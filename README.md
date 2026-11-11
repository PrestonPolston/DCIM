# DCIM

Local data-center inventory app: a FastAPI API and a Vite/React web app. Cabinet profiles are included. A fresh clone has an empty database and no user accounts.

## Versions

- **Python 3.13.** `apps/api/requirements.txt` is compiled with 3.13, and CI installs 3.13. Use a 3.13 `python` for the venv below.
- **Node.js `^20.19.0` or `>=22.12.0`.** That is the range required by Vite 8.3 (the locked version in `apps/web/package-lock.json`). npm 10 is enough to run `npm ci`.

## API

From the repo root. Each block is a subshell, so you can paste them in order in the same terminal without `cd` changing your directory. Install and migrate first, then create the admin, then start the API. The server command stays in the foreground, so create the admin before you start it (the CLI does not need the API to be running).

```bash
(
cd apps/api
python3.13 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.txt -r requirements-dev.txt
.venv/bin/alembic upgrade head
)
```

`alembic upgrade head` creates or updates the local SQLite file `apps/api/dcim.db` (`DCIM_DATABASE_URL` defaults to `sqlite:///./dcim.db`). Migrations do not insert users.

### First admin

No admin account is shipped. After you run the migrations, the database still has no users. Create one with the CLI before you start the API. It prompts for a password and does not accept a built-in password:

```bash
(cd apps/api && .venv/bin/python -m app.scripts.create_admin --email you@example.com)
```

To supply the password on stdin instead of a prompt:

```bash
(cd apps/api && .venv/bin/python -m app.scripts.create_admin --email you@example.com --password-stdin)
```

The password must be 12–128 characters, must not be a common password, and must not contain the email's local part. Further accounts are created in the app after you sign in.

Users created in the app (`POST /users`) receive a temporary password (`temporary_password` in the 201 response; omit it on the request to have one generated, or supply your own) and `must_change_password=true`. After they sign in, every endpoint except `GET /auth/me`, `POST /auth/logout` and `POST /auth/change-password` returns 403 with `detail.code` `password_change_required` until they change the password. A successful change rotates the session cookie and the CSRF token and signs out their other sessions. An admin password reset (`POST /users/{id}/reset-password`) issues a new temporary password and applies the same requirement. The admin created with `create_admin` is not required to change their password.

`scripts/seed_demo.py` is a separate, dev-only command documented in `apps/api/README.md`. The steps above do not run it, so its demo logins are not created.

### Start the API

```bash
(cd apps/api && .venv/bin/python -m app --reload)
```

The server listens on `http://127.0.0.1:8000`. Change the address with `DCIM_BIND_HOST` and `DCIM_PORT`. `python -m app` starts uvicorn with proxy headers off.

The dev fallback for `DCIM_SECRET_KEY` is rejected when `DCIM_ENV=prod`. Leave the default only for this local dev server, or set your own secret in the environment or in `apps/api/.env` (that file is gitignored).

## Web

Open a second terminal. From the repo root:

```bash
(
cd apps/web
npm ci
npm run dev
)
```

Vite serves `http://localhost:5173`. Open that URL, not `http://127.0.0.1:5173`, unless you intend to. The Origin check (and CORS, if you set `DCIM_CORS_ORIGINS`) compares the browser's `Origin` as an exact string, so `http://localhost:5173` and `http://127.0.0.1:5173` are different origins.

The dev server is configured with `strictPort: true` (and the same for `vite preview`), so it exits if the address it binds is already in use instead of silently moving to another port. By default that bind is `localhost`, which may be `::1` only. A process that occupies only IPv4 (for example `0.0.0.0:5173`) can leave `[::1]:5173` free, in which case Vite still starts on IPv6 and `http://localhost:5173` and `http://127.0.0.1:5173` can reach different servers.

The app calls `/api` (`VITE_API_URL` in `apps/web/.env.example`, default `/api`). The dev server proxies `/api` to `http://localhost:8000` and strips the `/api` prefix. `apps/web/vite.config.ts` reads `API_PROXY_TARGET` for that proxy target (default `http://localhost:8000`). The Vite proxy uses `changeOrigin: true`, so the API sees a `Host` header for the proxy target (for example `localhost:8000`) and cannot treat the browser's `Origin` as same-origin.

The API's CSRF/login Origin check defaults to allowing `http://localhost:5173` and `http://127.0.0.1:5173`. Set this with `DCIM_TRUSTED_ORIGINS` (a comma-separated list of full origins: scheme, host, and port). A value **replaces** the default list; it does not add to it. Origins listed in `DCIM_CORS_ORIGINS` are also accepted by that check. Include both `localhost` and `127.0.0.1` for every port you will use. If you run the web dev server or the API on other ports, start both with matching settings, for example API on 8100 and Vite on 5273:

```bash
(cd apps/api && DCIM_PORT=8100 DCIM_TRUSTED_ORIGINS=http://localhost:5273,http://127.0.0.1:5273 .venv/bin/python -m app --reload)
```

In the second terminal:

```bash
(cd apps/web && API_PROXY_TARGET=http://localhost:8100 npm run dev -- --port 5273)
```

To keep the defaults as well as an extra port, list every origin, including both host spellings, for example `DCIM_TRUSTED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://localhost:5273,http://127.0.0.1:5273`.

Otherwise sign-in fails with 403 `Origin not allowed`. Do not disable or loosen the Origin check. Keep the dev server on localhost so the API sees a local client.

Sign in with the email and password you passed to `create_admin`.

## Checks

From the repo root:

```bash
(cd apps/api && .venv/bin/python -m pytest -q)
(cd apps/api && .venv/bin/alembic check)
(cd apps/web && npm test && npm run lint && npm run typecheck && npm run build)
```

API tests use a temporary SQLite file per test. They do not read `dcim.db`.

## What stays off the repo

`.gitignore` ignores virtualenvs, `node_modules`, build output, `.env` files (`.env.example` stays), SQLite databases, and `sessions/`. Do not commit a database, a session, or a password.
