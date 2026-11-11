# DCIM

Local data-center inventory app: a FastAPI API and a Vite/React web app. Cabinet profiles are included. A fresh clone has an empty database and no user accounts.

## Versions

- **Python 3.13.** `apps/api/requirements.txt` is compiled with 3.13, and CI installs 3.13. Use a 3.13 `python` for the venv below.
- **Node.js `^20.19.0` or `>=22.12.0`.** That is the range required by Vite 8.3 (the locked version in `apps/web/package-lock.json`). npm 10 is enough to run `npm ci`.

## API

From `apps/api`:

```bash
cd apps/api
python3.13 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.txt -r requirements-dev.txt
.venv/bin/alembic upgrade head
.venv/bin/python -m app --reload
```

`alembic upgrade head` creates or updates the local SQLite file `apps/api/dcim.db` (`DCIM_DATABASE_URL` defaults to `sqlite:///./dcim.db`). Migrations do not insert users.

The server listens on `http://127.0.0.1:8000`. Change the address with `DCIM_BIND_HOST` and `DCIM_PORT`. `python -m app` starts uvicorn with proxy headers off.

The dev fallback for `DCIM_SECRET_KEY` is rejected when `DCIM_ENV=prod`. Leave the default only for this local dev server, or set your own secret in the environment or in `apps/api/.env` (that file is gitignored).

### First admin

No admin account is shipped. Clone, migrate, and start the API, and the database still has no users. Create one with the CLI. It prompts for a password and does not accept a built-in password:

```bash
cd apps/api
.venv/bin/python -m app.scripts.create_admin --email you@example.com
```

To supply the password on stdin instead of a prompt:

```bash
.venv/bin/python -m app.scripts.create_admin --email you@example.com --password-stdin
```

The password must be 12–128 characters, must not be a common password, and must not contain the email's local part. Further accounts are created in the app after you sign in.

`scripts/seed_demo.py` is a separate, dev-only command documented in `apps/api/README.md`. The steps above do not run it, so its demo logins are not created.

## Web

In a second terminal, from `apps/web`:

```bash
cd apps/web
npm ci
npm run dev
```

Vite serves `http://localhost:5173`. The dev server is configured with `strictPort: true` (and the same for `vite preview`), so it exits if that port is already in use instead of silently moving to another port.

The app calls `/api` (`VITE_API_URL` in `apps/web/.env.example`, default `/api`). The dev server proxies `/api` to `http://localhost:8000` and strips the `/api` prefix. Override the target with `API_PROXY_TARGET` if the API is not on port 8000.

The API's CSRF/login Origin check defaults to allowing `http://localhost:5173` and `http://127.0.0.1:5173`. Set this with `DCIM_TRUSTED_ORIGINS` (a comma-separated list of full origins: scheme, host, and port). A value **replaces** the default list; it does not add to it. The Vite proxy uses `changeOrigin: true`, so the API sees a `Host` header for the proxy target (for example `localhost:8000`) and cannot treat the browser's `Origin` as same-origin. If you run the web dev server on another port, start the API with that origin included, for example:

```bash
DCIM_TRUSTED_ORIGINS=http://localhost:5273,http://127.0.0.1:5273
```

Or keep the defaults and add the extra origin:

```bash
DCIM_TRUSTED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://localhost:5273
```

Otherwise sign-in fails with 403 `Origin not allowed`. Do not disable or loosen the Origin check. Keep the dev server on localhost so the API sees a local client.

Sign in with the email and password you passed to `create_admin`.

## Checks

```bash
cd apps/api && .venv/bin/python -m pytest -q
cd apps/web && npm test && npm run build
```

API tests use a temporary SQLite file per test. They do not read `dcim.db`.

## What stays off the repo

`.gitignore` ignores virtualenvs, `node_modules`, build output, `.env` files (`.env.example` stays), SQLite databases, and `sessions/`. Do not commit a database, a session, or a password.
