"""Curated GitHub job lists (Simplify, Jobright). They carry title/company/location, not descriptions."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

from ..domain import Job
from ..services.ats_urls import ats_ref_for_url
from .base import Source, to_date

_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)[^)]*\)")


def parse_simplify(data, list_slug: str) -> list[Job]:
    """SimplifyJobs listings.json: a JSON array; dates are unix seconds; skip inactive/hidden entries."""
    if not isinstance(data, list):
        raise ValueError(f"unexpected Simplify response: {str(data)[:120]}")
    jobs = []
    for p in data:
        if p.get("active") is False or p.get("is_visible") is False:
            continue
        title = (p.get("title") or "").strip()
        url = p.get("url") or ""
        if not (p.get("id") and title and url):
            continue
        locations = [str(x).strip() for x in p.get("locations") or [] if x]
        notes = "; ".join(
            part
            for part in (
                f"Sponsorship: {p['sponsorship']}" if p.get("sponsorship") else "",
                f"Degrees: {', '.join(p['degrees'])}" if p.get("degrees") else "",
            )
            if part
        )
        posted = p.get("date_posted")
        jobs.append(
            Job(
                source="simplify",
                board=list_slug,
                company=(p.get("company_name") or "").strip() or "Unknown",
                ext_id=str(p["id"]),
                title=title,
                url=url,
                location="; ".join(locations),
                department=p.get("category") or "",
                remote=any("remote" in loc.lower() for loc in locations),
                posted_at=to_date(posted * 1000) if isinstance(posted, (int, float)) else None,
                notes=notes,
                ats_ref=ats_ref_for_url(url),
            )
        )
    return jobs


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _plain(text: str) -> str:
    return re.sub(r"\*\*|`", "", text).strip()


def _link(cell: str) -> tuple[str, str]:
    """'**[Text](url)**' -> ('Text', 'url'); a cell without a link -> (plain text, '')."""
    match = _LINK.search(cell)
    return (_plain(match.group(1)), match.group(2)) if match else (_plain(cell), "")


def _strip_query(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _month_day(text: str, today: date) -> str | None:
    """'Aug 09' (no year) -> ISO date, assuming this year, or last year if that would be in the future."""
    match = re.match(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})", text.strip())
    if not match:
        return None
    try:
        day = datetime.strptime(f"{match.group(1).title()} {match.group(2)} {today.year}", "%b %d %Y").date()
        if day > today + timedelta(days=1):
            day = day.replace(year=today.year - 1)
    except ValueError:
        return None
    return day.isoformat()


def parse_jobright(text: str, list_slug: str, today: date | None = None) -> list[Job]:
    """Jobright README tables: Company | Job Title | Location | Work Model | Date Posted.

    A company cell of '↳' means 'same company as the row above'. Columns are located by header name,
    so a reordered table still parses. Raises ValueError if no job table is found (format changed).
    """
    today = today or date.today()
    jobs: list[Job] = []
    cols: dict[str, int] | None = None
    saw_table = False
    prev_company = ""

    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            cols = None  # the table ended
            continue
        cells = _cells(line)
        headers = [_plain(c).lower() for c in cells]
        if "company" in headers and ("job title" in headers or "title" in headers):
            cols = {name: i for i, name in enumerate(headers)}
            saw_table = True
            prev_company = ""
            continue
        if cols is None or set("".join(cells)) <= set("-: "):  # outside a table, or the |---| row
            continue

        def cell(*names: str) -> str:
            for name in names:
                i = cols.get(name)  # type: ignore[union-attr]
                if i is not None and i < len(cells):
                    return cells[i]
            return ""

        company, _ = _link(cell("company"))
        if company in ("", "↳"):
            company = prev_company
        else:
            prev_company = company
        title, url = _link(cell("job title", "title"))
        if not (title and url and company):
            continue
        url = _strip_query(url)  # drop utm tracking params
        location = _plain(cell("location"))
        work_model = _plain(cell("work model"))
        jobs.append(
            Job(
                source="jobright",
                board=list_slug,
                company=company,
                ext_id=urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1] or url,
                title=title,
                url=url,
                location=location,
                remote="remote" in f"{work_model} {location}".lower(),
                posted_at=_month_day(_plain(cell("date posted", "date")), today),
                notes=f"Work model: {work_model}" if work_model else "",
                ats_ref=ats_ref_for_url(url),
            )
        )
    if not saw_table:
        raise ValueError("no job table found in README (format changed?)")
    return jobs


class Simplify(Source):
    name = "simplify"

    def fetch(self, entry: dict) -> list[Job]:
        return parse_simplify(self.get(entry["url"]), entry["slug"])


class Jobright(Source):
    name = "jobright"

    def fetch(self, entry: dict) -> list[Job]:
        return parse_jobright(self.get_text(entry["url"]), entry["slug"])
