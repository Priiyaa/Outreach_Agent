"""Recognize Greenhouse / Lever / Ashby / Workday job links and pull out the board slug and posting id."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

_GREENHOUSE_HOSTS = {
    "boards.greenhouse.io", "job-boards.greenhouse.io",
    "boards.eu.greenhouse.io", "job-boards.eu.greenhouse.io",
}
_LEVER_HOSTS = {"jobs.lever.co", "jobs.eu.lever.co"}
_ASHBY_HOSTS = {"jobs.ashbyhq.com"}
_LOCALE = re.compile(r"^[a-z]{2}(?:-[A-Za-z]{2})?$")


def _workday(host: str, segs: list[str]) -> tuple[str, str, str | None] | None:
    """company.wd5.myworkdayjobs.com/[en-US/]Site/job/<place>/<Title_ID>, or
    wd5.myworkdaysite.com/[en-US/]recruiting/<tenant>/<Site>/job/... -> ("workday", "<host>/<tenant>/<Site>", id)."""
    if segs and _LOCALE.match(segs[0]):
        segs = segs[1:]
    if host.endswith(".myworkdayjobs.com"):
        tenant, rest = host.split(".", 1)[0], segs
    elif host.endswith(".myworkdaysite.com") and len(segs) >= 3 and segs[0] == "recruiting":
        tenant, rest = segs[1], segs[2:]
    else:
        return None
    if not rest or rest[0] in ("job", "details", "wday"):
        return None
    site, tail = rest[0], rest[1:]
    posting = None
    if tail and tail[0] in ("job", "details"):
        last = [t for t in tail[1:] if t not in ("apply", "applyManually", "autofillWithResume")]
        if last:
            posting = last[-1].rsplit("_", 1)[-1] if "_" in last[-1] else last[-1]
    return "workday", f"{host}/{tenant}/{site}", posting


def parse_ats_url(url: str) -> tuple[str, str, str | None] | None:
    """Return (source, board_slug, posting_id_or_None) for a recognized ATS URL, else None.

    Company-branded careers pages (e.g. ...?gh_jid=123 on the company's own domain) carry no slug
    and are not recognized.
    """
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    segs = [s for s in parts.path.split("/") if s]

    if host in _GREENHOUSE_HOSTS:
        if segs and segs[0] == "embed":  # embed/job_app?for=<slug>&token=<id>
            query = parse_qs(parts.query)
            slug = (query.get("for") or [""])[0]
            return ("greenhouse", slug, (query.get("token") or [None])[0]) if slug else None
        if not segs:
            return None
        posting = segs[2] if len(segs) >= 3 and segs[1] == "jobs" else None
        return "greenhouse", segs[0], posting
    if host in _LEVER_HOSTS and segs:
        return "lever", segs[0], segs[1] if len(segs) >= 2 else None
    if host in _ASHBY_HOSTS and segs:
        return "ashby", segs[0], segs[1] if len(segs) >= 2 else None
    if host.endswith((".myworkdayjobs.com", ".myworkdaysite.com")):
        return _workday(host, segs)
    return None


def ats_ref_for_url(url: str) -> str | None:
    """Canonical 'source:slug:id' (lowercased) for a link to one specific ATS posting."""
    hit = parse_ats_url(url)
    if not hit or not hit[2]:
        return None
    return f"{hit[0]}:{hit[1]}:{hit[2]}".lower()
