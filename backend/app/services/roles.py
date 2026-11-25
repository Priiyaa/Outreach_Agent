"""Decides whether a posting is a tech role. Precision first: a posting is kept only on clear evidence.

Evidence, strongest first:
  1. the title names a tech role (software engineer, ML engineer, data scientist ...)
  2. the department does, and the title is an engineer/developer/scientist style title
  3. the title is engineer-ish and the description names several concrete technologies
Titles that are clearly not tech (sales, recruiter, program manager ...) are dropped whatever the description says.
Anything these rules keep only on description evidence is the "uncertain" set that the LLM stage can re-read.
"""
from __future__ import annotations

import re

# Never tech, even when the description mentions code ("Software Sales Engineer", "Technical Recruiter").
_EXCLUDED_TITLE = re.compile(
    r"\b(?:sales|account\s+(?:executive|manager|director|representative)|business\s+development|customer\s+(?:success|support|service)"
    r"|support\s+(?:engineer|specialist|representative|agent)|help\s*desk|recruit\w*|sourcer|talent\s+(?:acquisition|partner)"
    r"|accountant|accounting|auditor|payroll|tax|treasury|financial\s+analyst|finance|hr|human\s+resources"
    r"|people\s+(?:partner|operations)|legal|counsel|attorney|paralegal|compliance|marketing|brand|copywriter|writer"
    r"|designer|nurse|physician|clinical|clinician|pharmac\w*|therapist|phlebotomist|teacher|tutor|instructor"
    r"|investigator|fraud|program(?:me)?\s+manager|project\s+manager|product\s+manager|operations\s+(?:manager|associate|coordinator)"
    r"|executive\s+assistant|administrative|receptionist|coordinator|technician|mechanic|machinist|welder|driver|warehouse"
    r"|retail|cashier|ai\s+training|annotat\w+|rater|subject\s+matter\s+expert|sme|it\s+support|macro|economist"
    r"|flexible\s+hours|freelance|part[\s-]time)\b",
    re.I,
)
# Engineering disciplines that are not software. Lose to a clearly software title ("Electrical Systems Software Engineer").
_NON_SOFTWARE_ENGINEER = re.compile(
    r"\b(?:mechanical|civil|electrical|chemical|industrial|manufacturing|materials?|process|structural|aerospace|propulsion"
    r"|thermal|hvac|facilities|safety|quality|environmental|petroleum|mining|controls?|mechatronics|hardware|rf|optical"
    r"|power|supply\s+chain|validation|field|systems?|fpga|asic|silicon|gnc|rtl|analog|digital|wireless|antenna)\s+(?:\w+\s+)?engineer",
    re.I,
)
_STRONG_TITLE = re.compile(
    r"\b(?:software|programmer|coder|swe|sde|sdet|member\s+of\s+technical\s+staff|technical\s+staff"
    r"|(?:web|application|app|api|backend|frontend|mobile|game|java|javascript|typescript|python|\.net|c#|c\+\+|php|ruby|golang|rust|scala|kotlin|swift|react|angular|node(?:\.js)?|sql|data|database|etl|salesforce|servicenow|apex|drupal|wordpress|sap|ai|ml)\s+developer"
    r"|machine\s+learning|ml\s+engineer|mlops|deep\s+learning|artificial\s+intelligence|ai\s+(?:engineer|scientist|researcher|research)"
    r"|ai\s*/\s*ml|gen\s*ai|generative\s+ai|agentic|llm|large\s+language\s+model|prompt\s+engineer\w*|nlp|natural\s+language"
    r"|computer\s+vision|data\s+(?:scientist|science|engineer|engineering)|analytics\s+engineer"
    r"|research\s+(?:scientist|engineer)|applied\s+(?:scientist|ai|ml)|computer\s+(?:science|engineer|scientist)"
    r"|full[\s-]?stack|back[\s-]?end|front[\s-]?end|devops|devsecops|site\s+reliability|sre|platform\s+engineer"
    r"|infrastructure\s+engineer|cloud\s+(?:and\s+\w+\s+)?(?:engineer|architect)|security\s+engineer|cyber\s*security\s+engineer|application\s+security"
    r"|appsec|firmware|embedded\s+(?:software|systems?\s+engineer|engineer)|(?:ios|android)\s+(?:engineer|developer|software)"
    r"|mobile\s+(?:engineer|software)|qa\s+engineer|quality\s+assurance\s+engineer|test\s+automation|software\s+test"
    r"|forward[\s-]deployed|build\s+(?:and\s+release\s+)?engineer|release\s+engineer)\b",
    re.I,
)
# A title that names someone who builds or analyses things; the gate for department and description evidence.
_ENGINEERISH_TITLE = re.compile(
    r"\b(?:engineer\w*|developer|scientist|researcher|research|analyst|architect|programmer|technologist|fde)\b", re.I
)

