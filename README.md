# OpsDesk

OpsDesk is a free, AI-assisted travel operations platform starter for TBO Voyagehack 4.0. The repository contains a React + Vite + Tailwind frontend and a Python + FastAPI + SQLAlchemy backend. It includes ticket management, deterministic routing, suggested case linking, and local password/token authentication with role and agency access controls. No external AI or authentication services are used.

## Requirements

- Node.js 20+ and npm
- Python 3.11+

## Run locally

In one terminal:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.serve
```

The API is at `http://localhost:8000`; interactive API docs are at `/docs`. The health check is `GET http://localhost:8000/api/health`.

## Ticket management

- `GET /api/tickets` lists tickets and accepts `status`, `priority`, `q`, `limit`, and `offset` filters.
- `GET /api/tickets?risk=at_risk` or `?risk=breached` filters tickets by calculated SLA status.
- `POST /api/tickets` creates a ticket for the signed-in user's agency; optional timezone-aware `check_in_at` and `departure_at` values capture travel deadlines.
- `GET /api/tickets/{id}` retrieves a ticket.
- `PATCH /api/tickets/{id}` updates its subject, description, status, or priority.
- `DELETE /api/tickets/{id}` deletes a ticket.
- `GET /api/tickets/{id}/related` suggests same-agency matches, prioritizing exact labeled booking references and then TF-IDF/cosine content similarity.
- `POST /api/tickets/{id}/links` records an agent-confirmed related-case link.
- `GET /api/tickets/{id}/assignment` returns the active assignment.
- `POST /api/tickets/{id}/assign` scores and assigns the ticket on an explicit admin or escalation manager request.
- `GET /api/tickets/{id}/sla` returns response/resolution deadlines, remaining time, travel context, and escalation history.
- `GET /api/insights` returns agency-scoped ticket metrics, resolution and SLA statistics, volume breakdowns, and recurring complaint themes. Optional filters are `date_from`, `date_to`, `agency_id`, and `priority`.
- `GET /api/users/{id}/routing-profile` reads an agent's regional expertise and availability.
- `PUT /api/users/{id}/routing-profile` updates that profile; an active same-agency admin or escalation manager must request it.
- `GET /api/agencies` and `GET /api/users` provide same-agency directory data to signed-in users.

## Authentication and access

- `POST /api/auth/login` accepts an email and password and returns a short-lived bearer access token.
- `GET /api/auth/me` returns the current account; `POST /api/auth/logout` revokes the current token.
- Every ticket, routing, directory, and case-linking endpoint requires `Authorization: Bearer <token>`. Data is scoped to the signed-in user's agency.
- Agents can update and link tickets assigned to them. Admins and escalation managers can update agency tickets and run routing. Only admins can delete tickets. Admins and escalation managers can manage routing profiles.
- Passwords are hashed with Argon2id. Login attempts are rate-limited to five attempts per normalized email/client-IP pair and 100 attempts per client IP in a 15-minute window; repeated attempts return HTTP 429 with a retry interval. Rate-limit keys are stored as hashes in SQLite.
- Local development generates a temporary JWT secret automatically. For production, set `APP_ENV=production` and provide a stable `JWT_SECRET_KEY` containing exactly 64 lowercase hexadecimal characters (32 bytes). Generate one with `python -c "import secrets; print(secrets.token_hex(32))"`; store it in your deployment secret manager and never commit it. All workers must use the same key, retained across restarts. Startup rejects wrong formats, known placeholders, and simple repeated patterns. This validation cannot prove the randomness or provenance of an arbitrary correctly formatted value; use the cryptographic generator or a trusted secret manager.
- Existing accounts created without a password need one set from a trusted backend terminal: `python -m app.db.set_password user@example.com`. The command prompts for a password of at least 12 characters.

## Demo workspace data

For a local SQLite development database, run this repeatable demo seed command from `backend/` after installing dependencies:

```powershell
python -m app.db.seed_demo
```

