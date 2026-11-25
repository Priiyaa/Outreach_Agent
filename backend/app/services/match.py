"""Ranks jobs against a candidate profile (config/profile.yaml). Rule based, free, and explainable: every score is
stored with short reasons so the board can say why a job is near the top.

Two steps:
  1. eligibility: jobs this person can realistically get (tech, US, not an internship, not senior, few enough years
     required, and no "we won't sponsor" when the profile needs sponsorship). Ineligible jobs get no score.
  2. score 0-100 = role fit + skill overlap + seniority fit + sponsorship + freshness + location, minus a PhD penalty.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from .classify import _LEVEL_SENIOR, EXP_EXPERIENCED, EXP_NEW, SPONSOR_NO, SPONSOR_YES, years_required

WEIGHTS = {"role": 30, "skills": 35, "seniority": 15, "sponsorship": 8, "freshness": 7, "location": 5}
PHD_PENALTY = 15
# Skill coverage: a job is only ranked on its merits when you have more than half of the skills its description names
# AND at least half of the ones it treats as core (not "nice to have"); otherwise it loses SKILL_GAP_PENALTY points.
MIN_SKILL_COVERAGE = 0.5
MIN_CORE_COVERAGE = 0.5
MIN_JD_SKILLS = 3  # descriptions naming fewer known skills say too little to judge coverage
SKILL_GAP_PENALTY = 20
SKILL_TARGET = 18  # matched skill weight that counts as a full skills score (about 6-7 core skills)

# Role families, checked in order against the title; the first that matches wins.
_FAMILIES = [
    ("ai", r"agentic|ai\s+agents?|llm|gen\s*ai|generative|applied\s+ai|ai(?:\s*/\s*ml)?\s+(?:engineer|developer|software)"
           r"|ai\s+platform|prompt|forward[\s-]deployed|conversational\s+ai"),
    ("ml", r"machine\s+learning|\bml\b|mlops|applied\s+scientist|deep\s+learning|computer\s+vision|nlp"),
    ("software", r"software|\bswe\b|\bsde\b|full[\s-]?stack|back[\s-]?end|front[\s-]?end|web|developer(?!\s+(?:advocate|relations|evangelist))"
                 r"|member\s+of\s+technical\s+staff|(?:platform|product|application|api|cloud|mobile|ios|android)\s+engineer"),
    ("research", r"research\s+(?:engineer|scientist)|scientist|researcher"),
    ("data", r"data\s+(?:engineer|scientist|science)|analytics\s+engineer|data\s+platform"),
]
_FAMILY_RE = [(name, re.compile(rf"\b(?:{pattern})", re.I)) for name, pattern in _FAMILIES]
FAMILY_LABELS = {"ai": "AI/agentic role", "ml": "ML role", "software": "software role", "research": "research role",
                 "data": "data role", "other": "other tech role"}

# Skill vocabulary: profile skill name -> pattern searched in the description. Case-insensitive unless noted.
SKILL_PATTERNS = {
    "python": r"python", "typescript": r"typescript", "javascript": r"javascript|\bjs\b|es6",
    "c++": r"c\+\+", "sql": r"\bsql\b|postgres|mysql", "react": r"react(?:\.js)?\b", "next.js": r"next\.?js",
    "svelte": r"svelte", "node.js": r"node(?:\.js)?\b", "fastapi": r"fastapi", "rest apis": r"\brest(?:ful)?\b|\bapis?\b",
    "microservices": r"micro-?services?", "mongodb": r"mongo(?:db)?", "aws": r"\baws\b|amazon\s+web\s+services",
    "lambda": r"\blambda\b", "docker": r"docker|containers?", "ci/cd": r"ci\s*/\s*cd|continuous\s+integration|github\s+actions",
    "llm": r"\bllms?\b|large\s+language\s+models?|gpt|claude|gemini", "rag": r"\brag\b|retrieval[\s-]augmented",
    "ai agents": r"agentic|ai\s+agents?|llm\s+agents?|multi-?agent|tool[\s-](?:calling|use)|function[\s-]calling",
    "langchain": r"langchain|langgraph|llamaindex", "bedrock": r"bedrock",
    "prompt engineering": r"prompt\s+(?:engineering|design|tuning)|prompting",
    "vector search": r"vector\s+(?:db|database|store|search)|embeddings?|pinecone|opensearch|elasticsearch|pgvector",
    "machine learning": r"machine\s+learning|\bml\b", "scikit-learn": r"scikit|sklearn",
    "anomaly detection": r"anomaly\s+detection", "distributed systems": r"distributed\s+systems?",
    "testing": r"unit\s+tests?|testing|pytest|jest|cypress", "full stack": r"full[\s-]?stack",
    "java": r"\bjava\b", "kubernetes": r"kubernetes|\bk8s\b", "pytorch": r"pytorch", "tensorflow": r"tensorflow",
    "spark": r"\bspark\b", "kafka": r"kafka", "terraform": r"terraform", "gcp": r"\bgcp\b|google\s+cloud",
    "azure": r"\bazure\b", "rust": r"\brust\b", "graphql": r"graphql",
    # mostly here so coverage counts the tech a description asks for, even skills you don't list
    "c#": r"c#", ".net": r"\.net\b|dotnet", "linux": r"linux|unix", "kotlin": r"kotlin", "swift": r"\bswift(?:ui)?\b",
    "ruby": r"\bruby\b|\brails\b", "php": r"\bphp\b", "scala": r"\bscala\b", "angular": r"angular",
    "vue": r"\bvue(?:\.js)?\b", "django": r"django", "flask": r"\bflask\b", "spring": r"spring\s*(?:boot|framework)",
    "redis": r"\bredis\b", "snowflake": r"snowflake", "airflow": r"airflow", "dbt": r"\bdbt\b", "hadoop": r"hadoop",
    "html/css": r"\bhtml5?\b|\bcss3?\b", "cuda": r"\bcuda\b", "onnx": r"\bonnx\b", "openvino": r"openvino",
    "dynamodb": r"dynamo\s?db", "jenkins": r"jenkins", "tableau": r"tableau",
}
_SKILL_RE = {name: re.compile(rf"(?:{p})", re.I) for name, p in SKILL_PATTERNS.items()}
# "Go" is too common an English word for a case-insensitive search; match the language name in a tech context.
_SKILL_RE["go"] = re.compile(r"golang|\bGo\b(?=\s*(?:[,/)]|and\b|or\b|programming|language))|(?<=[,/(]\s)Go\b")
SKILL_NAMES = sorted(_SKILL_RE)

# People-management and developer-relations titles aren't early-career engineering roles.
_NOT_IC_TITLE = re.compile(r"\b(?:manager|mgr|head\s+of|director|developer\s+(?:advocate|relations|evangelist)|devrel)\b", re.I)
# Spoken languages a job may require besides English.
LANGUAGES = ["spanish", "portuguese", "french", "german", "italian", "dutch", "japanese", "korean", "mandarin",
             "cantonese", "chinese", "arabic", "hindi", "russian", "vietnamese", "hebrew", "polish", "turkish", "tagalog",
             "thai", "indonesian", "swedish", "norwegian", "danish", "finnish", "greek", "ukrainian", "bengali", "urdu",
             "punjabi", "tamil", "telugu", "marathi", "gujarati", "farsi", "persian"]
_LANG = rf"\b({'|'.join(LANGUAGES)})\b"
_LANG_TITLE = re.compile(_LANG, re.I)
_LANG_ASK = r"fluen\w*|proficien\w*|native|bilingual|speak\w*|spoken|verbal|written|language\s+skills?|conversational"
_LANG_REQUIRED = re.compile(rf"(?:{_LANG_ASK})[^.\n]{{0,60}}?{_LANG}|{_LANG}[^.\n]{{0,60}}?(?:{_LANG_ASK})", re.I)


def required_language(title: str, description: str, speaks: list[str]) -> Optional[str]:
    """A spoken language other than English (and the ones you speak) that the job asks for, else None.
    Lines that call it a plus / preferred don't count."""
    known = {s.lower() for s in speaks}
    if (m := _LANG_TITLE.search(title or "")) and m.group(1).lower() not in known:
        return m.group(1).lower()
    for line in (description or "").splitlines():
        if _OPTIONAL.search(line):
            continue
        for m in _LANG_REQUIRED.finditer(line):
            lang = next(g for g in m.groups() if g).lower()
            if lang not in known:
                return lang
    return None


