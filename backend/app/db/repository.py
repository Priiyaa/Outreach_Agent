from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, RowMapping

from ..domain import DIRECT_SOURCES, Job
from .models import Base

# `status`, sponsorship and the derived columns are deliberately absent from the UPDATE list: a re-fetch
# must never overwrite what you set by hand. A job that reappears is re-opened. classified_at is cleared
# only when the title, location, description or notes changed, so the job gets re-classified.
UPSERT = """
INSERT INTO jobs (id, source, board, company, ext_id, title, url, location, department,
                  remote, posted_at, description, notes, ats_ref, first_seen, last_seen)
VALUES (:id, :source, :board, :company, :ext_id, :title, :url, :location, :department,
        :remote, :posted_at, :description, :notes, :ats_ref, :ts, :ts)
ON CONFLICT(id) DO UPDATE SET
    classified_at = CASE
        WHEN jobs.title != excluded.title OR jobs.location != excluded.location
          OR (excluded.description != '' AND jobs.description != excluded.description) OR jobs.notes != excluded.notes
        THEN NULL ELSE jobs.classified_at END,
    company     = excluded.company,
    title       = excluded.title,
    url         = excluded.url,
    location    = excluded.location,
    department  = excluded.department,
    remote      = excluded.remote,
    posted_at   = COALESCE(excluded.posted_at, jobs.posted_at),
    description = CASE WHEN excluded.description = '' THEN jobs.description ELSE excluded.description END,
    notes       = excluded.notes,
    ats_ref     = COALESCE(excluded.ats_ref, jobs.ats_ref),
    last_seen   = excluded.last_seen,
    closed_at   = NULL
"""

_DIRECT = ", ".join(f"'{s}'" for s in DIRECT_SOURCES)

# A curated-list row (simplify/jobright) is hidden when the same ATS posting is already in the table
# from the company's own board, which has the full description. Rows are kept, just not shown.
HIDDEN_DUPLICATE = (
    f"(source NOT IN ({_DIRECT}) AND ats_ref IS NOT NULL AND EXISTS ("
    f"SELECT 1 FROM jobs d WHERE d.ats_ref = jobs.ats_ref AND d.source IN ({_DIRECT}) AND d.closed_at IS NULL))"
)

EXPORT_COLUMNS = [
    "first_seen", "posted_at", "company", "title", "location", "remote", "department",
    "experience", "sponsorship", "source", "notes", "url", "status", "description_chars",
]

