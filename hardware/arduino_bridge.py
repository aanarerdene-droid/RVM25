#!/usr/bin/env python3
"""Forward chute sensor events to a paired XOT17 machine over authenticated HTTP."""
import argparse
import base64
import hashlib
import hmac
import json
import os
import queue
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlsplit

BAUD = 9600
RETRY_SECONDS = 3


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def make_pair_code(machine, key):
    payload = {'machine_id': machine, 'nonce': secrets.token_urlsafe(18), 'exp': int(time.time()) + 240}
    part = 'XOT17P1.' + b64(json.dumps(payload, separators=(',', ':')).encode())
    return part + '.' + b64(hmac.new(key.encode(), part.encode(), hashlib.sha256).digest())


def send_json(url, machine, key, endpoint, payload):
    request = urllib.request.Request(url.rstrip('/') + endpoint, data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json', 'X-Device-Key': key}, method='POST')
    with urllib.request.urlopen(request, timeout=4) as response:
        return json.load(response)


def find_port():
    from serial.tools import list_ports
    ports = list(list_ports.comports())
    matches = [p for p in ports if any(s in (p.device + ' ' + (p.description or '')).lower()
               for s in ('cu.usbmodem', 'cu.usbserial', 'ttyacm', 'ttyusb', 'arduino'))]
    # On Windows, only auto-select a COM port when it identifies as Arduino/USB serial.
    matches += [p for p in ports if p not in matches and p.device.upper().startswith('COM')
                and ('usb' in (p.description or '').lower() or p.vid is not None)]
    if len(matches) > 1:
        raise RuntimeError('Multiple serial devices found; choose one with --port: ' + ', '.join(p.device for p in matches))
    return matches[0].device if matches else None


class Bridge:
    def __init__(self, url, machine, key):
        self.url, self.machine, self.key = url.rstrip('/'), machine, key
        self.pending = queue.Queue(maxsize=1000)
        self.lock = threading.Lock()
        self.pairing_id = None
        self.heartbeat_at = 0.0
        self.serial_at = 0.0
        self.running = True

    def on_line(self, line):
        if line not in ('READY:XOT17_RVM', 'PING', 'BOTTLE:1'):
            return
        with self.lock:
            self.serial_at = time.monotonic()
            pairing = self.pairing_id if time.monotonic() - self.heartbeat_at <= 15 else None
        if line == 'BOTTLE:1':
            if not pairing:
                print('Bottle not credited: no recently confirmed active pairing.', flush=True)
                return
            event = {'machine_id': self.machine, 'bottles': 1, 'event_id': uuid.uuid4().hex, 'pairing_id': pairing}
            try:
                self.pending.put_nowait(event)
            except queue.Full:
                print('Bottle not credited: bridge queue is full.', file=sys.stderr, flush=True)

    def disconnected(self):
        with self.lock:
            self.serial_at = 0
            self.pairing_id = None
            self.heartbeat_at = 0

    def worker(self):
        next_heartbeat = 0.0
        event = None
        next_retry = 0.0
        while self.running:
            now = time.monotonic()
            with self.lock:
                sensor_alive = bool(self.serial_at and now - self.serial_at <= 12)
            if sensor_alive and now >= next_heartbeat:
                try:
                    response = send_json(self.url, self.machine, self.key, '/api/hardware/heartbeat',
                                         {'machine_id': self.machine, 'sensor': 'ultrasonic'})
                    with self.lock:
                        self.pairing_id = response.get('pairing_id')
                        self.heartbeat_at = time.monotonic()
                except (urllib.error.URLError, OSError, ValueError) as exc:
                    print('Heartbeat failed:', exc, file=sys.stderr, flush=True)
                next_heartbeat = time.monotonic() + 5
            if event is None:
                try: event = self.pending.get_nowait()
                except queue.Empty: pass
            if event and now >= next_retry:
                try:
                    result = send_json(self.url, self.machine, self.key, '/api/hardware/deposit', event)
                    player = result.get('player', {})
                    print('Credited player', player.get('id', '?'), 'rank', result.get('rank'),
                          '+', result.get('earned_points'), 'points', flush=True)
                    event = None
                except urllib.error.HTTPError as exc:
                    if 400 <= exc.code < 500:
                        print('Deposit not credited (HTTP %s); pairing may have expired or event was already accepted.' % exc.code, file=sys.stderr, flush=True)
                        event = None
                    else:
                        print('Deposit retry:', exc, file=sys.stderr, flush=True); next_retry = time.monotonic() + RETRY_SECONDS
                except (urllib.error.URLError, OSError, ValueError) as exc:
                    print('Deposit retry:', exc, file=sys.stderr, flush=True); next_retry = time.monotonic() + RETRY_SECONDS
            time.sleep(.1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', help='Serial port; auto-detect when omitted')
    parser.add_argument('--url', default=os.environ.get('RVM_SERVER_URL', 'http://127.0.0.1:8000'))
    parser.add_argument('--machine', default='RVM-UB-01')
    parser.add_argument('--key', default=os.environ.get('HARDWARE_API_KEY'), help='Device key; prefer HARDWARE_API_KEY environment variable')
    parser.add_argument('--pair-code', action='store_true', help='Print one short-lived pairing code and exit')
    args = parser.parse_args()
    if not args.key or len(args.key.encode()) < 32:
        parser.error('Set HARDWARE_API_KEY (or --key) to this machine’s unique key of at least 32 bytes.')
    url = urlsplit(args.url)
    if url.scheme not in ('http','https') or not url.netloc:
        parser.error('--url must be an HTTP(S) server URL')
    if url.scheme != 'https' and url.hostname not in ('localhost','127.0.0.1','::1'):
        parser.error('Remote servers must use HTTPS to protect the device key')
    if args.pair_code:
        print(make_pair_code(args.machine, args.key)); return
    try:
        import serial
    except ImportError:
        parser.error('pyserial is required: python3 -m pip install -r requirements.txt')
    bridge = Bridge(args.url, args.machine, args.key)
    threading.Thread(target=bridge.worker, daemon=True).start()
    try:
        while True:
            try:
                port = args.port or find_port()
                if not port: raise RuntimeError('No Arduino serial port found')
                print('Connecting to', port, flush=True)
                with serial.Serial(port, BAUD, timeout=.5) as connection:
                    while True:
                        line = connection.readline().decode('ascii', errors='replace').strip()
                        if line: bridge.on_line(line)
            except (serial.SerialException, OSError, RuntimeError) as exc:
                bridge.disconnected();print('Serial unavailable:', exc, file=sys.stderr, flush=True);time.sleep(RETRY_SECONDS)
    except KeyboardInterrupt:
        bridge.running = False;print('\nBridge stopped.', flush=True)


if __name__ == '__main__':
    main()
