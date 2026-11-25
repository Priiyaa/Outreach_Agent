"""Y Combinator startups. YC's own job board (Work at a Startup) needs a login, but many YC companies post their
jobs on Ashby, Greenhouse or Lever, which this app already reads. `discover-yc` takes the list of hiring YC
companies from the yc-oss mirror of YC's public company directory, finds each one's board by trying likely slugs
(YC slug, website name, company name), and writes them to config/companies.yc.yaml. Every fetch then pulls those
boards and tags the companies "YC <batch>" on the board.

A slug guess can occasionally land on a different company that uses the same name; the batch tag then shows on
that company's jobs. Remove such an entry from companies.yc.yaml by hand.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

from .classify import company_key

HIRING_URL = "https://yc-oss.github.io/api/companies/hiring.json"
US_REGIONS = {"America / Canada", "United States of America", "Remote", "Partly Remote"}
PROBES = (
    ("ashby", "https://api.ashbyhq.com/posting-api/job-board/{slug}"),
    ("greenhouse", "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"),
    ("lever", "https://api.lever.co/v0/postings/{slug}?mode=json&limit=1"),
)
_SEASON = {"winter": "W", "summer": "S", "fall": "F", "spring": "X"}


def short_batch(batch: str) -> str:
    """'Winter 2024' -> 'W24'. Anything else is kept as is."""
    m = re.match(r"(winter|summer|fall|spring)\s+(\d{4})", (batch or "").strip(), re.I)
    return f"{_SEASON[m.group(1).lower()]}{m.group(2)[2:]}" if m else (batch or "").strip()


def hiring_us_companies(session: requests.Session) -> list[dict]:
    """YC companies that are hiring in the US or remotely."""
    data = session.get(HIRING_URL, timeout=60).json()
    return [c for c in data if c.get("status", "Active") == "Active" and US_REGIONS & set(c.get("regions") or [])]


def slug_candidates(company: dict) -> list[str]:
    domain = urlparse(company.get("website") or "").netloc.lower().removeprefix("www.").split(".")[0]
    name = re.sub(r"[^a-z0-9]", "", (company.get("name") or "").lower())
    return list(dict.fromkeys(x for x in (company.get("slug"), domain, name) if x))


def find_board(session: requests.Session, company: dict) -> tuple[str, str] | None:
    """(source, slug) of the first board that answers with at least one job, or None."""
    for slug in slug_candidates(company):
        for source, url in PROBES:
            try:
                resp = session.get(url.format(slug=slug), timeout=15)
                if not resp.ok:
                    continue
                data = resp.json()
                if (data.get("jobs") if isinstance(data, dict) else data):
                    return source, slug
            except (requests.RequestException, ValueError):
                continue
    return None


def discover(session: requests.Session, known: list[tuple[str, dict]], workers: int = 8, progress=None) -> dict:
    """{source: [{name, slug, yc}]} for every hiring YC company with a readable board. Companies the config already
    fetches are matched by name or slug and reused rather than probed."""
    by_name = {company_key(e["name"]): (s, e["slug"]) for s, e in known}
    by_slug = {e["slug"].lower(): (s, e["slug"]) for s, e in known}
    companies = hiring_us_companies(session)
    found: dict[str, list[dict]] = {}

    def resolve(c):
        hit = by_name.get(company_key(c["name"])) or by_slug.get((c.get("slug") or "").lower())
        return c, hit or find_board(session, c)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (c, hit) in enumerate(pool.map(resolve, companies), start=1):
            if progress:
                progress(i, len(companies))
            if hit:
                found.setdefault(hit[0], []).append({"name": c["name"], "slug": hit[1], "yc": short_batch(c.get("batch"))})
    for entries in found.values():
        entries.sort(key=lambda e: e["name"].lower())
    return {"boards": found, "companies": len(companies)}


def sync_tags(db, targets: list[tuple[str, dict]]) -> int:
    """Make company_tags' "yc" rows match the YC entries among the fetch targets. Returns how many there are."""
    rows = {company_key(e["name"]): {"k": company_key(e["name"]), "d": str(e["yc"])} for _, e in targets if e.get("yc")}
    db.execute("DELETE FROM company_tags WHERE tag = 'yc'")
    if rows:
        db.execute("INSERT INTO company_tags (company_key, tag, detail) VALUES (:k, 'yc', :d)", list(rows.values()))
    return len(rows)