SPONSORSHIP_VALUES = ("Yes", "No", "Unknown")
STATUS_VALUES = ("new", "saved", "applied", "skipped")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DB:
    """All database access. Takes a SQLite file path or a SQLAlchemy URL, so the same code runs locally on
    SQLite and in production on Postgres. Raw SQL goes through `query`/`scalar` with named :params."""

    def __init__(self, path_or_url: str | Path) -> None:
        url = str(path_or_url)
        if "://" not in url:
            url = f"sqlite:///{url}"
        if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
            Path(url[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(
            url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {}, pool_pre_ping=True
        )
        if self.engine.dialect.name == "sqlite":
            Base.metadata.create_all(self.engine)  # local convenience; Postgres schema comes from Alembic

    # ---- plumbing -------------------------------------------------------------------------------

    def query(self, sql: str, **params) -> list[RowMapping]:
        with self.engine.connect() as conn:
            return list(conn.execute(text(sql), params).mappings())

    def scalar(self, sql: str, **params):
        with self.engine.connect() as conn:
            return conn.execute(text(sql), params).scalar()

    def execute(self, sql: str, params: dict | list[dict] | None = None) -> int:
        """Run one write (or the same write for a list of param dicts) in its own transaction."""
        with self.engine.begin() as conn:
            return conn.execute(text(sql), params or {}).rowcount

    # ---- fetching -------------------------------------------------------------------------------

    def record_board(self, source: str, board: str, jobs: list[Job], run_ts: str,
                     seen: list[Job] | None = None) -> tuple[int, int]:
        """Upsert one board's (or list's) jobs. Returns (new, closed). Safe to call repeatedly.
        `seen`: everything the board listed, when `jobs` is only the part worth storing (services.storage). Stored
        jobs it still lists stay open, even when they are no longer updated (a tracked job past the age limit);
        stored jobs it no longer lists are closed. Defaults to `jobs`."""
        seen = jobs if seen is None else seen
        unique = {j.id: j for j in jobs}
        with self.engine.begin() as conn:
            existing = {
                r["id"]
                for r in conn.execute(
                    text("SELECT id FROM jobs WHERE source = :source AND board = :board"),
                    {"source": source, "board": board},
                ).mappings()
            }
            new = sum(1 for job_id in unique if job_id not in existing)
            if unique:
                conn.execute(
                    text(UPSERT),
                    [
                        {
                            "id": j.id, "source": j.source, "board": j.board, "company": j.company,
                            "ext_id": j.ext_id, "title": j.title, "url": j.url, "location": j.location,
                            "department": j.department, "remote": int(j.remote),
                            "posted_at": j.posted_at, "description": j.description,
                            "notes": j.notes, "ats_ref": j.ats_ref, "ts": run_ts,
                        }
                        for j in unique.values()
                    ],
                )
            still_listed = [{"id": j.id, "ts": run_ts} for j in seen if j.id in existing and j.id not in unique]
            if still_listed:
                conn.execute(text("UPDATE jobs SET last_seen = :ts WHERE id = :id"), still_listed)
            closed = 0
            # Anything we didn't see this run has been taken down. An empty response is treated
            # as suspicious (could be a transient glitch) and never closes the whole board.
            if seen:
                closed = conn.execute(
                    text(
                        "UPDATE jobs SET closed_at = :ts WHERE source = :source AND board = :board "
                        "AND closed_at IS NULL AND last_seen < :ts"
                    ),
                    {"ts": run_ts, "source": source, "board": board},
                ).rowcount
        return new, closed

    def set_match_label(self, profile: str, job_id: str, label: str | None, ts: str) -> None:
        """Record "good" / "bad" for a ranked job, or clear it with None."""
        self.execute("DELETE FROM match_labels WHERE profile = :p AND job_id = :j", {"p": profile, "j": job_id})
        if label:
            self.execute("INSERT INTO match_labels (profile, job_id, label, created_at) VALUES (:p, :j, :l, :ts)",
                         {"p": profile, "j": job_id, "l": label, "ts": ts})

    def match_label_counts(self, profile: str) -> dict[str, int]:
        rows = self.query("SELECT label, COUNT(*) AS n FROM match_labels WHERE profile = :p GROUP BY label", p=profile)
        counts = {"good": 0, "bad": 0}
        counts.update({r["label"]: int(r["n"]) for r in rows})
        return counts

    def delete_where(self, condition: str, **params) -> int:
        """Delete the jobs matching a WHERE condition on `jobs`, with their match scores. Returns jobs deleted."""
        with self.engine.begin() as conn:
            conn.execute(text(f"DELETE FROM job_matches WHERE job_id IN (SELECT id FROM jobs WHERE {condition})"),
                         params)
            return conn.execute(text(f"DELETE FROM jobs WHERE {condition}"), params).rowcount

    def delete_jobs(self, ids: list[str], batch: int = 2000) -> int:
        """Delete jobs and their match scores. Returns how many jobs were deleted."""
        for i in range(0, len(ids), batch):
            chunk = ids[i:i + batch]
            names = ", ".join(f":id{n}" for n in range(len(chunk)))  # one statement per batch, not one per row
            params = {f"id{n}": x for n, x in enumerate(chunk)}
            self.execute(f"DELETE FROM job_matches WHERE job_id IN ({names})", params)
            self.execute(f"DELETE FROM jobs WHERE id IN ({names})", params)
        return len(ids)

    def log(self, run_ts: str, source: str, board: str, ok: bool, n_jobs: int, error: str | None) -> None:
        self.execute(
            "INSERT INTO fetch_log (run_ts, source, board, ok, n_jobs, error) "
            "VALUES (:run_ts, :source, :board, :ok, :n_jobs, :error)",
            {"run_ts": run_ts, "source": source, "board": board, "ok": int(ok), "n_jobs": n_jobs, "error": error},
        )

    # ---- classification -------------------------------------------------------------------------

    def rows_to_classify(self, force: bool = False) -> list[RowMapping]:
        where = "" if force else "WHERE classified_at IS NULL OR is_cs_role IS NULL"
        return self.query(
            f"SELECT id, source, company, title, department, location, description, notes FROM jobs {where}"
        )

    def save_classification(self, updates: list[dict], ts: str | None = None) -> None:
        """Write derived fields. Sponsorship is only replaced when it wasn't set by hand."""
        if not updates:
            return
        ts = ts or _now()
        self.execute(
            "UPDATE jobs SET experience = :experience, exp_reason = :exp_reason, is_us = :is_us, "
            "is_internship = :is_internship, company_key = :company_key, "
            "is_cs_role = :is_cs_role, cs_evidence = :cs_evidence, "
            "sponsorship = CASE WHEN sponsorship_source = 'manual' THEN sponsorship ELSE :sponsorship END, "
            "classified_at = :ts WHERE id = :id",
            [{**u, "ts": ts} for u in updates],
        )

    def llm_candidates(self) -> list[RowMapping]:
        """Jobs the rules were unsure about (see services.llm.needs_llm, which makes the final cut)."""
        return self.query(
            "SELECT id, title, department, description, is_cs_role, cs_evidence FROM jobs "
            "WHERE closed_at IS NULL AND description != '' AND is_cs_role IS NOT NULL "
            "AND is_us = 1 AND is_internship = 0 AND experience != 'Experienced' "  # only jobs a new grad would see
            "AND (is_cs_role = 0 OR cs_evidence LIKE 'description:%')"
        )

    def llm_labels(self, model: str) -> dict[str, dict]:
        return {r["hash"]: dict(r) for r in self.query("SELECT * FROM llm_labels WHERE model = :m", m=model)}

    def save_llm_labels(self, labels: list[dict]) -> None:
        if labels:
            self.execute(
                "INSERT INTO llm_labels (hash, model, is_tech, role_family, reason, created_at) "
                "VALUES (:hash, :model, :is_tech, :role_family, :reason, :created_at) "
                "ON CONFLICT(hash, model) DO NOTHING",
                labels,
            )

    def apply_llm_labels(self, updates: list[dict]) -> None:
        if updates:
            self.execute(
                "UPDATE jobs SET is_cs_role = :is_cs_role, role_family = :role_family, cs_evidence = :cs_evidence "
                "WHERE id = :id",
                updates,
            )

    def match_candidates(self) -> list[RowMapping]:
        """Open US tech jobs (not internships) with what services.match needs to score them."""
        return self.query(
            "SELECT id, company_key, title, description, experience, exp_reason, sponsorship, location, posted_at, first_seen "
            f"FROM jobs WHERE closed_at IS NULL AND is_us = 1 AND is_cs_role = 1 AND is_internship = 0 AND NOT {HIDDEN_DUPLICATE}"
        )

    def no_sponsorship_companies(self, min_jobs: int = 10, share: float = 0.8) -> set[str]:
        """Companies whose open postings that have a description mostly say they won't sponsor (e.g. ITAR-bound
        employers). Used to judge their postings that came without a description."""
        rows = self.query(
            "SELECT company_key, COUNT(*) AS n, SUM(CASE WHEN sponsorship = 'No' THEN 1 ELSE 0 END) AS no "
            "FROM jobs WHERE closed_at IS NULL AND description != '' AND company_key IS NOT NULL "
            "GROUP BY company_key HAVING COUNT(*) >= :min_jobs", min_jobs=min_jobs,
        )
        return {r["company_key"] for r in rows if r["no"] / r["n"] >= share}

    def save_matches(self, profile: str, rows: list[dict], ts: str) -> None:
        """Replace every stored score for `profile` with `rows` ({job_id, score, reasons})."""
        self.execute("DELETE FROM job_matches WHERE profile = :p", {"p": profile})
        if rows:
            self.execute(
                "INSERT INTO job_matches (profile, job_id, score, reasons, scored_at) "
                "VALUES (:profile, :job_id, :score, :reasons, :ts)",
                [{**r, "profile": profile, "ts": ts} for r in rows],
            )

    def saved_profile(self) -> dict | None:
        """The profile saved from the board (most recent), as a dict, or None."""
        rows = self.query("SELECT data FROM profiles ORDER BY updated_at DESC LIMIT 1")
        return json.loads(rows[0]["data"]) if rows else None

    def save_profile(self, profile_id: str, data: dict, ts: str) -> None:
        """Store the one profile (replacing any other: the board supports one for now)."""
        self.execute("DELETE FROM profiles")
        self.execute("INSERT INTO profiles (id, data, updated_at) VALUES (:id, :data, :ts)",
                     {"id": profile_id, "data": json.dumps(data), "ts": ts})

    def update_job_fields(self, job_id: str, status: str | None = None, sponsorship: str | None = None,
                          sponsorship_note: str | None = None) -> None:
        """Set values by hand. Setting sponsorship locks it: later fetches never overwrite it."""
        sets: list[str] = []
        params: dict = {"job_id": job_id}
        if status is not None:
            sets.append("status = :status")
            params["status"] = status
        if sponsorship is not None:
            sets += ["sponsorship = :sponsorship", "sponsorship_source = 'manual'"]
            params["sponsorship"] = sponsorship
        if sponsorship_note is not None:
            sets.append("sponsorship_note = :note")
            params["note"] = sponsorship_note
        if not sets:
            return
        self.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = :job_id", params)

    def bulk_set_sponsorship(self, job_ids: list[str], value: str) -> int:
        if job_ids:
            self.execute(
                "UPDATE jobs SET sponsorship = :value, sponsorship_source = 'manual' WHERE id = :id",
                [{"value": value, "id": job_id} for job_id in job_ids],
            )
        return len(job_ids)

    # ---- reading --------------------------------------------------------------------------------

    def export_rows(
        self,
        since_days: int | None = None,
        locations: list[str] | None = None,
        include_closed: bool = False,
        now: datetime | None = None,
    ) -> list[dict]:
        sql = (
            "SELECT first_seen, posted_at, company, title, location, remote, department, experience, "
            "sponsorship, source, notes, url, status, LENGTH(description) AS description_chars "
            "FROM jobs "
            f"WHERE NOT {HIDDEN_DUPLICATE}"
        )
        params: dict = {}
        if not include_closed:
            sql += " AND closed_at IS NULL"
        if since_days is not None:
            sql += " AND first_seen >= :cutoff"
            params["cutoff"] = ((now or datetime.now(timezone.utc)) - timedelta(days=since_days)).isoformat()
        if locations:
            sql += " AND (" + " OR ".join(f"LOWER(location) LIKE :loc{i}" for i, _ in enumerate(locations)) + ")"
            params.update({f"loc{i}": f"%{loc.lower()}%" for i, loc in enumerate(locations)})
        sql += " ORDER BY first_seen DESC, company, title"
        return [dict(r) for r in self.query(sql, **params)]

    def stats(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        shown = f"closed_at IS NULL AND NOT {HIDDEN_DUPLICATE}"
        last_run = self.scalar("SELECT MAX(run_ts) FROM fetch_log")
        return {
            "open": self.scalar(f"SELECT COUNT(*) FROM jobs WHERE {shown}"),
            "closed": self.scalar("SELECT COUNT(*) FROM jobs WHERE closed_at IS NOT NULL"),
            "new_24h": self.scalar(
                f"SELECT COUNT(*) FROM jobs WHERE {shown} AND first_seen >= :cutoff",
                cutoff=(now - timedelta(hours=24)).isoformat(),
            ),
            "by_source": {
                r["source"]: r["n"]
                for r in self.query(f"SELECT source, COUNT(*) AS n FROM jobs WHERE {shown} GROUP BY source")
            },
            "top_companies": [
                (r["company"], r["n"])
                for r in self.query(
                    f"SELECT company, COUNT(*) AS n FROM jobs WHERE {shown} "
                    "GROUP BY company ORDER BY n DESC LIMIT 10"
                )
            ],
            "last_run": last_run,
            "last_run_failures": [
                (r["source"], r["board"], r["error"])
                for r in self.query(
                    "SELECT source, board, error FROM fetch_log WHERE run_ts = :ts AND ok = 0", ts=last_run
                )
            ]
            if last_run
            else [],
        }
