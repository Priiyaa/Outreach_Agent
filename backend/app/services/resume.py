"""Turns an uploaded resume (PDF) into a draft match profile. Rule based and free; the draft is shown to the person to
correct before it is saved, so it only has to be a good first guess. The file itself is never stored.

What it reads:
  skills            every skill in the match vocabulary the resume names, weighted by how often it comes up
  years_experience  merged date ranges ("May 2024 - Present") outside the education section
  has_phd           a PhD / doctorate anywhere in the text
  location          "City, ST" in the header, added to the preferred locations
Everything else (sponsorship, role weights, max years asked) is kept from the current profile.
"""
from __future__ import annotations

import io
import re
from datetime import date

from .match import _SKILL_RE, Profile

MAX_RESUME_BYTES = 5 * 1024 * 1024


class ResumeError(ValueError):
    """The upload can't be read as a resume (not a PDF, no text layer ...)."""


def pdf_text(data: bytes) -> str:
    """The text of a PDF. Raises ResumeError for anything that isn't a readable, text-based PDF."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    if len(data) > MAX_RESUME_BYTES:
        raise ResumeError("The file is larger than 5 MB.")
    if not data.startswith(b"%PDF"):
        raise ResumeError("That file isn't a PDF.")
    try:
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(page.extract_text() or "" for page in reader.pages[:10])
    except (PdfReadError, ValueError, KeyError) as exc:
        raise ResumeError(f"Could not read the PDF: {exc}") from None
    if len(text.strip()) < 100:
        raise ResumeError("No text found in the PDF. Is it a scanned image? Export it from Word or Docs as a PDF instead.")
    return text


# ---- years of experience ----------------------------------------------------------------------------------

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_POINT = rf"(?:{_MONTH}\s+)?((?:19|20)\d\d)"
_RANGE = re.compile(rf"\b{_POINT}\s*(?:-|–|—|to)\s*(?:(present|current|now)|{_POINT})", re.I)
_SECTION = re.compile(r"^\s*(education|experience|work experience|professional experience|employment|projects|skills"
                      r"|technical skills|publications.*|summary|leadership.*|certifications?)\s*:?\s*$", re.I | re.M)


def _month_index(month: str | None, year: str, default: int) -> int:
    m = _MONTHS.get((month or "")[:3].lower(), default)
    return int(year) * 12 + m - 1


def _sections(text: str) -> dict[str, str]:
    """Section name (lowercased heading) -> its text. Text before the first heading is under 'header'."""
    out, name, start = {}, "header", 0
    for m in _SECTION.finditer(text):
        out[name] = out.get(name, "") + text[start:m.start()]
        name, start = m.group(1).lower(), m.end()
    out[name] = out.get(name, "") + text[start:]
    return out


def years_of_experience(text: str, today: date | None = None) -> int:
    """Whole years covered by the date ranges outside education and projects, overlaps counted once."""
    today = today or date.today()
    now = today.year * 12 + today.month - 1
    sections = _sections(text)
    body = "\n".join(v for k, v in sections.items() if k not in ("education", "projects"))
    spans = []
    for m in _RANGE.finditer(body):
        start = _month_index(m.group(1), m.group(2), 1)
        end = now if m.group(3) else _month_index(m.group(4), m.group(5), 12)
        if start <= end <= now + 1:
            spans.append((start, min(end, now)))
    months, cur_start, cur_end = 0, None, None
    for s, e in sorted(spans):
        if cur_end is None or s > cur_end + 1:
            if cur_end is not None:
                months += cur_end - cur_start + 1
            cur_start, cur_end = s, e
        else:
            cur_end = max(cur_end, e)
    if cur_end is not None:
        months += cur_end - cur_start + 1
    return months // 12


# ---- skills, PhD, location --------------------------------------------------------------------------------

def skill_weights(text: str) -> dict[str, int]:
    """Skill -> 1 (named once), 2 (twice), 3 (three times or more), heaviest first."""
    found = {}
    for name, pattern in _SKILL_RE.items():
        n = len(pattern.findall(text))
        if n:
            found[name] = 3 if n >= 3 else 2 if n == 2 else 1
    return dict(sorted(found.items(), key=lambda kv: (-kv[1], kv[0])))


_PHD = re.compile(r"\bph\.?\s?d\b|doctor\s+of\s+philosophy", re.I)
_CITY_STATE = re.compile(r"\b([A-Z][A-Za-z.]+(?:\s[A-Z][A-Za-z.]+){0,2}),\s*([A-Z]{2})\b")


def home_location(text: str) -> list[str]:
    """['chicago', ', il'] from a 'Chicago, IL' in the first lines, else []."""
    for line in text.splitlines()[:4]:
        if m := _CITY_STATE.search(line):
            return [m.group(1).lower(), f", {m.group(2).lower()}"]
    return []


def draft_profile(text: str, current: Profile | None, today: date | None = None) -> dict:
    """A profile dict built from the resume text, keeping the current profile's preferences."""
    base = current or Profile()
    sections = _sections(text)
    education = sections.get("education", "")
    if current is not None and not current.preferred_locations:
        locations: list[str] = []  # "anywhere in the US" stays that way
    else:
        locations = list(dict.fromkeys(home_location(text) + list(base.preferred_locations)))
        if "remote" not in locations:
            locations.append("remote")
    return {
        "id": base.id,
        "years_experience": years_of_experience(text, today),
        "max_years_required": base.max_years_required,
        "needs_sponsorship": base.needs_sponsorship,
        "has_phd": bool(_PHD.search(education or text)),
        "preferred_locations": locations,
        "role_weights": dict(base.role_weights),
        "skills": skill_weights(text),
        "languages": list(base.languages),
    }
