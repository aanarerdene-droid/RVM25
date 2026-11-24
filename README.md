# XOT17 admin prototype

Run the XOT17 local preview server from this folder:

```sh
python3 server.py
```

Then visit `http://localhost:8000`.

Open the admin dashboard at `http://localhost:8000/` and the customer app at `http://localhost:8000/rewards.html`. Both pages use the local request API; customer requests are saved in `data/support_requests.json` and the admin inbox refreshes every three seconds. Keep `server.py` running while using the request flow. Opening the HTML files directly bypasses the shared API. The server binds to all interfaces and reads its port from `PORT`.

The deployment planner in `index.html` deliberately leaves branches unassigned until store-traffic data is supplied. Add reviewed recommendations to `data/deployment_plan.js`: high-footfall sites can be marked `rvm`, and lower-volume weekly-pickup sites can be marked `compactor`. The current location data contains branch listings, not visits, bottle volume, or verified machine placement. The ten numbered areas and audience descriptions from the team template are shown as proposed pilot candidates in `data/pilot_candidates.js`; they are not verified branch addresses or measured traffic rankings.

The CU, GS25, and MGL directory is generated from `cu_mongolia_642_branch_locations.csv`, `gs25_mongolia_branch_locations.csv`, `mglstore_food_organization_locations.csv`, and `data/store_locations.js`. The location map is drawn locally from supplied coordinates, so it works without external map tiles. CU and GS25 entries have coordinates; MGL has 535 address-only listings with Google Maps search links and cannot appear as map pins until coordinates are added. Machine placements, fill levels, bottle counts, rewards activity, and dashboard totals are illustrative prototype data; they are not live machine or user records.


For the colored Fusion model, insert `RVM25_reverse_vending_machine_color.3mf`. The older STL file is monochrome. See `RVM25_model_notes.md` for model and QR details.

## Bottle return simulation

Open `simulation.html` to play the illustrative QR pairing → bottle check → compaction → collection → demo points sequence. It is a scripted concept cutaway; the internal conveyor, sensor, and compactor are not physically modeled in the Fusion assembly.

## Player accounts and saved demo progress

Run `python3 server.py` and visit `http://localhost:8000/login` to register or sign in with email and password. The local server stores scrypt password hashes, accounts, and demo progress in `data/private/accounts.sqlite3`. This directory is blocked from the web server; do not publish or commit it. Set `XOT17_DB_PATH` to store the database elsewhere. New accounts start at zero; existing browser-only guest progress is kept separate and is not imported.

A stable secret is created automatically in `data/private/session.secret` (keep it private and back it up with the database). Alternatively, set a strong, persistent `AUTH_SECRET` environment variable before starting the server, for example `export AUTH_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"`. The server binds to all interfaces by default; set `XOT17_HOST=127.0.0.1` to restrict it to this computer; cookies use HttpOnly and SameSite=Lax. `XOT17_SECURE_COOKIE=1` adds the Secure flag and should be used only behind properly configured HTTPS. The built-in Python HTTP server is a demo server and needs hardening before a public production deployment.

To enable the protected player directory, first register an account, stop the server, then run `python3 server.py --make-admin you@example.com` and restart the server with the same database path and secret. Sign in with that account and open `http://localhost:8000/users.html`. Registration cannot assign admin roles. The directory refreshes every 10 seconds.

Logged-in bottle insertions and completed embedded simulator cycles each save 10 **demo** points and one bottle, and demo reward redemptions deduct their fixed costs. Scan/connect alone does not credit points. The simulator and scanner are not connected to physical machine validation; these values must not be used as verified recycling records or real rewards. Requests and other existing admin pages remain prototype features and are not protected by this player directory's role check.

## Avatar and player card

After registration, the player opens the avatar editor; signed-in players can reopen it using their avatar in the header. Avatar choices are validated and saved to the account. Existing accounts receive the default avatar automatically when the server starts. The player card uses saved demo statistics and can be downloaded as PNG; sharing uses the browser's native share sheet where available, or copies a text summary and app URL when clipboard access is available. Browser sharing and clipboard APIs may require HTTPS or localhost.

## Open the app on a phone

Open the app through the server, never as a `file://` page. For local Wi-Fi testing on a trusted network, run `python3 server.py`, find your computer's local IP address, and open `http://<computer-local-IP>:8000/rewards.html` on the phone. Keep the server running. The optional environment settings are shown in `.env.example`; export them in your shell, as the server does not automatically load `.env` files. `PORT` can override 8000.

