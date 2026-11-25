"""What is worth storing. Free hosted Postgres holds about 500 MB, and most of a fetch is descriptions of jobs the
board never shows (non-tech, outside the US, closed). A description is kept only when it could matter: the job
could be a US tech role, either by its title or by the technologies its description names (the same test that
decides what the LLM re-checks). Every other job keeps its title, location and link, just not the text.
"""
from __future__ import annotations

from .classify import is_us_location
from .roles import MIN_TECH_TERMS, could_be_tech_title, is_excluded_title, tech_terms

KEEP_STATUSES = ("saved", "applied")  # a job someone is tracking keeps its description, even once closed


def keep_description(title: str, location: str, description: str) -> bool:
    if not description or not is_us_location(location) or is_excluded_title(title):
        return False
    return could_be_tech_title(title) or len(tech_terms(description)) >= MIN_TECH_TERMS


def drop_unneeded_descriptions(jobs) -> int:
    """Blank the description of every job not worth storing, in place. Returns how many were blanked."""
    dropped = 0
    for job in jobs:
        if job.description and not keep_description(job.title, job.location, job.description):
            job.description = ""
            dropped += 1
    return dropped


def trim_database(db, batch: int = 2000) -> dict:
    """Blank stored descriptions the board doesn't need: closed jobs, and open jobs that fail keep_description.
    Tracked jobs (saved, applied) are never touched. Returns counts."""
    rows = db.query(
        "SELECT id, title, location, description, closed_at, status FROM jobs WHERE description != ''"
    )
    ids = [
        r["id"] for r in rows
        if r["status"] not in KEEP_STATUSES
        and (r["closed_at"] is not None or not keep_description(r["title"], r["location"], r["description"]))
    ]
    for i in range(0, len(ids), batch):
        db.execute("UPDATE jobs SET description = '' WHERE id = :id", [{"id": x} for x in ids[i:i + batch]])
    return {"checked": len(rows), "trimmed": len(ids), "kept": len(rows) - len(ids)}