It adds three agencies and 25 realistic travel-operation tickets with booking references, related complaints, conversations, resolution/activity records, assignments, and on-track, approaching, travel-urgent, and breached SLA examples. It is safe to rerun: it recognizes seeded records, does not replace existing non-empty password hashes or user-entered profile/ticket fields, and refuses conflicting demo ticket references. It only supports SQLite and local development. Seeding is rejected when `APP_ENV=production` (or `prod`).

Before creating or initializing demo accounts, the seed command requires an explicit password of at least 12 characters. When `OPSDESK_DEMO_PASSWORD` is unset, it prompts twice using hidden terminal input. For non-interactive local development, set `OPSDESK_DEMO_PASSWORD` in the process environment; do not put the value in source files, scripts, command history, or production configuration. The password is used only for new demo accounts and existing demo accounts with no password hash. Existing configured passwords are preserved, and the seed command never prints the password.

To set a different private password for an individual account, use the interactive command from `backend/`; it prompts without placing the password in shell history:

```powershell
python -m app.db.set_password agent@opsdesk.local
python -m app.db.set_password manager@opsdesk.local
python -m app.db.set_password admin@opsdesk.local
```

Use the corresponding email from the table below for another agency, and choose unique passwords that you do not reuse elsewhere. The command updates the selected local account's Argon2 password hash. Do not publish these local passwords or reuse them in a deployed environment.

Primary demo account emails:

| Agency | Agent | Escalation manager | Admin |
| --- | --- | --- | --- |
| OpsDesk Demo Agency | `agent@opsdesk.local` | `manager@opsdesk.local` | `admin@opsdesk.local` |
| Meridian Travel Group | `agent1@meridian-demo.local` | `manager@meridian-demo.local` | `admin@meridian-demo.local` |
| Horizon Business Travel | `agent1@horizon-demo.local` | `manager@horizon-demo.local` | `admin@horizon-demo.local` |

Each agency also has a second agent account (`agent2@<agency-domain>`). Passwords are stored as Argon2 hashes. The seed preserves any already-configured password; if that password is unknown, reset it through the trusted local `python -m app.db.set_password <email>` prompt.

## Intelligent routing

Tickets may include a region. `AgentProfile` records each agent's supported regions and availability. Routing awards 40 points for an exact region match and 20 for a `Global` fallback; otherwise it awards no region points. It also considers ticket priority and role fit, availability, and the count of active assignments. Ties resolve by lower workload and then user ID. The API persists the selected score and explanation on the `Assignment` history row and returns a live ranked comparison of eligible candidates for the UI. Only active `agent` and `escalation_manager` profiles are candidates; the request actor must be an active agency admin or escalation manager. A request returns `409` when there is no eligible available agent. Routing is deterministic and does not use external AI services.

## Travel-aware SLAs

Response and resolution targets are local backend policy values keyed by priority. Defaults are low 24h/5d, normal 8h/2d, high 2h/12h, and urgent 30m/2h (response/resolution). When a check-in or departure time is supplied with a timezone, the earlier known travel event caps both deadlines. Ticket descriptions are not parsed for dates. Without structured travel data, the API marks travel context `missing` and still evaluates the priority SLA; missing travel data is not itself a breach.

Tickets are marked approaching inside the configured approach window (default 60 minutes), travel urgent inside the known travel window (default 3 hours), breached when a response or resolution deadline passes, and met when both clocks are completed in time. A background evaluator runs every 60 seconds. By default, the first approaching/travel-urgent and breached event each records an escalation and reassigns the ticket to an available same-agency escalation manager with the lowest active workload; if none is available, the history records that outcome. This does not change ticket priority. Configure `SLA_TARGETS_JSON`, `SLA_APPROACHING_MINUTES`, `SLA_TRAVEL_URGENT_MINUTES`, `SLA_ESCALATION_ENABLED`, and `SLA_POLL_SECONDS` in the backend environment. `SLA_TARGETS_JSON` maps each priority to `response_minutes` and `resolution_minutes`.

