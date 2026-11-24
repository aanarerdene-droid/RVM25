import io
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from hardware.arduino_bridge import Bridge


class BridgeRetryTests(unittest.TestCase):
    def run_bridge(self, respond):
        bridge = Bridge('http://127.0.0.1:8000', 'RVM-UB-02', 'x' * 32)
        with bridge.lock:
            bridge.pairing_id = 'original-pairing'
            bridge.heartbeat_at = time.monotonic()
        bridge.on_line('BOTTLE:1')
        with patch('hardware.arduino_bridge.send_json', side_effect=respond):
            worker = threading.Thread(target=bridge.worker, daemon=True)
            worker.start()
            deadline = time.monotonic() + 5
            while not bridge.pending.empty() and time.monotonic() < deadline:
                time.sleep(.05)
            time.sleep(1.5)
            bridge.running = False
            worker.join(timeout=2)
        return bridge

    def test_retry_reuses_event_and_pairing(self):
        events = []
        def send(url, machine, key, endpoint, payload):
            if endpoint.endswith('heartbeat'):
                return {'pairing_id': 'original-pairing'}
            events.append(dict(payload))
            if len(events) == 1:
                raise URLError('test outage')
            return {'earned_points': 5}
        self.run_bridge(send)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0], events[1])
        self.assertEqual(events[0]['pairing_id'], 'original-pairing')

    def test_duplicate_response_does_not_retry(self):
        events = []
        def send(url, machine, key, endpoint, payload):
            if endpoint.endswith('heartbeat'):
                return {'pairing_id': 'original-pairing'}
            events.append(payload)
            raise HTTPError(url, 409, 'Conflict', {}, io.BytesIO(b'{"error":"Deposit already credited."}'))
        self.run_bridge(send)
        self.assertEqual(len(events), 1)

if __name__ == '__main__':
    unittest.main()