_PHD = re.compile(r"\bph\.?\s?d\.?\b[^.\n]{0,40}\b(?:required|must|needed)|(?:required|must\s+have)[^.\n]{0,40}\bph\.?\s?d\b", re.I)
_PHD_TITLE = re.compile(r"\bph\.?\s?d\b", re.I)


@dataclass
class Profile:
    id: str = "me"
    years_experience: int = 0
    max_years_required: int = 2
    needs_sponsorship: bool = True
    has_phd: bool = False
    preferred_locations: list[str] = field(default_factory=list)
    role_weights: dict[str, float] = field(default_factory=dict)
    skills: dict[str, float] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)  # overrides of WEIGHTS, e.g. tuned on your labels
    languages: list[str] = field(default_factory=list)  # spoken languages besides English, e.g. ["hindi"]

    def __post_init__(self) -> None:
        unknown = sorted(set(self.skills) - set(_SKILL_RE))
        if unknown:
            raise ValueError(f"unknown skill(s) in profile: {', '.join(unknown)}. Known: {', '.join(sorted(_SKILL_RE))}")
        bad = sorted(set(self.weights) - set(WEIGHTS))
        if bad:
            raise ValueError(f"unknown weight(s) in profile: {', '.join(bad)}. Known: {', '.join(WEIGHTS)}")

    def weight(self, part: str) -> float:
        return float(self.weights.get(part, WEIGHTS[part]))


