from __future__ import annotations

from ..domain import Job
from .base import Source, html_to_text, to_date

API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


def parse(data: dict, slug: str, company: str) -> list[Job]:
    jobs = []
    for p in data.get("jobs", []):
        location = ((p.get("location") or {}).get("name") or "").strip()
        departments = ", ".join(d["name"] for d in p.get("departments") or [] if d.get("name"))
        jobs.append(
            Job(
                source="greenhouse",
                board=slug,
                company=company,
                ext_id=str(p["id"]),
                title=(p.get("title") or "").strip(),
                url=p.get("absolute_url") or "",
                location=location,
                department=departments,
                remote="remote" in location.lower(),
                posted_at=to_date(p.get("first_published") or p.get("updated_at")),
                description=html_to_text(p.get("content"), escaped=True),
            )
        )
    return jobs


class Greenhouse(Source):
    name = "greenhouse"

    def fetch(self, entry: dict) -> list[Job]:
        data = self.get(API.format(slug=entry["slug"]), params={"content": "true"})
        return parse(data, entry["slug"], entry["name"])
