# DCIM API

FastAPI + SQLModel (SQLite) + Alembic. The API contract is in `../../docs/API.md`, and the schema is in `openapi.json`.

## Setup
```bash
cd apps/api
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.txt -r requirements-dev.txt   # runtime (incl. alembic) + test tools
```

## Migrate
```bash
.venv/bin/alembic upgrade head                 # creates/updates ./dcim.db
.venv/bin/alembic revision --autogenerate -m "describe change"   # after model changes
```
Set `DCIM_DATABASE_URL` (default `sqlite:///./dcim.db`) to use another database. The app and Alembic both read it.

## Run
```bash
.venv/bin/python -m app --reload               # http://127.0.0.1:8000 (DCIM_BIND_HOST / DCIM_PORT)
# equivalent: .venv/bin/uvicorn app.main:app --reload --no-proxy-headers
```
With the Vite dev proxy, no CORS is needed. For cross-origin callers, set `DCIM_CORS_ORIGINS`.

**Client IP and proxies (N-1).** Always start uvicorn with `--no-proxy-headers`, as `python -m app` does. Otherwise, by default, uvicorn believes `X-Forwarded-For` from 127.0.0.1, and the Vite dev proxy passes a client's own header straight through, so anyone could choose their IP and dodge the login rate limits. The app itself ignores `X-Forwarded-For` unless the direct peer is listed in `DCIM_TRUSTED_PROXIES` (IPs or CIDRs). Then it uses the right-most address that is not a trusted proxy.
- **Dev:** keep the Vite dev server on localhost (no `--host`). Every browser then shares 127.0.0.1, which is fine for one developer.
- **LAN / prod:** put a real reverse proxy in front that **overwrites** the header (nginx: `proxy_set_header X-Forwarded-For $remote_addr;`). Set `DCIM_TRUSTED_PROXIES=<that proxy's IP>`, and keep `--no-proxy-headers`. If you'd rather let uvicorn do it, use `--forwarded-allow-ips=<exactly that proxy IP>`, never `*`.

## First admin
No default credentials exist. Create the first admin like this:
```bash
.venv/bin/python -m app.scripts.create_admin --email you@example.com      # prompts for the password
echo 'long-passphrase-here' | .venv/bin/python -m app.scripts.create_admin --email you@example.com --password-stdin
```
The password policy is 12–128 characters, not a common password, and must not contain the email's local part. Admins create everyone else with `POST /users`, which returns a temporary password the user must change.

## Demo data (DEV ONLY)
```bash
.venv/bin/alembic upgrade head
.venv/bin/python scripts/seed_demo.py             # idempotent: creates only what is missing
.venv/bin/python scripts/seed_demo.py --reseed    # (= --wipe) delete the demo data, then seed again
.venv/bin/python scripts/seed_demo.py --no-users  # skip the demo logins
```
Upgrading an existing demo DB (any older seed, including one from before profiles existed):
```bash
cd apps/api
DCIM_DATABASE_URL=sqlite:///./dcim.db .venv/bin/alembic upgrade head          # schema + p1_17 link/flag step
DCIM_DATABASE_URL=sqlite:///./dcim.db .venv/bin/python scripts/seed_demo.py   # completes + publishes profiles, links devices
# or, to start the demo data over:
DCIM_DATABASE_URL=sqlite:///./dcim.db .venv/bin/python scripts/seed_demo.py --reseed
```
`p1_18_device_profile_required` (devices.profile_id NOT NULL) refuses, listing ids, while any device has no profile; it deletes nothing. On a demo DB this can't happen after p1_17 (all demo devices are typed). If it does, stop at the previous revision (`alembic upgrade p1_19_removal_hardening`), run the seed, and dry-run the removal script; real removals stay gated.
(Use your own `DCIM_DATABASE_URL`, e.g. `postgresql+psycopg://user:pass@host/db`.) The plain re-run never deletes anything: it fills missing template fields on the draft demo profiles, uploads a generated front image clearly labeled **DEMO** for each through the normal image path (`save_image`), publishes all 13, links every demo device to its type's Standard profile and clears its `profile_not_published` flag. Published profiles are never edited.

The script writes to the database in `DCIM_DATABASE_URL`. When `DCIM_ENV=prod` it refuses `--wipe/--reseed` unless you pass `--force`, and it never creates the demo logins.

