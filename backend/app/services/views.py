"""Query and edit layer behind the API: filters, paging, counts and edits. No web framework imported, so it is easy to test."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone

from ..db.repository import HIDDEN_DUPLICATE, SPONSORSHIP_VALUES, STATUS_VALUES

STATUS_LABELS = {"new": "New", "saved": "Saved", "applied": "Applied", "skipped": "Skipped"}
LABEL_TO_STATUS = {v: k for k, v in STATUS_LABELS.items()}

# filter name -> SQL column. Adding a new multi-select filter later = add one line here.
MULTI_FILTERS = {
    "experience": "jobs.experience",
    "sponsorship": "jobs.sponsorship",
    "status": "jobs.status",
    "source": "jobs.source",
}

CSV_COLUMNS = [
    "company", "title", "location", "experience", "sponsorship", "sponsorship_note",
    "status", "remote", "source", "posted_at", "first_seen", "url", "match_score", "match_reasons",
]

# Every jobs query joins the match score for the active profile (NULL when not scored).
_FROM = "FROM jobs LEFT JOIN job_matches m ON m.job_id = jobs.id AND m.profile = :profile "
SORTS = {
    "newest": "jobs.first_seen DESC, jobs.company, jobs.title, jobs.id",
    "match": "m.score DESC, jobs.first_seen DESC, jobs.company, jobs.title, jobs.id",
}

_SELECT = (
    "SELECT jobs.id AS id, jobs.company, jobs.title, jobs.location, "
    "jobs.remote, jobs.experience, "
    "jobs.exp_reason, jobs.sponsorship, jobs.sponsorship_source, "
    "jobs.sponsorship_note, jobs.status, jobs.source, jobs.posted_at, jobs.first_seen, jobs.url, "
    "jobs.closed_at, jobs.company_key, jobs.cs_evidence AS cs_role_evidence, jobs.role_family, "
    "m.score AS match_score, COALESCE(m.reasons, '') AS match_reasons "
    f"{_FROM}"
)


def _build_where(
    *,
    us_only: bool = True,
    include_internships: bool = False,
    include_closed: bool = False,
    search: str = "",
    location: str = "",
    since_days: int | None = None,
    now: datetime | None = None,
    cs_related_only: bool = False,
    profile: str = "",
    matches_only: bool = False,
    min_score: int = 0,
    **multi: list[str] | None,
) -> tuple[str, dict]:
    """The WHERE clause and its parameters for a set of filters. Any MULTI_FILTERS name may be passed as a list
    of allowed values (empty/None = all)."""
    unknown = set(multi) - set(MULTI_FILTERS)
    if unknown:
        raise TypeError(f"unknown filter(s): {', '.join(sorted(unknown))}")
    where = [f"NOT {HIDDEN_DUPLICATE}"]
    params: dict = {"profile": profile}
    if us_only:
        where.append("jobs.is_us = 1")
    if not include_internships:
        where.append("jobs.is_internship = 0")
    if not include_closed:
        where.append("jobs.closed_at IS NULL")
    if cs_related_only:
        where.append("jobs.is_cs_role = 1")
    for name, values in multi.items():
        if values:
            keys = [f"{name}{i}" for i in range(len(values))]
            where.append(f"{MULTI_FILTERS[name]} IN ({', '.join(':' + k for k in keys)})")
            params.update(zip(keys, values))
    for i, term in enumerate(search.split()):
        where.append(f"(LOWER(jobs.title) LIKE :term{i} OR LOWER(jobs.company) LIKE :term{i})")
        params[f"term{i}"] = f"%{term.lower()}%"
    locs = [t.strip().lower() for t in location.split(",") if t.strip()]
    if locs:
        where.append("(" + " OR ".join(f"LOWER(jobs.location) LIKE :loc{i}" for i, _ in enumerate(locs)) + ")")
        params.update({f"loc{i}": f"%{t}%" for i, t in enumerate(locs)})
    if matches_only or min_score:
        where.append("m.score IS NOT NULL")  # scored = a job this profile can realistically get
    if min_score:
        where.append("m.score >= :min_score")
        params["min_score"] = int(min_score)
    if since_days is not None:
        # by the date the company posted it (first_seen when the source gives none); compared as YYYY-MM-DD
        params["cutoff"] = ((now or datetime.now(timezone.utc)) - timedelta(days=since_days)).date().isoformat()
        where.append("COALESCE(NULLIF(jobs.posted_at, ''), jobs.first_seen) >= :cutoff")
    return " AND ".join(where), params


def query_jobs(db, *, limit: int | None = None, offset: int = 0, sort: str = "newest", **filters) -> list[dict]:
    """Jobs for the table, newest first or best match first. `limit`/`offset` page in SQL so only the rows shown are read."""
    if sort not in SORTS:
        raise ValueError(f"unknown sort: {sort!r}")
    if sort == "match":
        filters["matches_only"] = True
    where, params = _build_where(**filters)
    # id last: many postings share company and title, and pages must not repeat or skip rows
    sql = _SELECT + f"WHERE {where} ORDER BY {SORTS[sort]}"
    if limit:
        sql += f" LIMIT {int(limit)} OFFSET {int(offset)}"
    return [dict(r) for r in db.query(sql, **params)]


def job_stats(db, **filters) -> dict:
    """Counts over every job the filters match, computed in SQL (no rows are loaded)."""
    where, params = _build_where(**filters)
    row = db.query(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN jobs.experience = 'New grad' THEN 1 ELSE 0 END) AS new_grad, "
        "SUM(CASE WHEN jobs.sponsorship = 'Yes' THEN 1 ELSE 0 END) AS sponsor_yes, "
        "SUM(CASE WHEN jobs.status IN ('new', 'saved') THEN 1 ELSE 0 END) AS not_applied "
        f"{_FROM}WHERE {where}",
        **params,
    )[0]
    return {k: int(row[k] or 0) for k in ("total", "new_grad", "sponsor_yes", "not_applied")}


def job_ids(db, **filters) -> list[str]:
    """Ids of every job the filters match, without loading the rows."""
    where, params = _build_where(**filters)
    sql = f"SELECT jobs.id {_FROM}WHERE {where}"
    return [r["id"] for r in db.query(sql, **params)]


def apply_job_edits(db, edits: dict[str, dict]) -> int:
    """edits: {job_id: {"status": label-or-value, "sponsorship": "Yes|No|Unknown", "sponsorship_note": str}}.
    Invalid values are rejected before anything is written. Returns the number of jobs changed."""
    cleaned: dict[str, dict] = {}
    for job_id, changes in edits.items():
        out: dict = {}
        if "status" in changes:
            value = LABEL_TO_STATUS.get(changes["status"], changes["status"])
            if value not in STATUS_VALUES:
                raise ValueError(f"invalid status: {changes['status']!r}")
            out["status"] = value
        if "sponsorship" in changes:
            if changes["sponsorship"] not in SPONSORSHIP_VALUES:
                raise ValueError(f"invalid sponsorship: {changes['sponsorship']!r}")
            out["sponsorship"] = changes["sponsorship"]
        if "sponsorship_note" in changes:
            out["sponsorship_note"] = str(changes["sponsorship_note"] or "")
        if out:
            cleaned[job_id] = out
    for job_id, out in cleaned.items():
        db.update_job_fields(job_id, **out)
    return len(cleaned)


def jobs_to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()