def load_profile(root: str | Path) -> Optional[Profile]:
    """The file-based profile from the PROFILE_YAML environment variable (how hosted runs get it; the file isn't committed),
    else config/profile.yaml. None when there is neither."""
    text = os.environ.get("PROFILE_YAML", "").strip()
    path = Path(root) / "config" / "profile.yaml"
    if not text and path.exists():
        text = path.read_text(encoding="utf-8")
    if not text:
        return None
    return profile_from_dict(yaml.safe_load(text) or {})


def profile_from_dict(data: dict) -> Profile:
    return Profile(**{k: v for k, v in data.items() if k in Profile.__dataclass_fields__})


def profile_to_dict(profile: Profile) -> dict:
    return {k: getattr(profile, k) for k in Profile.__dataclass_fields__}


def load_active_profile(db, root: str | Path) -> Optional[Profile]:
    """The profile saved from the board if there is one, else PROFILE_YAML / config/profile.yaml."""
    saved = db.saved_profile()
    return profile_from_dict(saved) if saved else load_profile(root)


def role_family(title: str) -> str:
    for name, pattern in _FAMILY_RE:
        if pattern.search(title or ""):
            return name
    return "other"


def matched_skills(profile: Profile, description: str) -> list[str]:
    """Profile skills named in the description, heaviest first."""
    text = description or ""
    found = [s for s in profile.skills if _SKILL_RE[s].search(text)]
    return sorted(found, key=lambda s: -profile.skills[s])


