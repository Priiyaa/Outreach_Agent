from __future__ import annotations

from ..domain import Job
from .base import Source, html_to_text, to_date

API = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def parse(data: dict, slug: str, company: str) -> list[Job]:
    jobs = []
    for p in data.get("jobs", []):
        if p.get("isListed") is False:
            continue
        location = (p.get("location") or "").strip()
        jobs.append(
            Job(
                source="ashby",
                board=slug,
                company=company,
                ext_id=str(p["id"]),
                title=(p.get("title") or "").strip(),
                url=p.get("jobUrl") or p.get("applyUrl") or "",
                location=location,
                department=p.get("department") or p.get("team") or "",
                remote=bool(p.get("isRemote")) or "remote" in location.lower(),
                posted_at=to_date(p.get("publishedAt")),
                description=p.get("descriptionPlain") or html_to_text(p.get("descriptionHtml")),
            )
        )
    return jobs


class Ashby(Source):
    name = "ashby"

    def fetch(self, entry: dict) -> list[Job]:
        data = self.get(API.format(slug=entry["slug"]))
        return parse(data, entry["slug"], entry["name"])
