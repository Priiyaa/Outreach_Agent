# outreach-agent

A personalized job board for international students looking for early-career tech roles in the USA. It pulls
every open posting from company career boards (Greenhouse, Lever, Ashby, Workday) and curated GitHub lists (Simplify,
Jobright), reads each one, and keeps the real tech roles, labelled by experience level and visa sponsorship,
and ranks them against your resume.

**Status:** Phase 1 in progress. Backend, LLM classifier stage (off until you add a free API key) and React frontend are built; deployment config is ready (see DEPLOY.md); it needs your accounts.

## Project layout

```
outreach-agent/
├── backend/                  Python API + data pipeline
│   ├── app/
│   │   ├── main.py           FastAPI app (CORS, routers)
│   │   ├── cli.py            command line: fetch, classify, check, discover, export, stats
│   │   ├── domain.py         Job dataclass shared by sources and the database
│   │   ├── api/              HTTP layer: routes.py, schemas.py (the contract), deps.py
│   │   ├── core/config.py    environment settings (DATABASE_URL, CORS origins)
│   │   ├── db/               models.py (tables), repository.py (all SQL), session.py (which DB to open)
│   │   ├── services/         classify.py (labels), views.py (queries and edits), fetch_runner.py, ats_urls.py
│   │   └── sources/          one adapter per job source
│   ├── alembic/              database migrations
│   ├── config/               yaml: fetch targets, tuning, your match profile
│   ├── tests/                pytest, no internet needed
│   └── Dockerfile
├── frontend/                 Next.js + TypeScript + Tailwind app (see frontend/README.md)
├── legacy/                   Superseded Streamlit app and Flask prototype, kept for reference
├── docker-compose.yml        API + Postgres for local development
├── render.yaml               Render blueprint for the API
├── DEPLOY.md                 step-by-step deployment (free tiers)
└── .github/workflows/ci.yml  lint, tests, migration check
```

Layers only depend downward: `api` -> `services` -> `db`. `services` never imports `api`, so the same logic
serves the HTTP API and the CLI.

## Run it locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements-dev.txt
cd backend
alembic upgrade head                 # create or upgrade the database (SQLite file by default)
python -m app.cli fetch              # pull jobs, label and rank them (or use the board's Fetch button later)
uvicorn app.main:app --port 8000     # API at http://localhost:8000, interactive docs at /docs
python -m app.cli stats              # what is in the database
pytest                               # tests
ruff check .                         # lint
```

Frontend (second terminal):
```bash
cd frontend && npm install && npx next dev -p 3100   # http://localhost:3100, talks to the API on :8000
```
Ports 3000 and 5000 are often taken on a Mac (5000 by AirPlay Receiver), hence 3100. If you use another port, add
it to `CORS_ORIGINS` in `backend/.env`.

With Docker (Postgres + API): `docker compose up --build`.

## API

| Method and path | What it does |
| --- | --- |
| `GET /api/jobs` | Filtered, paged jobs plus counts for every match. Filters: `experience`, `sponsorship`, `status`, `source` (repeatable), `cs_only`, `us_only`, `internships`, `closed`, `search`, `location`, `since_days`; paging: `limit` (max 500), `offset` |
| `GET /api/jobs.csv` | Same filters, every match as CSV |
| `PATCH /api/jobs` | Edit status, sponsorship and note for several jobs: `{job_id: {...}}` |
| `POST /api/jobs/bulk-sponsorship` | Set Sponsors? on everything the filters match |
| `POST` / `GET /api/fetch` | Start a background fetch; poll its status |
| `GET /api/meta` | Allowed values for every dropdown, and whether editing is locked / fetch is enabled |
| `GET /api/auth/check` | 200 if the access code is right (or none is needed) |

## Configuration

| Setting | Where | Default |
| --- | --- | --- |
| `DATABASE_URL` | env var or `backend/.env` | the SQLite file named by `db_path` in `config/config.yaml` |
| `CORS_ORIGINS` | env var | `["http://localhost:3000"]` |
| `WRITE_TOKEN` | env var | unset = anyone can edit; set = writes need `Authorization: Bearer <token>` |
| `ALLOW_FETCH` | env var | `true`; set `false` where a schedule does the fetching |
| fetch targets, LLM settings | `backend/config/*.yaml` | see the files |

## How labels are decided

- **CS role:** title and department match first, then technical work in the description (an action like
  "build" with an object like "API"). Stored on each job when it is classified, so queries never re-read descriptions.
- **Experience:** New grad = 0-3 years, Experienced = 3+. Title, then "N years" in the description, then new-grad
  wording. "Unclear" means no signal; it is never guessed.
- **Sponsorship:** per job. Unknown, or Yes/No when the posting says so. Once you set it, it is locked.

## The LLM stage (optional, off by default)

The rules decide clear cases for free. The LLM re-reads only the uncertain ones: a role matched only by
description wording, or a non-tech title whose description still has several technical terms. It only looks
at US, non-internship jobs that are not clearly senior, which is about 9,600 jobs today. It can overturn the
rules in either direction and records a role family (Software, ML/AI, Agentic AI, Research, Data,
Infra/Security, Other tech, Not tech). Answers are cached by a hash of the posting text.

```bash
python -m app.cli llm-classify            # with no provider set: shows how many jobs it would send, sends nothing
```
To turn it on: set `llm.provider: gemini` in `backend/config/config.yaml`, put `GEMINI_API_KEY=...` in `backend/.env`
(free key from Google AI Studio), and check `llm.model` is a current model name. `fetch` and `classify` then run
the stage automatically, up to `llm.max_calls_per_run` calls each time.

**Measure it** (this gives you a precision and recall number):
```bash
python -m app.cli sample --size 200       # writes data/eval/sample.csv
# fill the human_label column: 1 = tech role, 0 = not
python -m app.cli eval                    # scores the labels as sampled vs now
```
Run `eval` once with the LLM off, then again after `llm-classify`, to show the improvement.

## How it behaves

- Re-running `fetch` never duplicates rows (keyed on source, board, posting id).
- A posting that disappears is marked closed, not deleted; it reopens if it returns.
- Your status and sponsorship edits are never overwritten by a re-fetch.
- One failing company or list is logged and skipped. An empty response never closes a board's jobs.

## Changing the database schema

Edit `backend/app/db/models.py`, then `alembic revision --autogenerate -m "what changed"` and
`alembic upgrade head`. CI fails if the models and migrations disagree.
