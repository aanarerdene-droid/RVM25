"""Local XOT17 demo server with a shared support-request inbox."""
from __future__ import annotations

import json
import csv
from functools import lru_cache
import os
import posixpath
import sys
import time
from collections import defaultdict, deque
import auth_backend
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
    """Candidate data shares the CU directory source used by the admin map."""
    try:
        data = json.loads((ROOT / 'data' / 'cu_branches.json').read_text(encoding='utf-8'))
        if not isinstance(data, dict) or not isinstance(data.get('branches'), list) or not isinstance(data.get('candidates'), list):
            raise ValueError('Invalid CU data format')
    except (OSError, ValueError) as exc:
        from cu_locations_fallback import FALLBACK_LOCATIONS
        print(f'Warning: shared CU data unavailable ({exc}); using bundled candidate snapshot.', file=sys.stderr)
        return [{**item, 'district': item.get('district') or ('Сүхбаатар' if item.get('id') in ('RVM-CU-05', 'RVM-CU-12') else None)} for item in FALLBACK_LOCATIONS]
    branches = {branch['id']: branch for branch in data['branches']}
    locations = []
    for candidate in data['candidates']:
        item = candidate.copy()
        branch = branches.get(item.get('branch_id'))
        if branch:
            item.update(latitude=branch.get('latitude'), longitude=branch.get('longitude'), lat=branch.get('latitude'), lng=branch.get('longitude'), address=branch.get('address'))
        locations.append(item)
    missing_coords = [x['id'] for x in locations if x.get('latitude') is None or x.get('longitude') is None]
    missing_districts = [x['id'] for x in locations if not x.get('district')]
    if missing_coords: print('Warning: CU candidates missing coordinates: ' + ', '.join(missing_coords), file=sys.stderr)
    if missing_districts: print('Warning: CU candidates missing district: ' + ', '.join(missing_districts), file=sys.stderr)
    return locations


class XOT17Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        if getattr(self, '_private_response', False):
            self.send_header('Cache-Control', 'no-store')
        super().end_headers()

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
                or requested == REQUESTS_FILE or requested.suffix in ('.py', '.sqlite', '.sqlite3', '.db'))

    def _viewer(self):
        with auth_backend.connect() as db:
            return auth_backend.current(self, db)

    def _redirect(self, target):
        self.send_response(302)
        self.send_header('Location', target)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def _forbidden(self, page=False):
        if not page:
            self._send_json(403, {'error': 'Admin access required.', 'redirect': '/'});return
        body=b'<!doctype html><html><head><meta http-equiv="refresh" content="0;url=/"><title>Access denied</title></head><body>Admin access required. <a href="/">Return to the app</a>.</body></html>'
        self.send_response(403);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers()
        if self.command != 'HEAD': self.wfile.write(body)

    def _path(self):
        return posixpath.normpath('/' + unquote(urlsplit(self.path).path).lstrip('/'))

    def _serve_page(self, head=False):
        path = self._path()
        if self._blocked_static(path):
            self.send_error(404); return
        # Public assets are required by the login page; application HTML is guarded.
        if path.startswith(('/assets/', '/public/', '/models/')):
            return super().do_HEAD() if head else super().do_GET()
        if path.startswith('/api/'):
            self._private_response=True
            if head: self.send_error(404); return
            if not path.startswith('/api/hardware/') and path not in ('/api/auth/login','/api/auth/register') and not self._viewer():
                self._send_json(401, {'error':'Sign in required.'});return
            if path == '/api/rvm/locations':
                if not self._viewer(): self._send_json(401, {'error':'Sign in required.'}); return
                try: self._send_json(200, {'locations': rvm_locations()})
                except (OSError, ValueError, KeyError): self._send_json(503, {'error':'Location data unavailable.'})
                return
            if path == '/api/requests':
                user=self._viewer()
                if not user: self._send_json(401, {'error':'Sign in required.'});return
                if not auth_backend.is_admin(user): self._forbidden();return
                with REQUEST_LOCK: self._send_json(200, read_requests())
                return
            if path.startswith('/api/admin/'):
                user=self._viewer()
                if not user: self._send_json(401, {'error':'Sign in required.'});return
                if not auth_backend.is_admin(user): self._forbidden();return
            if auth_backend.handle(self, 'GET', path): return
            self.send_error(404);return
        self._private_response=True
        user=self._viewer()
        if path in ('/login','/login.html'):
            if user: self._redirect('/admin' if auth_backend.is_admin(user) else '/');return
            self.path='/login.html'
        else:
            if not user: self._redirect('/login');return
            admin_pages={'/admin','/admin/','/index.html','/users.html','/requests.html','/branches.html','/deployment.html','/machine.html'}
            if path in admin_pages or path.startswith('/admin/'):
                if not auth_backend.is_admin(user): self._forbidden(page=True);return
                if path in ('/admin','/admin/'): self.path='/index.html'
            elif path in ('/', '/game', '/device-test'): self.path='/rewards.html'
            elif path not in ('/rewards.html','/simulation.html'):
                # Data files backing the operations dashboard are admin-only.
                if not auth_backend.is_admin(user): self._forbidden();return
        return super().do_HEAD() if head else super().do_GET()

    def do_HEAD(self) -> None:
        self._serve_page(head=True)

    def do_GET(self) -> None:
        self._serve_page()

    def do_PATCH(self) -> None:
        self.do_POST()

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith('/api/'): self._private_response=True
        origin = self.headers.get('Origin')
        if origin and origin not in ('http://' + self.headers.get('Host', ''), 'https://' + self.headers.get('Host', '')):
            self._send_json(403, {'error': 'Invalid origin'}); return
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self._send_json(403, {'error': 'Cross-site requests are not allowed'}); return
        if path.startswith('/api/') and not path.startswith('/api/hardware/') and path not in ('/api/auth/login','/api/auth/register','/api/auth/logout') and not self._viewer():
            self._send_json(401, {'error':'Sign in required.'});return
        if path.startswith('/api/admin/'):
            user=self._viewer()
            if not user: self._send_json(401, {'error':'Sign in required.'});return
            if not auth_backend.is_admin(user): self._forbidden();return
        if path == '/api/requests' and not self._viewer():
            self._send_json(401, {'error':'Sign in required.'});return
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
    rvm_locations()  # Report incomplete candidate records at startup.
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