# A section heading: a short line, not a bullet, that ends in ":" or names a usual section.
_HEADING = re.compile(r"^\s*#*\s*[A-Za-z][^.!?•]{0,58}:\s*$|^\s*#*\s*(?=[^.!?•]{0,60}$)[^•\-*]*\b(?:requirements?|qualifications?"
                      r"|responsibilities|about|benefits|perks|compensation|skills|experience|education|you(?:'ll)?\s+(?:have|bring|need)"
                      r"|looking\s+for|nice[\s-]to[\s-]haves?|preferred|bonus|role|team|what\s+you|who\s+you)\b", re.I)
_OPTIONAL = re.compile(r"\b(?:preferred|nice[\s-]to[\s-]haves?|bonus(?:\s+points)?|pluses|a\s+plus|desired|desirable"
                       r"|ideally|not\s+required|optional|extra\s+credit|familiarity\s+with|advantage\w*|beneficial|helpful|an\s+asset)\b", re.I)


def jd_skills(description: str) -> tuple[set[str], set[str]]:
    """(every known skill the description names, the core ones: named somewhere other than a "preferred / nice to have /
    a plus" section or line)."""
    named, core, optional_section = set(), set(), False
    for line in (description or "").splitlines():
        if not line.strip():
            continue
        if _HEADING.match(line) and len(line.strip()) <= 60:
            optional_section = bool(_OPTIONAL.search(line))
            if optional_section:
                continue  # the heading itself
        found = {s for s, rx in _SKILL_RE.items() if rx.search(line)}
        named |= found
        if not optional_section and not _OPTIONAL.search(line):
            core |= found
    return named, core


def skill_coverage(profile: Profile, description: str) -> Optional[dict]:
    """How much of what the description asks for you have, or None when it names too few skills to tell."""
    named, core = jd_skills(description)
    if len(named) < MIN_JD_SKILLS:
        return None
    have = set(profile.skills)
    coverage = len(named & have) / len(named)
    core_coverage = len(core & have) / len(core) if core else 1.0
    return {"matched": len(named & have), "named": len(named), "coverage": coverage, "core": len(core),
            "core_matched": len(core & have), "core_coverage": core_coverage,
            "missing_core": sorted(core - have),
            "fits": coverage > MIN_SKILL_COVERAGE and core_coverage >= MIN_CORE_COVERAGE}


def _age_days(row, now: datetime) -> Optional[float]:
    for key in ("posted_at", "first_seen"):
        value = row.get(key)
        if value:
            try:
                seen = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                continue
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
            return max((now - seen).total_seconds() / 86400, 0.0)
    return None