It seeds the site **Demo DC** with the hall **Demo Hall**: 30 rows × 14 cabinets of 53U each (the standard cabinet), named `R01-C01` … `R30-C14`. Re-running the seed without `--reseed` grows demo cabinets left at 42U by an older seed to 53U, as long as every device still fits. It also adds 13 device types, each with a published default "Standard" profile (asset type, dimensions, 19-inch mounting, AC power (the MX304 is DC), weight, ports and a DEMO front image): 1U and 2U servers, 1U, 2U and 4U switches and routers, a patch panel, a 1U PDU and a storage shelf. Finally it adds 52 devices. Some are racked in R01-C01, R02-C01, R03-C05, R04-C07 and R10-C14, with `install`/`active` status. Others are unplaced: `decom` devices (always unracked) and `install` spares. Connections are seeded too, so the Connections report has data:
- server NICs to leaves (RJ45 and LC)
- leaf pairs (DAC)
- cross-cabinet leaf uplinks to the R04-C07 spines (LC)
- links that derive to Install and to Decom

Cables are labelled `DEMO-0001` and up. Re-running the seed is idempotent, and `--reseed` removes and re-creates the demo connections.

Floor layout: two banks of rows with a center aisle between them. The hall has `aisle_axis=y` and `odd_side=low`.
- Odd rows (R01, R03, … R29) are in the left bank at grid x 0–13, with fronts facing **E** toward the aisle.
- Even rows (R02 … R30) are in the right bank at x 17–30, with fronts facing **W**.
- Grid columns 14–16 are the aisle.
- Rows 2k−1 and 2k form facing pair k. Both rows of a pair share `pos_y = 2(k−1)`, so they face each other across the aisle, with one empty grid row between pairs.
- Cabinets step along x. `C01` is next to the aisle in both banks.
- No two cabinets share an (x, y) cell. Each row's `pos_x` is its bank's first column.

Demo logins (**DEV ONLY**, fixed passwords, never created in prod):

| Email | Role | Password |
|---|---|---|
| admin@demo.local | admin | `dcim-demo-Alpha-2026` |
| tech@demo.local | technician | `dcim-demo-Bravo-2026` |
| readonly@demo.local | read-only | `dcim-demo-Charlie-2026` |

## Auth (summary; details in docs/API.md)
- `POST /auth/login` `{email, password}` sets an HttpOnly `dcim_session` cookie (`__Host-dcim_session` when Secure) and returns `csrf_token`. Other endpoints: `POST /auth/logout`, `GET /auth/me`, and `POST /auth/change-password`, which rotates the session.
- Every POST, PATCH and DELETE needs `X-CSRF-Token: <csrf_token>` and a trusted `Origin` (`DCIM_TRUSTED_ORIGINS`).
- Roles: **admin** can do everything, including users, the audit log and deletes. **technician** can create and edit devices, create device types, import CSV, and move cabinets on the floor plan (pos/orientation only). **read-only** can only GET.

