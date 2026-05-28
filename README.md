# Crowd — crowd-linkbuilding control panel

Manage your donors, anchor plans, employee task queues and stop list in one place,
instead of fighting spreadsheets.

## What's inside (MVP)

- JWT login + roles (`admin`, `employee`)
- Donor database with CSV/XLSX import and CSV export
- Donor accounts (login_email / login_password / account_username) per donor
- Anchor plans + line items, CSV/XLSX import
- **Donor auto-match** — filters by geo / language / link_type, excludes
  `(target_url, donor_url)` pairs already used (per stop list + successful placements),
  ranks by quality score (TR / traffic / ref domains / backlinks)
- **Stop list** auto-populates when an employee marks a placement as `placed`;
  enforces `UNIQUE(target_url, donor_url)`
- "My tasks" view for employees with account suggestion
  (least-used active account on the chosen donor)
- Dashboard with totals, sparkline of last 14 days and top employees
- User management (admin only)

## Stack

| Layer    | Choice                                   |
|----------|------------------------------------------|
| Backend  | Python 3.11+ • FastAPI • SQLAlchemy 2.x  |
| DB       | SQLite by default; switch via `DATABASE_URL` to Postgres (`postgresql+psycopg2://…`) |
| Auth     | JWT + bcrypt                             |
| Files    | pandas + openpyxl (XLSX), built-in csv   |
| Frontend | Vanilla JS modules + simple SPA shell, served by the same FastAPI app |

> The backend serves the frontend as static files — one process, one URL.

## Project layout

```
CROWD/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app + static frontend mount
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── auth.py
│   │   ├── models/__init__.py # SQLAlchemy models
│   │   ├── schemas/__init__.py
│   │   ├── routes/            # auth, users, donors, anchor_plans, placements, stop_list, dashboard
│   │   ├── services/          # matcher.py, importer.py, stop_list_service.py
│   │   └── seed.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── index.html
│   ├── css/styles.css
│   └── js/
│       ├── api.js
│       ├── app.js             # router
│       ├── components/
│       └── pages/
└── README.md
```

## Quick start

```bash
cd /Users/nikita/Desktop/CROWD

# 1. Create a virtual env (Python 3.11–3.12 recommended; see note below for 3.13)
python3 -m venv .venv
source .venv/bin/activate

# 2. Install backend deps
pip install -r backend/requirements.txt

# 3. Copy env (optional — defaults are fine for local dev)
cp backend/.env.example backend/.env

# 4. Seed admin + demo data
cd backend
python -m app.seed

# 5. Run the app
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000 in a browser.

Default credentials seeded by `python -m app.seed`:

- **Admin:** `admin@crowd.local` / `admin123`
- **Employees** (password `employee123`):
  - `nastya@crowd.local`
  - `andrey@crowd.local`
  - `artem@crowd.local`

The seed also adds 8 sample donors and a demo anchor plan with 6 items. After login
as admin, open **Anchor Plans → Demo plan → Auto-match donors** and the items
will get donors assigned.

## Note on Python 3.13 on macOS (this machine)

The current Homebrew Python 3.13.13 on this Mac has a broken `libexpat` link
(symbol `_XML_SetAllocTrackerActivationThreshold` missing). It surfaces when
pandas/openpyxl try to parse XML. Until Homebrew ships a fix, use one of:

```bash
# Option A: install Python 3.12 via pyenv
brew install pyenv
pyenv install 3.12.7
pyenv local 3.12.7

# Option B: repair Homebrew Python
brew reinstall expat python@3.13
```

## Switching to PostgreSQL

```
# backend/.env
DATABASE_URL=postgresql+psycopg2://crowd:crowd@localhost:5432/crowd
```

Then add `psycopg2-binary` to `requirements.txt` and re-run. Tables are created
on startup via `Base.metadata.create_all` — for production swap in Alembic.

## API surface (auto-documented)

After running, OpenAPI docs are at:

- http://localhost:8000/docs (Swagger UI)
- http://localhost:8000/redoc

Key endpoints:

| Endpoint                              | Method | Role     |
|---------------------------------------|--------|----------|
| `/auth/login`                         | POST   | public   |
| `/auth/me`                            | GET    | auth     |
| `/users`                              | GET    | auth     |
| `/users`                              | POST   | admin    |
| `/donors`                             | GET    | auth     |
| `/donors`                             | POST   | admin    |
| `/donors/import` (multipart file)     | POST   | admin    |
| `/donors/export`                      | GET    | admin    |
| `/donors/{id}/accounts`               | GET/POST | auth   |
| `/donors/{id}/usage`                  | GET    | auth     |
| `/anchor-plans`                       | GET    | auth     |
| `/anchor-plans/import`                | POST   | admin    |
| `/anchor-plans/{id}/items`            | GET    | auth     |
| `/anchor-plans/{id}/auto-match`       | POST   | admin    |
| `/anchor-plans/{id}/assign`           | POST   | admin    |
| `/anchor-plans/items/{id}/match-now`  | POST   | admin    |
| `/anchor-plans/items/{id}`            | PATCH  | auth     |
| `/anchor-plans/{id}/export`           | GET    | auth     |
| `/my-tasks`                           | GET    | auth     |
| `/my-tasks/{item_id}/take`            | POST   | auth     |
| `/placements/{id}/mark-placed`        | POST   | auth     |
| `/placements/{id}/mark-problem`       | POST   | auth     |
| `/stop-list`                          | GET    | auth     |
| `/stop-list/import`                   | POST   | admin    |
| `/stop-list/export`                   | GET    | admin    |
| `/dashboard/stats`                    | GET    | auth     |

## Business rules implemented

- `donors.donor_url` is **unique**.
- `stop_list_entries (target_url, donor_url)` is **unique** — one specific URL of
  yours cannot be placed twice on the same donor. Different URLs on the same
  domain can use the same donor.
- The matcher excludes any donor where `(target_url, donor_url)` already exists
  in the stop list or in a successful placement.
- When a placement is marked **placed**:
  - `result_url` is required.
  - Donor account is upserted (by `donor_id` + `account_username`) and linked
    to the placement.
  - A stop-list entry is created if it doesn't yet exist.
  - The corresponding anchor plan item is moved to status `placed`.
- "My tasks" suggests the **least-used active account** on the selected donor,
  so reusing the same donor for a different target URL doesn't reuse the same
  account when there's a free alternative.

## What's intentionally out of scope for MVP

- Audit log / donor edit history
- Background queue for huge imports (current sync flow handles tens of thousands of rows in a second or two)
- Manual UI for column mapping during import — auto-detection by synonyms covers the common files
- Encryption at rest for donor passwords (flagged for next iteration; today they are stored in plain text per project decision)