## Feedback and insights

The Insights endpoint and dashboard calculate volume from ticket creation timestamps, resolution time from recorded `resolved_at` or status-change activity timestamps, and SLA breach rate from tickets with stored SLA evaluations. Missing samples produce a `null` metric and visible sample counts rather than a fabricated zero. Complaint themes are inferred locally by TF-IDF weighted cosine similarity over resolved ticket subjects, descriptions, and public conversation messages; internal conversations are excluded. Themes require at least three resolved text samples and at least two tickets per cluster. The response labels themes as inferred, provides example tickets and the similarity threshold, and reports insufficient data when the minimum sample is not met. Agency and operational-area frequency counts are measured from resolved tickets. All insight queries remain limited to the signed-in user's agency.

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Vite serves the UI at `http://localhost:5173`. It calls the backend health endpoint on load. Set `VITE_API_BASE_URL` in a frontend `.env` file to change the API base URL (default `http://localhost:8000/api`).

The frontend preview Content Security Policy is generated from the API origin available to Vite. Keep `VITE_API_BASE_URL` aligned between `npm run build` and `npm run preview`; preview checks the API origin recorded in the built HTML and exits with a clear error if they differ. For a static production host outside Vite preview, configure its CSP `connect-src` to include the same API origin.

## Database

SQLAlchemy models live in `backend/app/db/models/`. The backend creates the application tables automatically at startup in the local SQLite database `backend/opsdesk.db`, including stored SLA snapshots and escalation history. Set `DATABASE_URL` to override the default. SQLite foreign key enforcement is enabled for each SQLite connection.

The SQLite database is a plain file and is not encrypted by OpsDesk. Restrict read/write access to the backend service account and protect the containing volume with operating-system or full-disk encryption, especially when tickets may contain traveler or booking details. Treat database copies, exports, and backups as sensitive data: encrypt them, restrict access, store them separately from public web assets, and test restoration without exposing the backup. Do not commit database files or backups to source control.

For production, set `CORS_ORIGINS` to a comma-separated list of exact trusted frontend origins, including scheme and host (for example, `https://ops.example.com`). Do not use `*` or include untrusted preview domains. The API uses bearer authorization headers and does not rely on cross-site cookies. FastAPI adds content-type, framing, referrer, permissions, and API Content Security Policy headers; HSTS is sent on HTTPS requests. The Vite development server adds basic headers, and Vite preview adds a frontend Content Security Policy restricted to the configured API origin. Configure equivalent headers and HTTPS/HSTS at the actual production reverse proxy or static host.

The backend reads `TRUSTED_PROXY_IPS` as a comma-separated list of exact proxy addresses or narrow CIDR ranges; it is empty by default, so forwarding headers are ignored in local development. Never configure `*` or a catch-all network. Start the API with `python -m app.serve`, which disables Uvicorn's implicit proxy-header rewriting and leaves forwarding decisions to OpsDesk's allowlist middleware. If a reverse proxy is used, list only its source addresses and configure it to replace or correctly append `X-Forwarded-For`; do not pass through arbitrary client-supplied forwarding values. Restrict direct network access to the API so clients cannot impersonate a trusted proxy. If using a different ASGI launcher, configure it not to rewrite proxy headers before the OpsDesk middleware runs.

The frontend currently keeps bearer tokens in `sessionStorage`. This limits persistence to the browser tab session, but JavaScript can read the token; an XSS flaw or compromised script could steal it until it expires or is revoked. Keep dependencies updated, avoid injecting untrusted HTML, and deploy a restrictive Content Security Policy. This is a documented residual risk; authentication remains bearer-token based.

## Deploy to Render

This repository can be deployed as two independent Render services: a FastAPI Web Service and a React/Vite Static Site. The free configuration is suitable only for a disposable preview. Do not use it for persistent tickets, traveler information, production accounts, or other data that must survive a restart.

