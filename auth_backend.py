"""Local account storage and authenticated demo-player API."""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timezone, timedelta
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('XOT17_DB_PATH', str(ROOT / 'data' / 'private' / 'accounts.sqlite3'))).expanduser().resolve()
SECRET = os.environ.get('AUTH_SECRET', '').encode()
SECRET_FILE = ROOT / 'data' / 'private' / 'session.secret'
SECURE_COOKIE = os.environ.get('XOT17_SECURE_COOKIE', '1' if os.environ.get('RENDER') else '0') == '1'
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', '').strip().lower()
COOKIE = 'xot17_session'
TTL = 7 * 24 * 60 * 60
EMAIL = re.compile(r'^[^\s@]{1,64}@[^\s@.]+(?:\.[^\s@.]+)+$')
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]
RECEIPT_SECRET = os.environ.get('XOT17_RECEIPT_SECRET', '').encode()
try:
    DEVICE_KEYS = json.loads(os.environ.get('XOT17_DEVICE_KEYS', '{}'))
    if not isinstance(DEVICE_KEYS, dict): DEVICE_KEYS = {}
except (ValueError, TypeError): DEVICE_KEYS = {}
PAIR_TTL = 300
DUMMY = None
RANK_TIERS = (('D', 0, 5), ('B', 5, 6), ('A', 15, 7), ('S', 30, 8), ('SS', 50, 9), ('SSS', 100, 10))

def get_rank_info(irl_bottles):
    count = max(0, int(irl_bottles))
    index = max(i for i, (_, minimum, _) in enumerate(RANK_TIERS) if count >= minimum)
    name, _, rate = RANK_TIERS[index]
    nxt = RANK_TIERS[index + 1] if index + 1 < len(RANK_TIERS) else None
    return {'rank': name, 'points_per_bottle': rate, 'next_rank': nxt[0] if nxt else None, 'bottles_to_next_rank': nxt[1] - count if nxt else 0}

def deposit_points(start, bottles):
    return sum(get_rank_info(start + i + 1)['points_per_bottle'] for i in range(bottles))
AVATAR_OPTIONS = {'hair': ['spiky','twintails','bob','messy','ponytail','buns','fringe','long'], 'hairColor':['#B86BFF','#00F0FF','#8CFF00','#302143','#664334','#E3AA56','#FA91B8','#FFFFFF'], 'face':['eyes','wink','happy','visor','blush'], 'outfit':['hoodie','tee','jacket','vest'], 'outfitColor':['#8A3FFC','#00AFC2','#598C22','#FF2A85','#2E303E','#EFE5FF'], 'bottom':['shorts','cargo','skirt','sneakers'], 'skin':['#FCE0C7','#E9B38F','#C98359','#95573D','#603826'], 'accessory':['none','headset','horn','bottle','leaf']}
DEFAULT_AVATAR = {key: values[0] for key,values in AVATAR_OPTIONS.items()}

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
class Database:
    """Small DB-API adapter; close connections at the end of each request."""
    def __init__(self):
        self.postgres = bool(DATABASE_URL)
        if self.postgres:
            import psycopg2
            import psycopg2.extras
            self.raw = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor, connect_timeout=10)
        else:
            DB.parent.mkdir(parents=True, exist_ok=True)
            self.raw = sqlite3.connect(DB, timeout=15)
            self.raw.row_factory = sqlite3.Row
            self.raw.execute('PRAGMA foreign_keys=ON')
    def execute(self, sql, params=()):
        if self.postgres:
            cursor = self.raw.cursor()
            cursor.execute(sql.replace('?', '%s'), params)
            return cursor
        return self.raw.execute(sql, params)
    def commit(self): self.raw.commit()
    def rollback(self): self.raw.rollback()
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type: self.raw.rollback()
            else: self.raw.commit()
        finally: self.raw.close()
        return False

def connect(): return Database()