This opt-in HTTP mode sends passwords and cookies without transport encryption and exposes the existing prototype admin and support pages on the network. Use only a trusted test network and test accounts. For a real deployment, use a production application server with HTTPS, `XOT17_SECURE_COOKIE=1`, a persistent database and secret, and access controls for all admin/support pages; the built-in preview server is not production-ready.

## PostgreSQL and Render configuration

Install the dependency with `python3 -m pip install -r requirements.txt`. When `DATABASE_URL` is set to a PostgreSQL connection URL, the account API uses PostgreSQL and creates its tables at startup; otherwise it uses SQLite. The two databases are independent: setting `DATABASE_URL` does not migrate existing local accounts or demo progress. Back up and explicitly migrate data before switching if it must be preserved. PostgreSQL connection failures stop startup rather than silently falling back to SQLite.

Set `DATABASE_URL` and a long, random, stable `AUTH_SECRET` in the hosting environment. A PostgreSQL deployment requires `AUTH_SECRET`; do not use the generated local secret file in cloud hosting. Render web services bind to `0.0.0.0` and the supplied `PORT`. Exact start command: `python3 server.py`. For Render, use the internal database connection URL when the service and database share a region and workspace. Secure cookies default on when Render sets `RENDER`; on other HTTPS hosts set `XOT17_SECURE_COOKIE=1`. For local HTTP with PostgreSQL, leave it unset or set it to `0`.

The player accounts, sessions, avatar settings, and demo events use PostgreSQL when configured. The support-request inbox still uses `data/support_requests.json`, which is local to the server instance and is not durable across deployments or shared between instances. It and the prototype admin pages are not protected by the player-directory admin check. Do not expose the app publicly until the support inbox and all admin pages are protected and the preview HTTP server, rate limiting, and other production security needs have been addressed.

## UB World and Eco-Pac

The UB World tab shows the player's D–SSS rank from the verified IRL bottle total and changes its pixel city as ranks increase. Move with the on-screen arrows or arrow/WASD keys. The leaderboard requires login, refreshes every 10 seconds, and uses anonymous player IDs rather than email addresses; ties use account creation time and ID for a stable position.

Pickups and Eco-Pac rounds award only temporary practice score; simulator and games cannot change saved points, IRL bottles, rank, or city tier. Historical account balances are preserved, including points previously awarded by older demo versions.

## Verified receipt scanner and city

The scanner uses the camera in a secure browser context (HTTPS or localhost) and offers manual entry when camera access is unavailable. The city uses only `irlBottles`: tier 1 at 0–4, tier 2 at 5–14, and tier 3 at 15+. Existing bottle totals are preserved and classified as simulator counts during migration; they are not treated as verified real-world deposits. Simulator activity cannot increase the city tier.

Legacy receipt redemption is disabled. Verified deposits require the authenticated device and pairing flow described below.

## Interface style and machine connection

The app uses the XOT17 pixel-arcade theme throughout.

The demo connection remains a local practice screen and does not establish a machine session or award points. Hardware integration requires a provisioned device and a valid signed pairing code.

## 3D station viewer

The customer app and admin views load `models/XOT17_reverse_vending_station.obj` and its MTL with the bundled Three.js loaders. The logo texture is `public/images/xot17-logo.png` (a copy is present in `models/` for the MTL reference). The viewer scales and centers the original millimeter geometry and provides rotation, front-view, and reset controls. Serve the app through `python3 server.py`; JavaScript modules and model loading are not supported when opening the HTML directly as a `file://` URL.

## Verified deposit rank rates

Verified IRL bottles determine rank and the per-bottle award: D 0–4 (5 points), B 5–14 (6), A 15–29 (7), S 30–49 (8), SS 50–99 (9), and SSS 100+ (10). A batch crossing a threshold is calculated bottle by bottle. Practice simulator bottles do not change IRL rank. Existing points and bottle counts are preserved; old earned points are not recalculated.

