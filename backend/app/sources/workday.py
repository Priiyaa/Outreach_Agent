"""Workday career sites (company.wd5.myworkdayjobs.com/Site, wd5.myworkdaysite.com/recruiting/company/Site).

Every Workday careers page is backed by a JSON endpoint, /wday/cxs/<tenant>/<site>/jobs, which the page itself
calls. It is not a documented public API, so a change on Workday's side shows up as a failed board in the fetch
log, like any other broken board.

The listing gives title, location, path and "Posted N Days Ago" (20 per request). The description needs one more
request per posting, so it is fetched only for postings that could be US tech roles and that this database doesn't
already hold a description for; an empty description keeps the saved one (see repository.UPSERT).

Board slug: "<host>/<tenant>/<site>", e.g. "nvidia.wd5.myworkdayjobs.com/nvidia/NVIDIAExternalCareerSite".
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Optional

from ..domain import Job
from ..services.classify import is_us_location
from ..services.roles import could_be_tech_title
from .base import Source, html_to_text, to_date

PAGE = 20  # Workday's maximum page size
MAX_PAGES = 150  # 3,000 postings: a safety stop for a board that keeps paging
DETAIL_WORKERS = 3  # description requests in parallel per board; boards already run 8 at a time
US = "United States of America"
US_NAMES = {US, "United States", "USA", "US"}  # how boards name the country in their location filter


def split_slug(slug: str) -> tuple[str, str, str]:
    host, tenant, site = slug.split("/", 2)
    return host, tenant, site


def api_base(slug: str) -> str:
    host, tenant, site = split_slug(slug)
    return f"https://{host}/wday/cxs/{tenant}/{site}"


def page_base(slug: str) -> str:
    """Where people open a posting: the careers page the path is relative to."""
    host, tenant, site = split_slug(slug)
    if host.endswith(".myworkdaysite.com"):
        return f"https://{host}/recruiting/{tenant}/{site}"
    return f"https://{host}/{site}"


def posting_id(external_path: str) -> str:
    """'/job/US-CA-Santa-Clara/Software-Engineer_JR2017486-1' -> 'JR2017486-1' (the requisition id)."""
    last = external_path.rstrip("/").rsplit("/", 1)[-1]
    return last.rsplit("_", 1)[-1] if "_" in last else last


_POSTED = re.compile(r"posted\s+(today|yesterday|(\d+)\+?\s+days?\s+ago)", re.I)


def posted_date(text: str, today: Optional[date] = None) -> Optional[str]:
    """'Posted Today' / 'Posted Yesterday' / 'Posted 3 Days Ago' -> YYYY-MM-DD. '30+ Days Ago' is too vague: None."""
    m = _POSTED.search(text or "")
    if not m or "+" in (text or ""):
        return None
    today = today or date.today()
    word = m.group(1).lower()
    days = 0 if word == "today" else 1 if word == "yesterday" else int(m.group(2))
    return (today - timedelta(days=days)).isoformat()


def worth_a_description(title: str, location: str) -> bool:
    """Could this be a US tech role? Only these get the extra request for their description."""
    if not could_be_tech_title(title):
        return False
    return is_us_location(location) or bool(re.search(r"\d+\s+locations", location or "", re.I))


def find_us_facet(facets: list) -> Optional[tuple[str, str]]:
    """(facet parameter, value id) of the 'United States of America' country filter, searched through nested
    facets, or None when the board has no such filter."""
    for facet in facets or []:
        for value in facet.get("values") or []:
            if value.get("descriptor") in US_NAMES and value.get("id") and facet.get("facetParameter"):
                return facet["facetParameter"], value["id"]
            if "values" in value:  # a group of facets (e.g. locationMainGroup)
                found = find_us_facet([value])
                if found:
                    return found
    return None


class Workday(Source):
    name = "workday"

    def _list(self, slug: str) -> tuple[list[dict], bool]:
        """Every posting on the board (US only when the board can filter by country) and whether it did."""
        url = f"{api_base(slug)}/jobs"
        body = {"appliedFacets": {}, "limit": PAGE, "offset": 0, "searchText": ""}
        first = self.post(url, body)
        us = find_us_facet(first.get("facets") or [])
        if us:
            body["appliedFacets"] = {us[0]: [us[1]]}
            first = self.post(url, body)
        postings, total = list(first.get("jobPostings") or []), int(first.get("total") or 0)
        pages = min(-(-total // PAGE), MAX_PAGES)  # the total is only reliable on the first page
        with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as pool:
            for batch in pool.map(lambda n: self.post(url, {**body, "offset": n * PAGE}).get("jobPostings") or [],
                                  range(1, pages)):
                postings.extend(batch)
        return postings, bool(us)

    def _detail(self, slug: str, path: str) -> dict:
        return (self.get(f"{api_base(slug)}{path}") or {}).get("jobPostingInfo") or {}

    def fetch(self, entry: dict) -> list[Job]:
        slug, company = entry["slug"], entry["name"]
        known = entry.get("known") or {}  # ext_id -> saved location, for postings whose description is saved
        postings, us_only = self._list(slug)
        today = date.today()

        jobs: dict[str, Job] = {}
        wanted = []
        for p in postings:
            path = p.get("externalPath") or ""
            if not path:
                continue
            ext_id = posting_id(path)
            location = (p.get("locationsText") or "").strip()
            if us_only and not is_us_location(location) and not re.search(r"\d+\s+locations", location, re.I):
                location = f"{location}, United States".lstrip(", ")  # the board's own country filter says so
            title = (p.get("title") or "").strip()
            if ext_id in known:
                location = known[ext_id] or location  # the full location saved from its description request
            jobs[ext_id] = Job(
                source=self.name, board=slug, company=company, ext_id=ext_id, title=title,
                url=page_base(slug) + path, location=location, remote="remote" in location.lower(),
                posted_at=posted_date(p.get("postedOn") or "", today),
            )
            if ext_id not in known and worth_a_description(title, location):
                wanted.append((ext_id, path))

        def detail(item):
            ext_id, path = item
            try:
                return ext_id, self._detail(slug, path)
            except Exception:  # one posting failing must not fail the board; it is retried next run
                return ext_id, {}

        with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as pool:
            for ext_id, info in pool.map(detail, wanted):
                if not info:
                    continue
                job = jobs[ext_id]
                job.description = html_to_text(info.get("jobDescription"))
                job.posted_at = to_date(info.get("startDate")) or job.posted_at
                places = [info.get("location") or ""] + list(info.get("additionalLocations") or [])
                full = "; ".join(x for x in places if x)
                country = (info.get("country") or {}).get("descriptor") or ""
                if full:
                    job.location = f"{full}, United States" if country == US and not is_us_location(full) else full
                    job.remote = job.remote or "remote" in full.lower()
        return list(jobs.values())
