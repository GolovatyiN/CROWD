# Crowd — crowd-linkbuilding control panel

Manage donors, anchor plans, employee task queues and the stop list in one place,
instead of fighting spreadsheets.

## Features

- JWT login + roles (`admin`, `employee`)
- Donor base with CSV/XLSX import, sortable + paginated table, bulk actions
- Donor accounts with `max_placements` cap (auto-rotated when full)
- Anchor plans with **auto-match** and **manual donor picker**
- **Stop list** auto-populated when a placement is marked placed; enforces
  `UNIQUE(target_url, donor_url)`
- "My tasks" card view with copy-to-clipboard credentials
- Dashboard with stats cards, sparkline of last 14 days, recent activity and
  problems feeds, per-employee progress bars
- Cmd/Ctrl+K command palette
- Mobile-friendly sidebar with hamburger
- Russian UI

## Stack

| Layer    | Choice                                                  |
|----------|---------------------------------------------------------|
| Backend  | Python 3.12 • FastAPI • SQLAlchemy 2.x • Alembic        |
| DB       | SQLite for local dev, Postgres for prod (Neon)          |
| Auth     | JWT + bcrypt                                            |
| Files    | pandas + openpyxl (XLSX), built-in csv                  |
| Frontend | Vanilla JS modules + SPA shell, served by FastAPI       |
| Deploy   | Docker, Railway / Render                                |

## Project layout

```
CROWD/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app + static frontend mount
│   │   ├── config.py
│   │   ├── database.py        # engine, URL normalisation
│   │   ├── auth.py
│   │   ├── models/__init__.py
│   │   ├── schemas/__init__.py
│   │   ├── routes/            # auth, users, donors, anchor_plans, …
│   │   ├── services/          # matcher.py, importer.py, stop_list_service.py
│   │   └── seed.py
│   ├── alembic/               # migrations
│   ├── alembic.ini
│   ├── requirements.txt
│   └── .env.example
├── frontend/                  # vanilla JS, no build step
│   ├── index.html
│   ├── css/styles.css
│   └── js/{api,app,components,pages}
├── Dockerfile
├── railway.toml
├── render.yaml
└── README.md
```

## Local development

```bash
cd /Users/nikita/Desktop/CROWD

# 1. Python 3.11+ virtual env
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

# 2. Copy env (defaults are fine for SQLite)
cp backend/.env.example backend/.env

# 3. Run migrations + seed demo data + admin
cd backend
alembic upgrade head
python -m app.seed

# 4. Run
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000.

**Default credentials** (created by `python -m app.seed`):

- **Admin:** `admin@crowd.local` / `admin123`
- **Employees** (password `employee123`): `nastya@crowd.local`, `andrey@crowd.local`, `artem@crowd.local`

## Production deployment

### Step 1 — Neon Postgres (free tier)

1. Sign up at https://neon.tech (GitHub login is fine).
2. Create a new project, region close to your hosting.
3. From the dashboard copy the **Connection string** — it looks like:
   ```
   postgresql://user:pass@ep-xyz.aws.neon.tech/neondb?sslmode=require
   ```
4. Keep it handy — we need it for Railway.

> The app normalises `postgres://` and `postgresql://` URLs to the
> `postgresql+psycopg2://` driver form automatically — paste the Neon URL as-is.

### Step 2 — Railway (recommended)

1. Sign up at https://railway.app with GitHub.
2. Click **New Project → Deploy from GitHub** and pick the `crowd` repo.
3. Railway will detect the `Dockerfile`. On the deploy settings:
   - **Environment Variables** — add:
     - `DATABASE_URL` = Neon connection string from Step 1
     - `SECRET_KEY` = a long random string (e.g. `python -c 'import secrets; print(secrets.token_urlsafe(48))'`)
     - `ADMIN_EMAIL` = your real admin email
     - `ADMIN_PASSWORD` = strong password (used only on first run to create admin)
     - `SEED_DEMO` = `0`  (production — skip demo employees and sample donors)
     - *(optional)* `ACCESS_TOKEN_EXPIRE_MINUTES` = `1440`
4. Click **Deploy**. First build takes ~3 min (mostly pandas + psycopg2).
5. When green, open the public URL Railway gives you. Login as admin.

### Step 3 — Render alternative

If you prefer Render (`render.yaml` is provided):

1. https://render.com → **New → Blueprint** → connect your GitHub.
2. Pick the repo. Render reads `render.yaml`, prompts for `DATABASE_URL` and
   `ADMIN_PASSWORD`.
3. Free tier sleeps after 15 min idle — pick Starter ($7/mo) for daily use.

### Step 4 — Logging in for the first time

The deploy command runs:
```
alembic upgrade head && python -m app.seed && uvicorn ...
```

`python -m app.seed` is idempotent and respects `SEED_DEMO=0` — it only creates
your admin user. On any subsequent restart it's a no-op.

## Switching DB locally to Postgres

Set `DATABASE_URL` in `backend/.env`:
```
DATABASE_URL=postgresql://user:pass@localhost:5432/crowd
```
The app auto-normalises to `postgresql+psycopg2://`.

## Useful commands

| What                                | Command                                          |
|-------------------------------------|--------------------------------------------------|
| Apply pending migrations            | `alembic upgrade head`                           |
| New migration from model changes    | `alembic revision --autogenerate -m "your msg"`  |
| Roll back one revision              | `alembic downgrade -1`                           |
| Re-seed (idempotent)                | `python -m app.seed`                             |
| Seed admin only                     | `SEED_DEMO=0 python -m app.seed`                 |
| Run dev server                      | `uvicorn app.main:app --reload --port 8000`      |

## API

After running, OpenAPI docs are at:
- http://localhost:8000/docs (Swagger UI)
- http://localhost:8000/redoc

## Business rules

- `donors.donor_url` is **unique**.
- `stop_list_entries (target_url, donor_url)` is **unique** — one specific URL
  of yours cannot be placed twice on the same donor.
- The matcher excludes any donor where `(target_url, donor_url)` already exists
  in the stop list or in a successful placement.
- The matcher suggests the **least-used active account** on the picked donor
  that still has capacity (`max_placements`).
- On `mark-placed`:
  - `result_url` is required.
  - Donor account is upserted by `(donor_id, account_username)`.
  - Stop-list entry is created if missing.
  - Anchor plan item status → `placed`.

## Roadmap

- Encryption-at-rest for `login_password` (Fernet with master key from env)
- Audit log for donor edits
- Webhooks / Telegram notifications on placements