## Configuration (`DCIM_` environment variables, or `apps/api/.env`)
| Variable | Default | Meaning |
|---|---|---|
| `DCIM_ENV` | `dev` | `prod` forces Secure cookies, requires a strong secret, turns docs off, and blocks the demo logins |
| `DCIM_DATABASE_URL` | `sqlite:///./dcim.db` | SQLAlchemy URL (`postgresql+psycopg://…` for Postgres) |
| `DCIM_SECRET_KEY` | dev value | 32+ random bytes, required in prod |
| `DCIM_BIND_HOST` | `127.0.0.1` | Address `python -m app` listens on |
| `DCIM_PORT` | `8000` | Port `python -m app` listens on |
| `DCIM_TRUSTED_PROXIES` | (empty) | Comma list of proxy IPs/CIDRs whose `X-Forwarded-For` is believed; empty means ignore the header |
| `DCIM_DOCS_ENABLED` | on when `DCIM_ENV=dev`, off in prod | Force `/docs`, `/redoc` and `/openapi.json` on or off. A dev server reachable from the LAN serves docs unless you set this to `false` |
| `DCIM_COOKIE_SECURE` | `false` (prod: true) | Secure session cookie |
| `DCIM_CORS_ORIGINS` | empty | Comma-separated cross-origin callers |
| `DCIM_TRUSTED_ORIGINS` | Vite dev URLs | Origins accepted by the CSRF/login Origin check |
| `DCIM_TRUSTED_HOSTS` | localhost | Allowed `Host` headers |
| `DCIM_HSTS_ENABLED` | `false` | Send HSTS (only on HTTPS requests; behind a proxy, run uvicorn with `--proxy-headers` so the scheme is seen) |
| `DCIM_HSTS_MAX_AGE` | `86400` | HSTS max-age in seconds (short default for LAN; raise once HTTPS is settled) |
| `DCIM_HSTS_INCLUDE_SUBDOMAINS` | `false` | Add `includeSubDomains` |
| `DCIM_PERMISSIONS_CAMERA_SELF` | `false` | `Permissions-Policy: camera=(self)` for scanning; default `camera=()` |
| `DCIM_TRUST_REQUEST_ID` | `false` | Accept a proxy's `X-Request-ID` (`[A-Za-z0-9-]{1,64}`) |
| `DCIM_AUTH_LOCAL_ENABLED` | `true` | `true`, `false` or `admin_only` |
| `DCIM_PASSWORD_MIN_LENGTH` | `12` | Minimum password length |
| `DCIM_LOGIN_MAX_FAILURES` / `DCIM_LOGIN_LOCKOUT_MINUTES` | `10` / `15` | Per-account lockout |
| `DCIM_LOGIN_RATE_PER_IP` / `_FAILURES_PER_IP_EMAIL` / `_RATE_GLOBAL` / `_RATE_WINDOW_SECONDS` | `10` / `5` / `300` / `60` | Login rate limits (0 = off) |
| `DCIM_SESSION_IDLE_MINUTES` / `DCIM_SESSION_ABSOLUTE_HOURS` | `480` / `168` | Session expiry |
| `DCIM_HARD_DELETE_ENABLED` | `false` | `DELETE /devices/{id}?hard=true` (off until approved) |
| `DCIM_AUDIT_RETENTION_MONTHS` | `13` | Audit archive cutoff for standard rows (0 = keep forever) |
| `DCIM_RESTORABLE_RETENTION_MONTHS` | `24` | Cutoff for `restorable` rows (deletion snapshots); values below 24 are raised to 24; 0 = keep forever |
| `DCIM_IMAGE_DECODE_CONCURRENCY` | `4` | Concurrent image decodes per process (F-2) |
| `DCIM_IMAGE_DECODE_WAIT_SECONDS` | `10` | Wait for a decode slot, then 503 `image_busy` |
| `DCIM_EXPORT_DIR` | unset | Removal-script export directory (0700, outside repo/web roots); unset = `--export` refused |
| `DCIM_CSV_MAX_BYTES` / `_MAX_ROWS` / `_MAX_FIELD_CHARS` | 5 MB / 10000 / 10000 | CSV import limits |
| `DCIM_TEST_DATABASE_URL` | unset | Tests only: run the suite on Postgres |

## Test
```bash
.venv/bin/python -m pytest -q
```
Each test uses its own temporary SQLite file. One test also runs every migration up and down.

## OpenAPI
```bash
.venv/bin/python scripts/export_openapi.py     # writes openapi.json
```

## Layout
`app/modules/<feature>/` holds `models.py` (tables), `schemas.py` (request/response), `service.py` (helpers/rules), and `router.py`. The features are `locations` (sites/halls/rows/racks, where a rack is a cabinet), `device_types` (+ profiles), `devices`, `history`, `audit`, `auth` and `users`. All tables are registered in `app/models.py`.

## Dependencies, CI, Postgres

