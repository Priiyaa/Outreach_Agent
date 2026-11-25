# Deploying (all free tiers)

```
Vercel (React app)  ──►  Render (FastAPI)  ──►  Postgres (Neon or Supabase)
                                                      ▲
GitHub Actions (daily fetch + classify) ──────────────┘
```

Free-tier limits change, so check each provider's current page before relying on a number here.
Steps marked **YOU** need your accounts or secrets; everything else is already in the repo.

## 0. Put the code on GitHub (YOU)

The code is committed locally on `main`. `.gitignore` keeps `.env`, `node_modules`, your profile and the local
database out. Create an empty GitHub repo (no README), then:

```bash
git remote add origin https://github.com/<you>/outreach-agent.git && git push -u origin main
```
A public repo gets free Actions minutes and shows up on your resume; nothing secret is in it.

## 1. Database (YOU)

Create a free Postgres project on **Neon** (works over IPv4, wakes on demand) or **Supabase**
(use the *pooler* connection string, not the direct one: the direct host is IPv6-only and Render and
GitHub Actions cannot reach it). Copy the connection string and change its start to `postgresql+psycopg2://`
and make sure it ends with `?sslmode=require`:

```
postgresql+psycopg2://USER:PASSWORD@HOST/DBNAME?sslmode=require
```

## 2. Create the tables and copy your data

```bash
cd backend
export DATABASE_URL="postgresql+psycopg2://..."        # the string from step 1
alembic upgrade head                                    # creates the tables
python -m app.cli copy-db --to "$DATABASE_URL"          # copies the local SQLite data, then verifies row counts
```
`copy-db` refuses a database that already has rows, so running it twice cannot duplicate anything.
The copy takes seconds.

**Size.** The free databases hold about 500 MB. Run `python -m app.cli trim --vacuum` locally before copying: it
clears descriptions the board never needs (closed, non-US and non-tech jobs; saved and applied jobs keep theirs).
That took the local file from 800 MB to 449 MB, and every fetch stores descriptions under the same rule, so the
database stays small. Check the hosted size after the copy:
```sql
SELECT pg_size_pretty(pg_database_size(current_database()));
```

## 3. API on Render (YOU)

1. Render dashboard, **New > Blueprint**, pick the repo. It reads `render.yaml`.
2. Fill the secrets it asks for:
   - `DATABASE_URL`: the string from step 1
   - `WRITE_TOKEN`: a long random string. This is the access code people type to unlock editing. Without it anyone with the link can edit.
   - `CORS_ORIGINS`: leave a placeholder for now, set it in step 4 (a JSON list, e.g. `["https://your-app.vercel.app"]`)
   - `PROFILE_YAML`: optional. The easier route is the board's **Profile** page: upload a resume, review, save. That
     profile is stored in the database and wins over `PROFILE_YAML`. Use this variable only to start from your
     `backend/config/profile.yaml` (not committed, because it describes you). Resume files are never stored.
3. Deploy. Check `https://<your-service>.onrender.com/api/health` returns `{"status":"ok"}`, and `/docs` shows the API.

The container runs `alembic upgrade head` on every start, so schema changes apply themselves.

## 4. Frontend on Vercel (YOU)

1. Vercel, **Add New > Project**, pick the repo, and set **Root Directory** to `frontend`.
2. Add the environment variable `NEXT_PUBLIC_API_URL` = your Render URL (no trailing slash).
3. Deploy, then go back to Render and set `CORS_ORIGINS` to `["https://<your-project>.vercel.app"]`, and redeploy the API.

## 5. Daily fetch on GitHub Actions (YOU)

Repo **Settings > Secrets and variables > Actions**, add `DATABASE_URL` (the same string).
Optionally `GEMINI_API_KEY` and `PROFILE_YAML` (same text as on Render). Each run re-ranks jobs
for the profile saved on the board, or `PROFILE_YAML` when none is saved. Then **Actions > Daily fetch > Run workflow** to test it once.
After that it runs every day at 12:00 UTC (edit the cron in `.github/workflows/fetch.yml`).

## 6. Check it works

- Open the Vercel URL: jobs load (the first request after idle can take up to a minute while Render wakes).
- Click **Unlock editing**, enter your `WRITE_TOKEN`, change a status, press Save, reload: it stuck.
- The Actions run is green and `python -m app.cli stats` in its log shows the job counts.

## Known limits

- **One shared dataset.** Statuses and sponsorship edits are stored on the job, so everyone using the site sees the same ones.
  Per-person tracking needs user accounts (a later step).
- **The access code is not real login.** It keeps strangers from editing; it does not tell users apart.
- **Cold starts.** Render's free API sleeps when idle.
- **One match profile.** "Best match" ranks jobs for a single profile (set on the Profile page). Scores for several
  people need user accounts; the `job_matches` table is already keyed by profile. Saving re-ranks every job in about
  10 s locally; expect longer on Render's free CPU.
- **Postgres is first exercised in CI.** The tests in `backend/tests/test_postgres.py` run against a real Postgres
  service in GitHub Actions. They cannot run on the machine this was written on, so watch the first CI run.