def init():
    global DUMMY, SECRET
    if not SECRET and DATABASE_URL:
        raise RuntimeError('AUTH_SECRET must be set to a stable random value when DATABASE_URL is configured.')
    if not SECRET:
        SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(SECRET_FILE), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            SECRET = SECRET_FILE.read_bytes()
        else:
            SECRET = secrets.token_bytes(32)
            with os.fdopen(fd, 'wb') as f:
                f.write(SECRET)
        if len(SECRET) < 32:
            raise RuntimeError('Stored session secret is invalid; configure AUTH_SECRET or repair session.secret.')
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'USER' CHECK(role IN ('USER','ADMIN')), points INTEGER NOT NULL DEFAULT 0, bottles_recycled INTEGER NOT NULL DEFAULT 0, streak INTEGER NOT NULL DEFAULT 0, last_recycled_day TEXT, created_at TEXT NOT NULL, last_login_at TEXT, avatar_config TEXT NOT NULL DEFAULT '{}')""")
        db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires BIGINT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS player_events (id TEXT NOT NULL, user_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, PRIMARY KEY(id,user_id))")
        db.execute("CREATE TABLE IF NOT EXISTS receipt_claims (receipt_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), claimed_at TEXT NOT NULL, bottles INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS machine_pairings (machine_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires BIGINT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS machine_heartbeats (machine_id TEXT PRIMARY KEY, last_heartbeat_at BIGINT NOT NULL, sensor TEXT NOT NULL)")
        if db.postgres:
            db.execute("ALTER TABLE machine_pairings ADD COLUMN IF NOT EXISTS pairing_id TEXT")
        else:
            pairing_columns={row['name'] for row in db.execute('PRAGMA table_info(machine_pairings)')}
            if 'pairing_id' not in pairing_columns: db.execute('ALTER TABLE machine_pairings ADD COLUMN pairing_id TEXT')
        db.execute("CREATE TABLE IF NOT EXISTS pairing_tokens (token_id TEXT PRIMARY KEY, expires BIGINT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS game_rewards (user_id TEXT NOT NULL REFERENCES users(id), reward_day TEXT NOT NULL, coins INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id,reward_day))")
        if db.postgres:
            db.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS irl_bottles INTEGER NOT NULL DEFAULT 0')
            db.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS irl_points_earned INTEGER NOT NULL DEFAULT 0')
            columns={row['column_name'] for row in db.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='users'")}
            if 'sim_bottles' not in columns:
                db.execute('ALTER TABLE users ADD COLUMN sim_bottles INTEGER NOT NULL DEFAULT 0')
                db.execute('UPDATE users SET sim_bottles=bottles_recycled')
            db.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS eco_coins INTEGER NOT NULL DEFAULT 0')
            db.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_config TEXT NOT NULL DEFAULT '{}'")
            db.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_recycled_day TEXT")
        else:
            columns={row['name'] for row in db.execute('PRAGMA table_info(users)')}
            if 'avatar_config' not in columns: db.execute("ALTER TABLE users ADD COLUMN avatar_config TEXT NOT NULL DEFAULT '{}'")
            if 'eco_coins' not in columns: db.execute('ALTER TABLE users ADD COLUMN eco_coins INTEGER NOT NULL DEFAULT 0')
            if 'irl_bottles' not in columns: db.execute('ALTER TABLE users ADD COLUMN irl_bottles INTEGER NOT NULL DEFAULT 0')
            if 'irl_points_earned' not in columns: db.execute('ALTER TABLE users ADD COLUMN irl_points_earned INTEGER NOT NULL DEFAULT 0')
            if 'sim_bottles' not in columns:
                db.execute('ALTER TABLE users ADD COLUMN sim_bottles INTEGER NOT NULL DEFAULT 0')
                db.execute('UPDATE users SET sim_bottles=bottles_recycled')
    if not DATABASE_URL:
        try: os.chmod(DB, 0o600)
        except OSError: pass
    DUMMY = hash_password('not-a-real-password')

def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return 'scrypt$16384$8$1$' + salt.hex() + '$' + digest.hex()

def verify(password, stored):
    try:
        name, n, r, p, salt, expected = stored.split('$')
        if name != 'scrypt': return False
        value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(value, bytes.fromhex(expected))
    except (ValueError, TypeError): return False

def b64(data): return base64.urlsafe_b64encode(data).rstrip(b'=').decode()
def unb64(data): return base64.urlsafe_b64decode(data + '=' * (-len(data) % 4))
def sign(payload):
    head = b64(b'{"alg":"HS256","typ":"JWT"}')
    body = b64(json.dumps(payload, separators=(',', ':')).encode())
    msg = head + '.' + body
    return msg + '.' + b64(hmac.new(SECRET, msg.encode(), hashlib.sha256).digest())
def decode(token):
    try:
        head, body, signature = token.split('.')
        if not hmac.compare_digest(signature, b64(hmac.new(SECRET, (head+'.'+body).encode(), hashlib.sha256).digest())): return None
        if json.loads(unb64(head)) != {'alg':'HS256','typ':'JWT'}: return None
        data = json.loads(unb64(body))
        if not isinstance(data,dict) or not isinstance(data.get('exp'),int) or data['exp'] <= time.time(): return None
        return data
    except (ValueError, TypeError, KeyError, json.JSONDecodeError): return None

def session_cookie(value, max_age=TTL):
    return f'{COOKIE}={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}' + ('; Secure' if SECURE_COOKIE else '')
def issue(db, user_id):
    sid = secrets.token_urlsafe(32); expiry = int(time.time()) + TTL
    db.execute('INSERT INTO sessions VALUES (?,?,?)', (sid, user_id, expiry))
    return sign({'sub':user_id,'sid':sid,'exp':expiry})
def current(handler, db):
    try:
        jar = SimpleCookie(); jar.load(handler.headers.get('Cookie',''))
        token = jar[COOKIE].value if COOKIE in jar else ''
        payload = decode(token)
        if not payload: return None
        return db.execute('SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE u.id=? AND s.id=? AND s.expires>?', (payload.get('sub'),payload.get('sid'),int(time.time()))).fetchone()
    except (ValueError, KeyError): return None

def is_admin(user):
    return bool(user and (str(user['role']).upper() == 'ADMIN' or (ADMIN_EMAIL and user['email'].strip().lower() == ADMIN_EMAIL)))

def safe(row, admin=False):
    value = {'id':row['id'],'email':row['email'],'role':'ADMIN' if is_admin(row) else 'USER','points':row['points'],'bottlesRecycled':row['bottles_recycled'],'streak':row['streak'],'createdAt':row['created_at'],'ecoCoins':row['eco_coins'],'irlBottles':row['irl_bottles'],'irlPointsEarned':row['irl_points_earned'],'simBottles':row['sim_bottles']}
    value.update(get_rank_info(row['irl_bottles']))
    try:
        config=json.loads(row['avatar_config'])
        value['avatarConfig']={key: config.get(key) if config.get(key) in choices else DEFAULT_AVATAR[key] for key,choices in AVATAR_OPTIONS.items()} if isinstance(config,dict) else dict(DEFAULT_AVATAR)
    except (ValueError, TypeError): value['avatarConfig']=dict(DEFAULT_AVATAR)
    if admin: value['lastLoginAt'] = row['last_login_at']
    return value

def valid_auth(payload):
    if not isinstance(payload,dict) or set(payload) != {'email','password'}: return None
    email,password = payload['email'],payload['password']
    if not isinstance(email,str) or not isinstance(password,str): return None
    email=email.strip().lower()
    if len(email)>254 or not EMAIL.fullmatch(email) or len(password)<6 or len(password)>256 or len(password.encode())>1024: return None
    return email,password

def handle(handler, method, path, payload=None):
    if path not in ('/api/auth/register','/api/auth/login','/api/auth/logout','/api/auth/me','/api/user/sync','/api/user/avatar','/api/admin/users','/api/leaderboard','/api/game/reward','/api/scan/irl','/api/hardware/deposit','/api/rvm/live-status','/api/rvm/pair','/api/rvm/unpair','/api/hardware/heartbeat'): return False
    with connect() as db:
        if path in ('/api/auth/register','/api/auth/login') and method=='POST':
            credentials=valid_auth(payload)
            if not credentials: handler._send_json(400,{'error':'Enter a valid email and a password of 6–256 characters.'}); return True
            email,password=credentials
            if path.endswith('register'):
                if ADMIN_EMAIL and email==ADMIN_EMAIL:
                    handler._send_json(403,{'error':'This account must be provisioned before admin access is enabled.'});return True
                hashed=hash_password(password); uid=str(uuid.uuid4()); stamp=now()
                try: db.execute('INSERT INTO users(id,email,password_hash,created_at,last_login_at) VALUES(?,?,?,?,?)',(uid,email,hashed,stamp,stamp))
                except Exception as exc:
                    if not isinstance(exc, sqlite3.IntegrityError) and not (db.postgres and getattr(exc, 'pgcode', None) == '23505'):
                        raise
                    db.rollback();handler._send_json(409,{'error':'This email is already registered.'}); return True
            else:
                row=db.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
                if not verify(password,row['password_hash'] if row else DUMMY) or not row:
                    handler._send_json(401,{'error':'Invalid email or password.'}); return True
                uid=row['id'];db.execute('UPDATE users SET last_login_at=? WHERE id=?',(now(),uid))
            token=issue(db,uid); row=db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone();db.commit()
            handler._send_json(201 if path.endswith('register') else 200, safe(row),cookie=session_cookie(token));return True
        if path=='/api/auth/logout' and method=='POST':
            try:
                jar=SimpleCookie();jar.load(handler.headers.get('Cookie',''));data=decode(jar[COOKIE].value) if COOKIE in jar else None
                user=current(handler,db)
                if user: db.execute('DELETE FROM machine_pairings WHERE user_id=?',(user['id'],))
                if data: db.execute('DELETE FROM sessions WHERE id=?',(data.get('sid'),))
            except (ValueError,KeyError): pass
            handler._send_json(200,{'ok':True},cookie=session_cookie('',0));return True
        if path=='/api/auth/me' and method=='GET':
            user=current(handler,db)
            if not user: handler._send_json(401,{'error':'Sign in required.'});return True
            handler._send_json(200,safe(user));return True
        if path=='/api/rvm/live-status' and method=='GET':
            user=current(handler,db)
            if not user: handler._send_json(401,{'error':'Sign in required.'});return True
            pair=db.execute('SELECT machine_id,expires FROM machine_pairings WHERE user_id=? AND expires>? ORDER BY expires DESC LIMIT 1',(user['id'],int(time.time()))).fetchone()
            requested=parse_qs(urlsplit(getattr(handler,'path','')).query).get('machine_id',[''])[0]
            target=pair['machine_id'] if pair else requested if requested in DEVICE_KEYS else ''
            heartbeat=db.execute('SELECT last_heartbeat_at FROM machine_heartbeats WHERE machine_id=?',(target,)).fetchone() if target else None
            handler._send_json(200, {**safe(user),'pairing':dict(pair) if pair else None,'hardware_online':bool(heartbeat and 0<=int(time.time())-heartbeat['last_heartbeat_at']<=15)});return True
        if path=='/api/admin/users' and method=='GET':
            user=current(handler,db)
            if not user: handler._send_json(401,{'error':'Sign in required.'});return True
            if not is_admin(user): handler._send_json(403,{'error':'Admin access required.'});return True
            handler._send_json(200,[safe(row,True) for row in db.execute('SELECT * FROM users ORDER BY created_at DESC, id DESC')]);return True
        if path=='/api/leaderboard' and method=='GET':
            user=current(handler,db)
            if not user: handler._send_json(401,{'error':'Sign in required.'});return True
            query="SELECT id,irl_bottles,avatar_config,ROW_NUMBER() OVER (ORDER BY irl_bottles DESC,created_at ASC,id ASC) AS place FROM users"
            rows=db.execute('SELECT * FROM ('+query+') ranked WHERE place<=25 OR id=? ORDER BY place',(user['id'],)).fetchall()
            me=next((r for r in rows if r['id']==user['id']),None)
            ahead=None
            if me and me['place']>1:
                ahead=db.execute('SELECT irl_bottles FROM ('+query+') ranked WHERE place=?',(me['place']-1,)).fetchone()
            def public(r):
                try: config=json.loads(r['avatar_config'])
                except (ValueError, TypeError): config={}
                config=config if isinstance(config,dict) else {}
                return {'name':'PLAYER-'+r['id'][:6].upper(),'avatarConfig':{k:config.get(k) if config.get(k) in choices else DEFAULT_AVATAR[k] for k,choices in AVATAR_OPTIONS.items()},'bottlesRecycled':r['irl_bottles'],'place':r['place'],'isMe':r['id']==user['id']}
            handler._send_json(200,{'players':[public(r) for r in rows if r['place']<=25],'me':public(me) if me else None,'toOvertake':max(1,ahead['irl_bottles']-me['irl_bottles']+1) if ahead else 0});return True
        if path=='/api/rvm/pair' and method=='POST':
            user=current(handler,db)
            if not user: handler._send_json(401,{'error':'Sign in required.'});return True
            if not isinstance(payload,dict) or set(payload)!={'machine_id','pairing_code'} or not isinstance(payload['machine_id'],str) or not isinstance(payload['pairing_code'],str) or len(payload['pairing_code'])>1024:
                handler._send_json(400,{'error':'Machine ID and pairing code required.'});return True
            machine=payload['machine_id'];key=DEVICE_KEYS.get(machine)
            if not isinstance(key,str) or len(key.encode())<32: handler._send_json(503,{'error':'Machine pairing is not configured.'});return True
            try:
                prefix,encoded,signature=payload['pairing_code'].split('.')
                expected=b64(hmac.new(key.encode(),(prefix+'.'+encoded).encode(),hashlib.sha256).digest())
                token=json.loads(unb64(encoded));stamp=int(time.time())
                if prefix!='XOT17P1' or not hmac.compare_digest(signature,expected) or not isinstance(token,dict) or set(token)!={'machine_id','nonce','exp'} or token['machine_id']!=machine or not isinstance(token['nonce'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}',token['nonce']) or type(token['exp']) is not int or not stamp<token['exp']<=stamp+PAIR_TTL: raise ValueError()
            except (ValueError,TypeError,KeyError,UnicodeError,json.JSONDecodeError):
                handler._send_json(400,{'error':'Invalid or expired machine pairing code.'});return True
            if not db.postgres: db.execute('BEGIN IMMEDIATE')
            tokenid=machine+':'+token['nonce']
            claim=db.execute('INSERT INTO pairing_tokens(token_id,expires) VALUES(?,?) ON CONFLICT(token_id) DO NOTHING',(tokenid,token['exp']))
            if claim.rowcount!=1: db.rollback();handler._send_json(409,{'error':'Pairing code already used.'});return True
            # Existing unexpired sessions cannot be taken by another user.
            expires=stamp+PAIR_TTL;pairing_id=secrets.token_urlsafe(24)
            paired=db.execute('INSERT INTO machine_pairings(machine_id,user_id,expires,pairing_id) VALUES(?,?,?,?) ON CONFLICT(machine_id) DO UPDATE SET user_id=excluded.user_id,expires=excluded.expires,pairing_id=excluded.pairing_id WHERE machine_pairings.expires<=? OR machine_pairings.user_id=excluded.user_id',(machine,user['id'],expires,pairing_id,stamp))
            if paired.rowcount!=1: db.rollback();handler._send_json(409,{'error':'Machine is already paired.'});return True
            db.execute('DELETE FROM machine_pairings WHERE user_id=? AND machine_id<>?',(user['id'],machine));db.commit()
            handler._send_json(200,{'machine_id':machine,'expires':expires});return True
        if path=='/api/rvm/unpair' and method=='POST':
            user=current(handler,db)
            if not user: handler._send_json(401,{'error':'Sign in required.'});return True
            db.execute('DELETE FROM machine_pairings WHERE user_id=?',(user['id'],));db.commit();handler._send_json(200,{'ok':True});return True
        if path=='/api/hardware/heartbeat' and method=='POST':
            if not isinstance(payload,dict) or set(payload)!={'machine_id','sensor'} or not isinstance(payload['machine_id'],str) or payload['sensor']!='ultrasonic': handler._send_json(400,{'error':'Invalid heartbeat.'});return True
            machine=payload['machine_id'];key=DEVICE_KEYS.get(machine);supplied=handler.headers.get('X-Device-Key','')
            if not isinstance(key,str) or len(key.encode())<32: handler._send_json(503,{'error':'Device is not configured.'});return True
            if not hmac.compare_digest(supplied.encode(),key.encode()): handler._send_json(401,{'error':'Invalid device credentials.'});return True
            stamp=int(time.time());db.execute('INSERT INTO machine_heartbeats(machine_id,last_heartbeat_at,sensor) VALUES(?,?,?) ON CONFLICT(machine_id) DO UPDATE SET last_heartbeat_at=excluded.last_heartbeat_at,sensor=excluded.sensor',(machine,stamp,'ultrasonic'))
            pair=db.execute('SELECT pairing_id FROM machine_pairings WHERE machine_id=? AND expires>?',(machine,stamp)).fetchone();db.commit()
            handler._send_json(200,{'ok':True,'pairing_id':pair['pairing_id'] if pair else None});return True
        if path=='/api/hardware/deposit' and method=='POST':
            if not isinstance(payload,dict) or not {'machine_id','event_id'} <= set(payload) or set(payload)-{'machine_id','event_id','bottles','pairing_id'} or not isinstance(payload['machine_id'],str) or not isinstance(payload['event_id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}',payload['event_id']) or type(payload.get('bottles',1)) is not int or not 1<=payload.get('bottles',1)<=100:
                handler._send_json(400,{'error':'Invalid deposit.'});return True
            machine=payload['machine_id'];key=DEVICE_KEYS.get(machine);supplied=handler.headers.get('X-Device-Key','')
            if not isinstance(key,str) or len(key.encode())<32: handler._send_json(503,{'error':'Device is not configured.'});return True
            if not hmac.compare_digest(supplied.encode(),key.encode()): handler._send_json(401,{'error':'Invalid device credentials.'});return True
            if not db.postgres: db.execute('BEGIN IMMEDIATE')
            pair=db.execute('SELECT * FROM machine_pairings WHERE machine_id=?'+(' FOR UPDATE' if db.postgres else ''),(machine,)).fetchone()
            if not pair or pair['expires']<=int(time.time()): db.rollback();handler._send_json(409,{'error':'No active machine pairing.'});return True
            if 'pairing_id' in payload and (not isinstance(payload['pairing_id'],str) or not pair['pairing_id'] or not hmac.compare_digest(payload['pairing_id'],pair['pairing_id'])): db.rollback();handler._send_json(409,{'error':'Machine pairing changed.'});return True
            uid=pair['user_id'];count=payload.get('bottles',1)
            if not db.execute('SELECT 1 FROM sessions WHERE user_id=? AND expires>?',(uid,int(time.time()))).fetchone(): db.rollback();handler._send_json(409,{'error':'Player session expired.'});return True
            row=db.execute('SELECT * FROM users WHERE id=?'+(' FOR UPDATE' if db.postgres else ''),(uid,)).fetchone()
            if not row: db.rollback();handler._send_json(404,{'error':'Player not found.'});return True
            claim=db.execute('INSERT INTO receipt_claims(receipt_id,user_id,claimed_at,bottles) VALUES(?,?,?,?) ON CONFLICT(receipt_id) DO NOTHING',('hardware:'+machine+':'+payload['event_id'],uid,now(),count))
            if claim.rowcount!=1: db.rollback();handler._send_json(409,{'error':'Deposit already credited.'});return True
            before=get_rank_info(row['irl_bottles']);earned=deposit_points(row['irl_bottles'],count)
            today=datetime.now(timezone.utc).date();last=row['last_recycled_day'];streak=row['streak'] if last==today.isoformat() else (row['streak']+1 if last==(today-timedelta(days=1)).isoformat() else 1)
            db.execute('UPDATE users SET irl_bottles=irl_bottles+?,points=points+?,irl_points_earned=irl_points_earned+?,streak=?,last_recycled_day=? WHERE id=?',(count,earned,earned,streak,today.isoformat(),uid))
            db.execute('INSERT INTO machine_heartbeats(machine_id,last_heartbeat_at,sensor) VALUES(?,?,?) ON CONFLICT(machine_id) DO UPDATE SET last_heartbeat_at=excluded.last_heartbeat_at,sensor=excluded.sensor',(machine,int(time.time()),'ultrasonic'))
            row=db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone();db.commit();info=get_rank_info(row['irl_bottles'])
            handler._send_json(200,{'player':safe(row),'accepted':count,'earned_points':earned,'ranked_up':before['rank']!=info['rank'],**info});return True
        if path=='/api/scan/irl' and method=='POST':
            handler._send_json(410,{'error':'Receipt credits are disabled. Pair with a machine.'});return True
        if path=='/api/game/reward' and method=='POST':
            handler._send_json(410,{'error':'Game rewards are practice only.'});return True
        if path=='/api/user/avatar' and method=='PATCH':
            user=current(handler,db)
            if not user: handler._send_json(401,{'error':'Sign in required.'});return True
            if not isinstance(payload,dict) or set(payload)!={'avatarConfig'} or not isinstance(payload['avatarConfig'],dict):
                handler._send_json(400,{'error':'Invalid avatar.'});return True
            config=payload['avatarConfig']
            if set(config)!=set(AVATAR_OPTIONS) or any(not isinstance(config[key],str) or config[key] not in choices for key,choices in AVATAR_OPTIONS.items()):
                handler._send_json(400,{'error':'Invalid avatar selection.'});return True
            db.execute('UPDATE users SET avatar_config=? WHERE id=?',(json.dumps(config,separators=(',',':')),user['id']))
            row=db.execute('SELECT * FROM users WHERE id=?',(user['id'],)).fetchone();db.commit();handler._send_json(200,safe(row));return True
        if path=='/api/user/sync' and method=='POST':
            user=current(handler,db)
            if not user: handler._send_json(401,{'error':'Sign in required.'});return True
            if not isinstance(payload,dict) or set(payload)!={'action','eventId'} or payload['action'] not in ('bottle','voucher','tree','tote') or not isinstance(payload['eventId'],str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,64}',payload['eventId']):
                handler._send_json(400,{'error':'Invalid action.'});return True
            if payload['action']=='bottle': handler._send_json(403,{'error':'Practice bottles cannot credit an account.'});return True
            if db.postgres:
                db.execute('SELECT id FROM users WHERE id=? FOR UPDATE', (user['id'],)).fetchone()
            else:
                db.execute('BEGIN IMMEDIATE')
            existing=db.execute('SELECT 1 FROM player_events WHERE id=? AND user_id=?',(payload['eventId'],user['id'])).fetchone()
            if not existing:
                row=db.execute('SELECT * FROM users WHERE id=?',(user['id'],)).fetchone();action=payload['action']
                cost={'voucher':200,'tree':400,'tote':600}[action]
                if row['points']<cost: db.rollback();handler._send_json(409,{'error':'Not enough points.'});return True
                db.execute('UPDATE users SET points=points-? WHERE id=?',(cost,user['id']))
                db.execute('INSERT INTO player_events VALUES(?,?,?)',(payload['eventId'],user['id'],now()))
            row=db.execute('SELECT * FROM users WHERE id=?',(user['id'],)).fetchone();db.commit();handler._send_json(200,safe(row));return True
        handler._send_json(405,{'error':'Method not allowed.'});return True

def promote(email):
    with connect() as db:
        cur=db.execute("UPDATE users SET role='ADMIN' WHERE email=?",(email.strip().lower(),))
        if cur.rowcount!=1: raise SystemExit('Account not found. Register it first.')
    print('Admin role granted to existing account.')