- Pinned with hashes: edit `requirements.in` / `requirements-dev.in`, then
  `pip-compile --generate-hashes --strip-extras requirements.in` (dev: add `--allow-unsafe`).
  Install with `pip install --require-hashes -r requirements.txt -r requirements-dev.txt` (the dev file only *constrains* to the runtime pins, it doesn't include them); `pip-audit -r requirements.txt` runs in CI.
- CI (`.github/workflows/api.yml`) runs migrations up/down/up + `alembic check` and the full test suite on
  SQLite **and** `postgres:16`. Locally: `DCIM_TEST_DATABASE_URL=postgresql+psycopg://user:pw@host/db pytest`
  (the test DB's `public` schema is dropped and recreated per test).
- Audit retention: `python -m app.scripts.audit_archive --out archive.jsonl [--purge]` archives events older than
  `DCIM_AUDIT_RETENTION_MONTHS` (default 13; 0 = keep forever) and, with `--purge`, deletes them and records `audit.purge`.
  Deletion snapshots (`retention_class='restorable'`) are excluded from that cutoff and kept at least 24 months
  (`DCIM_RESTORABLE_RETENTION_MONTHS`, minimum 24, 0 = forever).
- Only the first 429 per IP per window writes an `auth.rate_limited` audit row (N-2). Limiter memory is bounded: empty keys are dropped and at most 50,000 keys are kept (N-3). Because the limits live in the API process, **run exactly one API worker** (no `--workers N`).
- Logins refused because `DCIM_AUTH_LOCAL_ENABLED=admin_only` are audited as `auth.login_failed` with `reason=local_disabled` (R-12).
- Every response, including a TrustedHost 400, carries the security headers (R-8). Log records never contain a validation error's submitted values: a log filter redacts `input_value=` (N-4).
- Login rate limiting is in-process (one API worker). Behind a reverse proxy, set `DCIM_TRUSTED_PROXIES` (see
  "Client IP and proxies"), so limits apply to the real client IP.

## Rack-unit slots (`device_ru_slots`, p1_23)
Overlaps are also blocked in the DB: `device_ru_slots` (PK `rack_id, u, side`) is rewritten by an ORM flush hook
(`app/modules/devices/slots.py`) whenever a device's rack/U/face/profile changes. **Write placements through the
ORM only**: Core/bulk `UPDATE devices SET rack_id/position_u/face/profile_id` (or raw SQL) skips the hook and
leaves stale slots (a guard test fails on such code in `app/` and `scripts/`). Rack height is **not** a DB check;
it stays in the Python fit check. A slot or floor-cell clash at commit is a 409 with `code`
`ru_slot_taken` / `floor_position_taken`.

## Removing / restoring profile-less devices (items 47/48, OPERATOR ONLY, NOT YET CLEARED)
> **Not cleared for real data yet.** We're waiting for DCIM Security guidance on who may run these scripts and on access to the snapshots and exports. Until then, `--execute` refuses to run unless `DCIM_ALLOW_PROFILELESS_REMOVAL=1` is set. There is no API endpoint. Nothing runs them automatically (not migrations, app startup or CI).
```bash
.venv/bin/python scripts/remove_profileless_devices.py            # dry run: every device with profile_id NULL (placed, unplaced, soft-deleted) + set hash
DCIM_ALLOW_PROFILELESS_REMOVAL=1 .venv/bin/python scripts/remove_profileless_devices.py --execute \
    --actor you@example.com --expect-hash <hash> [--include-connections] [--export removed-YYYYMMDD.json] \
    [--backup-confirmed]   # prod only
.venv/bin/python scripts/restore_from_audit.py --change-set <id> --actor you@example.com --profile-id <published id>   # dry run
DCIM_ALLOW_PROFILELESS_REMOVAL=1 .venv/bin/python scripts/restore_from_audit.py --change-set <id> --actor you@example.com \
    --profile-id <id> [--map type_id:profile_id,...] --execute
```
Removal runs in one transaction:
1. Re-select the devices (FOR UPDATE on PG) and check the hash.
2. Refuse (exit 2) if ports or connections exist and `--include-connections` isn't given.
3. Write a change_set and one `hard_delete` audit snapshot per device (`via='script'`, `retention_class='restorable'`, actor_user_id set).
4. Write the optional export (0600, JSON plus a flat CSV) before commit, and record its path and SHA-256 on the change set and the run's audit event. A failure rolls everything back.

Exports: `--export` takes a plain file name, written in `DCIM_EXPORT_DIR` (no default: unset means `--export` is refused). The directory is created 0700 and must stay 0700 and owned by you. It is refused inside the repository (including `apps/web`), any `dist/` or `www` path, `/var/www`, `/srv/www`, `/usr/share/nginx` or `DCIM_STATIC_ROOT`. CSV cells starting with `= + - @`, tab or CR are prefixed with `'` so spreadsheets don't run them. The repo `.gitignore` also ignores `exports/` and `*removed*.json/csv`.
5. Delete for real, in FK order.

Both scripts:
- `--actor` must be an **active admin** and re-enter their password (prompted; the normal login check, so failures are audited and count toward lockout). A refused actor exits **3**.
- Typed confirmations: `remove N` (and `delete connections` when `--include-connections` touches connected devices); restore asks for `restore N from change_set ID`. `--yes` skips them only outside `DCIM_ENV=prod`.
- In prod, removal refuses (exit 3) unless the file named by `DCIM_BACKUP_MARKER` (touched by your backup job) is under 1 hour old, or you pass `--backup-confirmed`.

Restore brings devices back **unplaced** on a published profile, with the same ids when free (an existing id is never overwritten). History, ports and connections whose other end exists come back too, and the old location goes in `notes`. Each restored device is recorded in `restored_devices`, so restoring the same change set again restores nothing and is refused. Hostname conflicts (case-insensitive, in the old rack or unplaced), serial conflicts or a missing mapping are refused with a list, and nothing is written.