# Languages, frameworks and ML stack. A description needs at least one of these plus others to count on its own.
_CORE_TERMS = [
    "python", "java", "javascript", "typescript", "c++", "c#", "golang", "rust", "scala", "kotlin", "swift", "sql",
    "react", "angular", "vue", "node.js", "django", "flask", "fastapi", "spring", "kubernetes", "docker", "terraform",
    "pytorch", "tensorflow", "scikit-learn", "spark", "kafka", "airflow", "machine learning", "deep learning", "llms?",
    "nlp", "computer vision",
]
# Common in tech postings but also in plenty of non-tech ones; they only add to the count.
_SUPPORTING_TERMS = [
    "nosql", "postgres", "postgresql", "mysql", "mongodb", "redis", "hadoop", "dbt", "snowflake", "aws", "azure", "gcp",
    "linux", "ci/cd", "graphql", "rest apis?", "apis?", "microservices?", "data pipelines?", "etl", "distributed systems?",
    "algorithms?", "data structures", "git", "databases?", "back-?end",
]


def _alternation(terms: list[str]) -> str:
    return "|".join(sorted(terms, key=len, reverse=True)).replace("++", r"\+\+").replace(".", r"\.")


_CORE_TERM = re.compile(r"(?<![\w+#.])(?:" + _alternation(_CORE_TERMS) + r")(?![\w+#])", re.I)
_TECH_TERM = re.compile(
    r"(?<![\w+#.])(?:" + _alternation(_CORE_TERMS + _SUPPORTING_TERMS) + r")(?![\w+#])", re.I
)
MIN_TECH_TERMS = 3  # distinct technologies a description must name to carry a role on its own


def tech_terms(text: str) -> list[str]:
    """Distinct technologies named in the text, in order of first appearance (plurals count once)."""
    seen: dict[str, str] = {}
    for match in _TECH_TERM.finditer(text or ""):
        seen.setdefault(match.group(0).lower().rstrip("s"), match.group(0).lower())
    return list(seen.values())


def is_excluded_title(title: str) -> bool:
    return bool(_EXCLUDED_TITLE.search(title or ""))


def could_be_tech_title(title: str) -> bool:
    """A title that is, or could be, a tech role once the description is read. Used to decide which postings are
    worth an extra request for their description."""
    title = title or ""
    if is_excluded_title(title):
        return False
    return bool(_STRONG_TITLE.search(title) or (_ENGINEERISH_TITLE.search(title) and not _NON_SOFTWARE_ENGINEER.search(title)))


def classify_cs_role(title: str, department: str, description: str) -> tuple[bool, str]:
    """(is_tech, evidence). Evidence reads 'title: ...', 'department: ...' or 'description: python, sql, aws'."""
    title = title or ""
    if is_excluded_title(title):
        return False, ""
    strong = _STRONG_TITLE.search(title)
    if strong:
        return True, f"title: {strong.group(0)}"
    if _NON_SOFTWARE_ENGINEER.search(title) or not _ENGINEERISH_TITLE.search(title):
        return False, ""
    if match := _STRONG_TITLE.search(department or ""):
        return True, f"department: {match.group(0)}"
    terms = tech_terms(description)
    if len(terms) >= MIN_TECH_TERMS and _CORE_TERM.search(" ".join(terms)):
        return True, "description: " + ", ".join(terms[:4])
    return False, ""
