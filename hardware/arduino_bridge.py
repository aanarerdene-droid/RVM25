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

BAUD = 115200
RETRY_SECONDS = 3
MAX_BACKOFF_SECONDS = 10


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
            # The server validates this pairing ID on every deposit. Keep the
            # last confirmed ID during an outage; never attach a later pairing.
            pairing = self.pairing_id
        if line == 'BOTTLE:1':
            if not pairing:
                print('Bottle not credited: no recently confirmed active pairing.', flush=True)
                return
            event = {'machine_id': self.machine, 'bottles': 1, 'event_id': uuid.uuid4().hex, 'pairing_id': pairing}
            try:
                self.pending.put_nowait(event)
                print('Bottle detected; sending event to server.', flush=True)
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
        retry_started = None
        retry_delay = 1.0
        slow_warning = False
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
                except urllib.error.HTTPError as exc:
                    if exc.code in (401, 403):
                        print('Device key rejected (HTTP %s). Check the machine ID and key.' % exc.code, file=sys.stderr, flush=True)
                    elif exc.code == 503:
                        print('Machine not configured or server waking up (HTTP 503). Check Render settings if this persists.', file=sys.stderr, flush=True)
                    else:
                        print('Heartbeat unavailable (HTTP %s); retrying.' % exc.code, file=sys.stderr, flush=True)
                except (urllib.error.URLError, OSError, ValueError):
                    print('Server unreachable or waking up; retrying.', file=sys.stderr, flush=True)
                next_heartbeat = time.monotonic() + 5
            if event is None:
                try:
                    event = self.pending.get_nowait()
                    retry_started = time.monotonic(); retry_delay = 1.0; slow_warning = False
                except queue.Empty: pass
            if event and now >= next_retry:
                try:
                    result = send_json(self.url, self.machine, self.key, '/api/hardware/deposit', event)
                    print('Bottle sent and credited: +%s points.' % result.get('earned_points', '?'), flush=True)
                    event = None
                except urllib.error.HTTPError as exc:
                    if exc.code == 409:
                        try: message = json.load(exc).get('error', '')
                        except (ValueError, OSError, AttributeError): message = ''
                        if message == 'Deposit already credited.':
                            print('Bottle was already credited; duplicate retry ignored.', flush=True)
                        else:
                            print('Bottle was not confirmed (HTTP 409): pairing expired or changed. Check the account history before retrying.', file=sys.stderr, flush=True)
                        event = None
                    elif exc.code in (401, 403):
                        print('Device key rejected (HTTP %s). Check the machine ID and key; event remains queued.' % exc.code, file=sys.stderr, flush=True)
                        next_retry = time.monotonic() + MAX_BACKOFF_SECONDS
                    elif 400 <= exc.code < 500:
                        print('Bottle rejected (HTTP %s). Check pairing and server configuration.' % exc.code, file=sys.stderr, flush=True)
                        event = None
                    else:
                        print('Server is waking up, please wait... (HTTP %s)' % exc.code, file=sys.stderr, flush=True)
                        next_retry = time.monotonic() + retry_delay; retry_delay = min(retry_delay * 2, MAX_BACKOFF_SECONDS)
                except (urllib.error.URLError, OSError, ValueError):
                    print('Server is waking up or unreachable, please wait...', file=sys.stderr, flush=True)
                    next_retry = time.monotonic() + retry_delay; retry_delay = min(retry_delay * 2, MAX_BACKOFF_SECONDS)
            if event and retry_started and time.monotonic() - retry_started >= 60 and not slow_warning:
                print('Server still unavailable after 60 seconds; the event is queued and retries will continue while the bridge runs.', file=sys.stderr, flush=True)
                slow_warning = True
            time.sleep(.1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', help='Serial port; auto-detect when omitted')
    parser.add_argument('--list-ports', action='store_true', help='List available serial ports and exit')
    parser.add_argument('--baud', type=int, default=BAUD, help='Serial baud rate (default 115200)')
    parser.add_argument('--url', default=os.environ.get('XOT17_URL') or os.environ.get('RVM_SERVER_URL', 'http://127.0.0.1:8000'))
    parser.add_argument('--machine', default='RVM-UB-01')
    parser.add_argument('--pair-code', action='store_true', help='Print one short-lived pairing code and exit')
    args = parser.parse_args()
    if args.list_ports:
        try:
            from serial.tools import list_ports
        except ImportError:
            parser.error('Install pyserial first: python -m pip install -r hardware/requirements.txt')
        ports = list(list_ports.comports())
        for port in ports: print('%s — %s' % (port.device, port.description or 'serial device'))
        if not ports: print('No serial ports found. Connect the Arduino with a USB data cable.')
        return
    args.key = os.environ.get('HARDWARE_API_KEY')
    if not args.key or len(args.key.encode()) < 32:
        parser.error('Set HARDWARE_API_KEY to this machine’s unique key of at least 32 bytes.')
    if args.baud <= 0: parser.error('--baud must be a positive number.')
    url = urlsplit(args.url)
    if url.scheme not in ('http','https') or not url.netloc or url.username or url.password or url.query or url.fragment:
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
                with serial.Serial(port, args.baud, timeout=.5) as connection:
                    print('Connected to %s at %s baud.' % (port, args.baud), flush=True)
                    while True:
                        line = connection.readline().decode('ascii', errors='replace').strip()
                        if line: bridge.on_line(line)
            except (serial.SerialException, OSError, RuntimeError) as exc:
                bridge.disconnected();print('Cannot open serial port. Check the port name, USB cable, and close Serial Monitor or other bridges:', exc, file=sys.stderr, flush=True);time.sleep(RETRY_SECONDS)
    except KeyboardInterrupt:
        bridge.running = False;print('\nBridge stopped.', flush=True)


if __name__ == '__main__':
    main()