def score_parts(profile: Profile, row, now: Optional[datetime] = None,
                no_sponsor_companies: frozenset[str] = frozenset()) -> Optional[tuple[dict[str, float], int, list[str]]]:
    """How well a job does on each part of the score, each from 0 to 1, plus penalty points (asks for a PhD the
    profile lacks, too few of the skills it names), and the reasons. None when the job isn't one this profile can get.
    `row` needs: title, description, experience, exp_reason, sponsorship, location, first_seen (posted_at optional)."""
    now = now or datetime.now(timezone.utc)
    title, description = row["title"] or "", row["description"] or ""

    # ---- eligibility
    if row["experience"] == EXP_EXPERIENCED and (row["exp_reason"] or "").startswith("title"):
        return None  # senior / staff / lead title
    if _NOT_IC_TITLE.search(title) or _LEVEL_SENIOR.search(title):
        return None  # manager / devrel, or level 3+ ("Engineer III", "Engineer 5")
    if required_language(title, description, profile.languages):
        return None  # asks for a spoken language you don't list
    years = years_required(description)
    if years is not None and years > profile.max_years_required:
        return None
    if profile.needs_sponsorship and row["sponsorship"] == SPONSOR_NO:
        return None
    if profile.needs_sponsorship and row["sponsorship"] != SPONSOR_YES and row.get("company_key") in no_sponsor_companies:
        return None  # this posting doesn't say, but the company's other postings say they don't sponsor

    parts: dict[str, float] = {}
    reasons: list[str] = []

    family = role_family(title)
    parts["role"] = profile.role_weights.get(family, profile.role_weights.get("other", 0.3))
    reasons.append(FAMILY_LABELS[family])

    skills = matched_skills(profile, description)
    parts["skills"] = min(sum(profile.skills[s] for s in skills) / SKILL_TARGET, 1.0)
    if skills:
        reasons.append("skills: " + ", ".join(skills[:6]))
    penalty = 0
    coverage = skill_coverage(profile, description)
    if coverage is not None:
        reasons.append(f"you have {coverage['matched']} of {coverage['named']} skills it names")
        if not coverage["fits"]:
            penalty += SKILL_GAP_PENALTY
            if coverage["core_coverage"] < MIN_CORE_COVERAGE:
                reasons.append("missing core skills: " + ", ".join(coverage["missing_core"][:5]))
            else:
                reasons.append("half or fewer of its skills")

    if row["experience"] == EXP_NEW and years is None:
        parts["seniority"], why = 1.0, "new-grad level"
    elif years is not None and years <= max(profile.years_experience, 1):
        parts["seniority"], why = 1.0, f"{years}+ yrs asked"
    elif years is not None:
        parts["seniority"], why = 0.6, f"{years}+ yrs asked"
    else:
        parts["seniority"], why = 0.6, "level not stated"
    reasons.append(why)

    if row["sponsorship"] == SPONSOR_YES:
        parts["sponsorship"] = 1.0
        reasons.append("sponsors visas")
    else:
        parts["sponsorship"] = 0.4 if profile.needs_sponsorship else 0.0  # unknown: most postings don't say

    age = _age_days(row, now)
    parts["freshness"] = 0.0 if age is None else 1.0 if age <= 7 else 0.6 if age <= 21 else 0.2
    if age is not None and age <= 7:
        reasons.append("posted this week")

    location = (row["location"] or "").lower()
    if not profile.preferred_locations:  # no preference: anywhere in the US is equally good
        parts["location"] = 1.0
    elif any(p.lower() in location for p in profile.preferred_locations):
        parts["location"] = 1.0
        reasons.append("preferred location")
    else:
        parts["location"] = 0.5

    if not profile.has_phd and (_PHD.search(description) or _PHD_TITLE.search(title)):
        penalty += PHD_PENALTY
        reasons.append("asks for a PhD")
    return parts, penalty, reasons


def combine(parts: dict[str, float], penalty: float, weights: dict[str, float]) -> int:
    """The 0-100 score from the parts and a weight per part, minus penalty points."""
    points = sum(weights[k] * v for k, v in parts.items()) - penalty
    return max(0, min(100, round(points)))


def score_job(profile: Profile, row, now: Optional[datetime] = None,
              no_sponsor_companies: frozenset[str] = frozenset()) -> Optional[tuple[int, list[str]]]:
    """(score 0-100, reasons) for one job, or None when the job isn't one this profile can get."""
    result = score_parts(profile, row, now, no_sponsor_companies)
    if result is None:
        return None
    parts, penalty, reasons = result
    return combine(parts, penalty, {k: profile.weight(k) for k in WEIGHTS}), reasons


def score_all(db, profile: Profile, now: Optional[datetime] = None) -> dict:
    """Score every open candidate job for the profile and replace that profile's stored scores."""
    now = now or datetime.now(timezone.utc)
    scored, skipped = [], 0
    no_sponsor = frozenset(db.no_sponsorship_companies()) if profile.needs_sponsorship else frozenset()
    for row in db.match_candidates():
        result = score_job(profile, row, now, no_sponsor)
        if result is None:
            skipped += 1
            continue
        score, reasons = result
        scored.append({"job_id": row["id"], "score": score, "reasons": "; ".join(reasons)})
    db.save_matches(profile.id, scored, now.isoformat())
    top = sum(1 for s in scored if s["score"] >= 70)
    return {"scored": len(scored), "ineligible": skipped, "strong": top}
