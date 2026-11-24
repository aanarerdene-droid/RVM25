"""Local XOT17 demo server with a shared support-request inbox."""
from __future__ import annotations

import json
import csv
from functools import lru_cache
import os
import sys
import time
from collections import defaultdict, deque
import auth_backend
from cu_locations_fallback import FALLBACK_LOCATIONS
import threading
import uuid
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parent
REQUESTS_FILE = ROOT / "data" / "support_requests.json"
REQUEST_LOCK = threading.Lock()
MAX_BODY_BYTES = 12_000
AUTH_ATTEMPTS = defaultdict(deque)
AUTH_LOCK = threading.Lock()


def read_requests() -> list[dict]:
    try:
        value = json.loads(REQUESTS_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


@lru_cache(maxsize=1)
def rvm_locations():
    """Read a portable CSV when available; preserve unknowns in the bundled snapshot."""
    candidates = (ROOT / 'ub_cu_17_locations.csv', ROOT / 'data' / 'ub_cu_17_locations.csv',
                  ROOT / 'static' / 'ub_cu_17_locations.csv', Path.home() / 'Downloads' / 'ub_cu_17_locations.csv')
    def first(row, *keys):
        for key in keys:
            value = row.get(key)
            if value is not None and str(value).strip(): return str(value).strip()
        return None
    def number(value):
        try: return float(value)
        except (TypeError, ValueError): return None
    def normalized(rows):
        result=[]
        for i, raw in enumerate(rows, 1):
            row={str(k).strip().lower():v for k,v in raw.items() if k is not None}
            name=first(row,'cu_location_or_area','name','branch','store_name','branch_name')
            if not name: raise ValueError('Location name is missing')
            place_id=first(row,'map_place_id','google_place_id','place_id')
            match=next((item for item in FALLBACK_LOCATIONS if place_id and item.get('place_id')==place_id),None)
            lat=number(first(row,'latitude','lat'));lon=number(first(row,'longitude','lng','lon'))
            if lat is None and lon is None and match: lat,lon=match['latitude'],match['longitude']
            if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180): lat=lon=None
            record={'id':first(row,'machine_id','id') or f'RVM-CU-{i:02}', 'code':f'{i:02}', 'number':i,
                'name':name, 'place_id':place_id,'note':first(row,'location_note','note') or '',
                'city':first(row,'city') or 'Ulaanbaatar, Mongolia', 'ranking_basis':first(row,'ranking_basis'),
                'latitude':lat,'longitude':lon,'lat':lat,'lng':lon,
                'district':first(row,'district','district_or_soum') or (match['district'] if match else None),
                'address':first(row,'address','street_address') or (match['address'] if match else None),
                'matched_name':match['matched_name'] if match else None,
                'coordinate_source':('CSV' if first(row,'lat','latitude') and first(row,'lng','lon','longitude') else match['coordinate_source'] if match else None),
                'machine_status':'unverified','status':'UNVERIFIED'}
            result.append(record)
        if len(result)!=17: raise ValueError('Expected 17 candidates')
        return result
    for path in candidates:
        try:
            with path.open(encoding='utf-8-sig', newline='') as source:
                return normalized(list(csv.DictReader(source)))
        except (OSError, UnicodeError, ValueError, csv.Error):
            continue
    return [item.copy() for item in FALLBACK_LOCATIONS]


class XOT17Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _send_json(self, status: int, payload: object, cookie: str = "") -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        if cookie: self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(encoded)

    def _blocked_static(self, path: str) -> bool:
        requested = (ROOT / unquote(path).lstrip('/')).resolve()
        return (any(part.startswith('.') for part in Path(unquote(path)).parts if part not in ('.', '..', '/'))
                or requested == auth_backend.SECRET_FILE.parent or auth_backend.SECRET_FILE.parent in requested.parents
                or requested == auth_backend.DB or requested == auth_backend.DB.parent or auth_backend.DB.parent in requested.parents
                or requested.suffix in ('.py', '.sqlite', '.sqlite3', '.db'))

    def do_HEAD(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith('/api/') or self._blocked_static(path):
            self.send_error(404); return
        if path == '/login': self.path = '/login.html'
        super().do_HEAD()

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == '/api/rvm/locations':
            try: self._send_json(200, {'locations': rvm_locations()})
            except (OSError, ValueError, KeyError): self._send_json(503, {'error': 'Location data unavailable.'})
            return
        if auth_backend.handle(self, 'GET', path): return
        if self._blocked_static(path):
            self.send_error(404); return
        if path == '/login':
            self.path = '/login.html'
            return super().do_GET()
        if path == "/api/requests":
            with REQUEST_LOCK:
                self._send_json(200, read_requests())
            return
        super().do_GET()

    def do_PATCH(self) -> None:
        self.do_POST()

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        origin = self.headers.get('Origin')
        if origin and origin not in ('http://' + self.headers.get('Host', ''), 'https://' + self.headers.get('Host', '')):
            self._send_json(403, {'error': 'Invalid origin'}); return
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self._send_json(403, {'error': 'Cross-site requests are not allowed'}); return
        if path in ('/api/auth/login', '/api/auth/register'):
            with AUTH_LOCK:
                attempts = AUTH_ATTEMPTS[self.client_address[0]]; cutoff = time.monotonic() - 60
                while attempts and attempts[0] < cutoff: attempts.popleft()
                if len(attempts) >= 10:
                    self._send_json(429, {'error':'Too many attempts. Try again shortly.'}); return
                attempts.append(time.monotonic())
        if self.headers.get_content_type() != "application/json":
            self._send_json(415, {"error": "Content-Type must be application/json"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY_BYTES:
                self._send_json(413, {"error": "Request is empty or too large"})
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Expected an object")
            if auth_backend.handle(self, self.command, path, payload): return
            if path != '/api/requests' or self.command != 'POST':
                self._send_json(404, {'error':'Not found'}); return
            request_type = str(payload.get("type", "")).strip()[:100]
            message = str(payload.get("message", "")).strip()[:700]
            location = str(payload.get("location", "")).strip()[:100]
            if not request_type or not message:
                self._send_json(400, {"error": "Topic and message are required"})
                return
            item = {
                "id": "LW-" + uuid.uuid4().hex[:8].upper(),
                "type": request_type,
                "location": location,
                "message": message,
                "createdAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                "status": "New",
            }
            with REQUEST_LOCK:
                requests = read_requests()
                requests.insert(0, item)
                REQUESTS_FILE.parent.mkdir(parents=True, exist_ok=True)
                temporary = REQUESTS_FILE.with_suffix(".tmp")
                temporary.write_text(json.dumps(requests, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                temporary.replace(REQUESTS_FILE)
            self._send_json(201, item)
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "Invalid request data"})


def main() -> None:
    auth_backend.init()
    if len(sys.argv) == 3 and sys.argv[1] == '--make-admin':
        auth_backend.promote(sys.argv[2]); return
    host = '0.0.0.0'
    try:
        port = int(os.environ.get('PORT', '8000'))
        if not 1 <= port <= 65535: raise ValueError()
    except ValueError:
        raise SystemExit('PORT must be a number between 1 and 65535.')
    address = (host, port)
    server = ThreadingHTTPServer(address, XOT17Handler)
    print(f"XOT17 preview: http://localhost:{address[1]}/ (bound to {host})")
    if host not in ('127.0.0.1', 'localhost', '::1'):
        print('Network access enabled: use only on a trusted network; this demo server does not provide HTTPS.')
    print(f"Request inbox API: http://localhost:{address[1]}/api/requests")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping XOT17 preview.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
