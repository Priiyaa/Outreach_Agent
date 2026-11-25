"""Companies you applied to stay on the fetch list, so their new postings keep showing up.

Marking a job applied records its company, plus the board the job came from: the job's own board for
Greenhouse/Lever/Ashby/Workday postings, or the board its link points to for jobs from curated lists. A company
whose career site the app can't read is still recorded by name, with no board, so it can be listed as such.
Every fetch also re-syncs from all applied jobs, so nothing is missed if a job was marked applied elsewhere.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..domain import DIRECT_SOURCES
from .ats_urls import parse_ats_url

FRESH_DAYS = 7  # "fresh" postings: posted (or first seen) within this many days


def board_for(source: str, board: str, url: str) -> tuple[str, str]:
    """(source, board) the app can fetch for this job, or ("", "") when its career site isn't supported."""
    if source in DIRECT_SOURCES:
        return source, board
    hit = parse_ats_url(url)
    return (hit[0], hit[1]) if hit else ("", "")


def sync_watched(db, job_ids: list[str] | None = None) -> int:
    """Record the company (and board) of every applied job, or of just `job_ids` when given. Returns rows added."""
    sql = ("SELECT company_key, company, source, board, url FROM jobs "
           "WHERE status = 'applied' AND company_key IS NOT NULL")
    params: dict = {}
    if job_ids is not None:
        if not job_ids:
            return 0
        names = ", ".join(f":j{i}" for i in range(len(job_ids)))
        sql += f" AND id IN ({names})"
        params = {f"j{i}": x for i, x in enumerate(job_ids)}
    existing = {(r["company_key"], r["source"], r["board"]) for r in db.query(
        "SELECT company_key, source, board FROM watched_companies")}
    named = {k for k, _s, b in existing if b}
    now = datetime.now(timezone.utc).isoformat()
    rows = {}
    for r in db.query(sql, **params):
        source, board = board_for(r["source"], r["board"], r["url"])
        key = (r["company_key"], source, board)
        if key in existing or key in rows:
            continue
        rows[key] = {"company_key": key[0], "source": source, "board": board, "name": r["company"], "ts": now}
    # A company already watched through a readable board doesn't also need a row without one.
    boarded = named | {k for k, _s, b in rows if b}
    rows = {key: row for key, row in rows.items() if key[2] or key[0] not in boarded}
    if rows:
        db.execute("INSERT INTO watched_companies (company_key, source, board, name, reason, added_at) "
                   "VALUES (:company_key, :source, :board, :name, 'applied', :ts)", list(rows.values()))
    return len(rows)


def watched_targets(db) -> list[tuple[str, dict]]:
    """Fetch targets for watched companies that have a readable board, in the form select_targets returns."""
    return [(r["source"], {"name": r["name"], "slug": r["board"]})
            for r in db.query("SELECT DISTINCT source, board, name FROM watched_companies WHERE board != ''")]


def watched_summary(db, profile: str, now: datetime | None = None) -> list[dict]:
    """Each watched company with its open matching jobs and how many of those are fresh and not yet acted on."""
    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=FRESH_DAYS)).date().isoformat()
    counts = {
        r["company_key"]: r for r in db.query(
            "SELECT j.company_key, COUNT(*) AS open_matches, "
            "SUM(CASE WHEN COALESCE(NULLIF(j.posted_at, ''), j.first_seen) >= :cutoff AND j.status = 'new' "
            "THEN 1 ELSE 0 END) AS fresh "
            "FROM jobs j JOIN job_matches m ON m.job_id = j.id AND m.profile = :profile "
            "WHERE j.closed_at IS NULL AND j.company_key IN (SELECT company_key FROM watched_companies) "
            "GROUP BY j.company_key", cutoff=cutoff, profile=profile)
    }
    out: dict[str, dict] = {}
    for r in db.query("SELECT company_key, source, board, name, added_at FROM watched_companies ORDER BY name"):
        item = out.setdefault(r["company_key"], {
            "company_key": r["company_key"], "company": r["name"], "boards": [], "added_at": r["added_at"],
            "open_matches": int((counts.get(r["company_key"]) or {}).get("open_matches") or 0),
            "fresh_matches": int((counts.get(r["company_key"]) or {}).get("fresh") or 0),
        })
        if r["board"]:
            item["boards"].append(f"{r['source']}:{r['board']}")
        item["added_at"] = min(item["added_at"], r["added_at"])
    return sorted(out.values(), key=lambda c: (-c["fresh_matches"], -c["open_matches"], c["company"].lower()))


def unwatch(db, company_key: str) -> int:
    return db.execute("DELETE FROM watched_companies WHERE company_key = :k", {"k": company_key})
