"""What is worth storing. The board only shows fresh US tech roles, and free hosted Postgres holds a limited amount:

  * a fetch keeps only jobs that could be US tech roles (a US location, a title that is not never-tech, and a
    tech-style title or a description naming several technologies: the same test that decides what the LLM
    re-checks) and that were posted within the retention window (7 days by default);
  * every fetch then deletes stored jobs that are closed or have aged past the window.

Jobs someone is tracking (saved, applied) or labelled (to tune the ranking) are never removed, however old.
"""
from __future__ import annotations

from datetime import date, timedelta

from .classify import is_us_location
from .roles import MIN_TECH_TERMS, could_be_tech_title, is_excluded_title, tech_terms

KEEP_STATUSES = ("saved", "applied")  # a job someone is tracking stays, even once closed or old
RETENTION_DAYS = 7


def keep_job(title: str, location: str, description: str = "") -> bool:
    """Could this be a US tech role? Decided before classification, from what the source gives us."""
    if not is_us_location(location) or is_excluded_title(title):
        return False
    return could_be_tech_title(title) or len(tech_terms(description or "")) >= MIN_TECH_TERMS


def keep_description(title: str, location: str, description: str) -> bool:
    return bool(description) and keep_job(title, location, description)


def cutoff_date(days: int, today: date | None = None) -> str:
    return ((today or date.today()) - timedelta(days=days)).isoformat()


def jobs_worth_storing(jobs, days: int = RETENTION_DAYS, today: date | None = None) -> list:
    """The fetched jobs that could be US tech roles and were posted within the window. A job with no posting date
    is kept (its first-seen date then counts)."""
    cutoff = cutoff_date(days, today)
    return [j for j in jobs
            if (not j.posted_at or j.posted_at >= cutoff) and keep_job(j.title, j.location, j.description)]


# Saved or applied jobs, and jobs you labelled for tuning the ranking, are never removed.
_UNTRACKED = "status NOT IN ('saved', 'applied') AND id NOT IN (SELECT job_id FROM match_labels)"
_OLD = "COALESCE(NULLIF(posted_at, ''), first_seen) < :cutoff"


def prune_database(db, days: int = RETENTION_DAYS, full: bool = False, dry_run: bool = False,
                   today: date | None = None, batch: int = 2000) -> dict:
    """Delete untracked jobs that are closed or older than `days`. That part is plain SQL and runs after every
    fetch. With `full`, also delete untracked open jobs that fail keep_job (needed once, for data stored before
    this rule existed). Returns counts; with dry_run nothing is deleted."""
    cutoff = cutoff_date(days, today)
    condition = f"{_UNTRACKED} AND (closed_at IS NOT NULL OR {_OLD})"
    if dry_run:
        stale = db.query(f"SELECT COUNT(*) AS n FROM jobs WHERE {condition}", cutoff=cutoff)[0]["n"]
    else:
        stale = db.delete_where(condition, cutoff=cutoff)
    irrelevant = 0
    if full:
        rows = db.query(f"SELECT id, title, location, description FROM jobs WHERE {_UNTRACKED} "
                        f"AND closed_at IS NULL AND NOT ({_OLD})", cutoff=cutoff)
        ids = [r["id"] for r in rows if not keep_job(r["title"], r["location"], r["description"])]
        irrelevant = len(ids)
        if not dry_run:
            db.delete_jobs(ids, batch)
    total = db.query("SELECT COUNT(*) AS n FROM jobs")[0]["n"]
    return {"deleted": stale + irrelevant, "stale": stale, "irrelevant": irrelevant,
            "kept": total - (stale + irrelevant if dry_run else 0)}
