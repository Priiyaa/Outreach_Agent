from __future__ import annotations

from ..domain import Job
from .base import Source, html_to_text, to_date

HOSTS = {"us": "https://api.lever.co", "eu": "https://api.eu.lever.co"}


def _description(p: dict) -> str:
    parts = [p.get("descriptionPlain") or html_to_text(p.get("description"))]
    for block in p.get("lists") or []:
        parts.append(f"{block.get('text', '')}\n{html_to_text(block.get('content'))}".strip())
    parts.append(p.get("additionalPlain") or html_to_text(p.get("additional")))
    return "\n\n".join(x for x in parts if x)


def parse(data: list, slug: str, company: str) -> list[Job]:
    if not isinstance(data, list):
        raise ValueError(f"unexpected Lever response: {str(data)[:120]}")
    jobs = []
    for p in data:
        cats = p.get("categories") or {}
        location = (cats.get("location") or "").strip()
        jobs.append(
            Job(
                source="lever",
                board=slug,
                company=company,
                ext_id=str(p["id"]),
                title=(p.get("text") or "").strip(),
                url=p.get("hostedUrl") or p.get("applyUrl") or "",
                location=location,
                department=cats.get("department") or cats.get("team") or "",
                remote=p.get("workplaceType") == "remote" or "remote" in location.lower(),
                posted_at=to_date(p.get("createdAt")),
                description=_description(p),
            )
        )
    return jobs


class Lever(Source):
    name = "lever"

    def fetch(self, entry: dict) -> list[Job]:
        host = HOSTS[entry.get("region", "us")]
        data = self.get(f"{host}/v0/postings/{entry['slug']}", params={"mode": "json"})
        return parse(data, entry["slug"], entry["name"])