Provision each machine with a unique random secret of at least 32 bytes. Set `XOT17_DEVICE_KEYS` to a private JSON object mapping machine IDs to their device keys, such as `{"RVM-UB-01":"<unique-long-random-device-key>"}`. Use HTTPS and never expose these secrets in frontend code. The machine displays a one-time QR or code `XOT17P1.<payload>.<signature>`: payload is unpadded base64url UTF-8 JSON with exactly `machine_id`, a random 16–64 character alphanumeric/underscore/hyphen `nonce`, and `exp` (Unix seconds, no more than five minutes ahead). The signature is unpadded base64url HMAC-SHA256 over ASCII `XOT17P1.<payload>` with that machine's key. A signed code is required even when selecting a machine by ID; an ID alone does not prove the user is at the machine. An authenticated user sends `{ "machine_id": "RVM-UB-01", "pairing_code": "XOT17P1...." }` to `POST /api/rvm/pair`; pairing lasts five minutes, cannot be taken over while active, and is cleared on logout or via `POST /api/rvm/unpair`.

A trusted machine sends `POST /api/hardware/deposit` with header `X-Device-Key: <device key>` and JSON `{ "machine_id": "RVM-UB-01", "event_id": "<unique event id>", "bottles": 1 }`. `bottles` defaults to 1 (maximum 100), and `event_id` must be unique per machine and 16–64 alphanumeric/underscore/hyphen characters. The server credits the currently paired authenticated user, rejects duplicates and expired sessions, and calculates points for each bottle at the tier reached by that bottle (the fifth bottle earns 6 points). A machine must have an actual trusted hardware integration before physical deposits work. Restart the server to apply the schema migration and device configuration.

## Arduino ultrasonic prototype

1. Connect the HC-SR04 TRIG to Arduino D9, ECHO to D10, VCC to 5V, and GND to GND. For boards whose inputs are not 5V tolerant, level-shift ECHO. Flash `hardware/arduino_rvm_ultrasonic/arduino_rvm_ultrasonic.ino`; the Arduino serial port runs at 9600 baud. Calibrate `DETECT_THRESHOLD_CM` to the installed chute and allow the chute to clear between items.
2. Install `python3 -m pip install -r requirements.txt`. Configure a **unique random key of at least 32 bytes** for the machine in server-side `XOT17_DEVICE_KEYS`, restart the server, and set that same key as `HARDWARE_API_KEY` on the bridge host. No shared or default key is provided. Remote `RVM_SERVER_URL` must use HTTPS.
3. Run `python3 hardware/arduino_bridge.py --machine RVM-UB-01`. Specify `--port /dev/cu.usbmodem...` (or the relevant `ttyACM`, `ttyUSB`, or COM port) if auto-detection cannot choose one. Set `RVM_SERVER_URL` or pass `--url` for a remote host. Unplugging and reconnecting the Arduino causes automatic retries.
4. To generate a short-lived pairing code for a trusted operator, run `python3 hardware/arduino_bridge.py --machine RVM-UB-01 --pair-code` on the trusted bridge host. Enter that code and machine ID in Connect to Machine while signed in. The code expires in four minutes and can be used only once. After pairing, wait for the next heartbeat before inserting a bottle. The hardware status appears online for 15 seconds after the last authenticated heartbeat or accepted deposit.

The bridge captures the active pairing identifier when it receives each sensor event, and retries transient HTTP errors with the same event ID. Events cannot be credited to a later pairing. Events received without a recently confirmed pairing, rejected by the server, or left in memory when the bridge stops are **not credited**; the terminal reports failures. This basic sensor detects obstructions, not PET material or bottle identity, and requires physical calibration and additional validation before it can be used for real rewards. A five-minute pairing expires automatically; issue a fresh code for a new session.
# RVM25

## Sign-in and administrator access

All app pages require a signed-in account. `/` opens the player app, and `/admin` opens the operations dashboard for an administrator. The server recognizes the `ADMIN` role or an existing account whose email matches `ADMIN_EMAIL` (case-insensitive). Configure `ADMIN_EMAIL` only after creating that account through a trusted bootstrap procedure: while the variable is set, public registration of that address is blocked so an unauthenticated visitor cannot claim it. Alternatively, register an account and run `python3 server.py --make-admin you@example.com` with the same `DATABASE_URL` and `AUTH_SECRET`.

On Render set `DATABASE_URL`, a stable random `AUTH_SECRET` of at least 32 characters, and `ADMIN_EMAIL` if using email-based admin access. Render sets `PORT`; secure cookies default on Render and can be set explicitly with `XOT17_SECURE_COOKIE=1`. `XOT17_DEVICE_KEYS` is required only for configured physical machines. Admin page requests by non-admins return HTTP 403 and direct the browser back to the player app; APIs return a 403 JSON response.