### FastAPI backend Web Service

Create a Render **Web Service** with these settings:

| Setting | Value |
| --- | --- |
| Root Directory | `backend` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python -m app.serve` |
| Health Check Path | `/api/health` |

Set these backend environment variables in Render's service settings:

| Variable | Value |
| --- | --- |
| `APP_ENV` | `production` |
| `HOST` | `0.0.0.0` |
| `JWT_SECRET_KEY` | Generate a stable secret using `python -c "import secrets; print(secrets.token_hex(32))"`; enter it as a secret in Render and do not commit it. |
| `CORS_ORIGINS` | The exact frontend origin, for example `https://opsdesk-ui.onrender.com` (no path or trailing slash). |
| `TRUSTED_PROXY_IPS` | Leave empty unless proxy source addresses are explicitly verified and forwarding headers are sanitized by that proxy. |

Render supplies `PORT`; `app.serve` reads it. The backend currently reads `CORS_ORIGINS`, not `CORS_ALLOWED_ORIGINS`. Keep the JWT secret stable across restarts. Never use a local development key or a value copied into source control.

### React/Vite frontend Static Site

Create a Render **Static Site** with these settings:

| Setting | Value |
| --- | --- |
| Root Directory | `frontend` |
| Build Command | `npm ci && npm run build` |
| Publish Directory | `dist` |
| `VITE_API_BASE_URL` build environment variable | The backend origin plus `/api`, for example `https://opsdesk-api.onrender.com/api`. |

`VITE_API_BASE_URL` is embedded into the frontend at build time. Rebuild the static site after changing it. The backend's `CORS_ORIGINS` must contain the deployed static site's exact HTTPS origin.

The Vite preview CSP is generated from the build-time API URL, and preview checks that its API origin matches the one used to build. Render serves the published static files directly, so configure the equivalent CSP in the static site's response-header settings. Its `connect-src` must allow `'self'` and the backend **origin** (without `/api`). For example, with `opsdesk-api.onrender.com` as the backend service name, set a `Content-Security-Policy` response header with this value:

```text
default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self' https://opsdesk-api.onrender.com
```

Replace the example backend origin with the actual API origin. Configure HTTPS and the other security headers at the host as well. If either service URL changes, update `CORS_ORIGINS`, `VITE_API_BASE_URL`, and CSP together, then rebuild the frontend.

### Render Free storage and demo-data warning

The backend creates database tables at startup, but startup does not create demo users or tickets. The demo seed command is local SQLite development tooling; do not enable automatic demo-user creation or run the seed against production data. A newly deployed backend therefore needs an explicitly safe, supported account-provisioning procedure before it can be used to log in.

The default database is a SQLite file on the backend service filesystem. Render Free Web Services have ephemeral filesystems: local changes, including SQLite records, can be lost on restart, redeploy, or spin-down. Free services cannot attach persistent disks. A free deployment is therefore disposable: expect accounts and tickets to disappear and do not enter real or sensitive data. Keep a local backup of any demo data you need to recreate. This project does not configure PostgreSQL or another persistent database.

See [Render's free instance limitations](https://render.com/docs/free) and [Web Service port requirements](https://render.com/docs/web-services) before deployment. The backend must bind to `0.0.0.0` and the Render-provided port; the frontend is a static build and has no runtime environment-variable substitution.

Expired token-revocation records and elapsed login-rate-limit windows are removed at startup and by periodic background cleanup. Active revocations are retained until their token expiry.

Run the backend tests from `backend/`:

```powershell
python -m pytest
```

## Structure

```text
OpsDesk/
├── backend/
│   ├── app/
│   │   ├── api/routes/health.py
│   │   ├── core/config.py
│   │   ├── db/models/
│   │   ├── db/init.py
│   │   ├── db/session.py
│   │   └── main.py
│   ├── tests/
│   └── requirements.txt
└── frontend/
    ├── src/
    └── package.json
```
