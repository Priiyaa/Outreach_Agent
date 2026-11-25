"""Derived job fields: experience level, US location, internship flag, sponsorship and the tech-role label.
Everything here is rule based and free. (Company sizing was removed on 2026-11-16; see legacy/company_size.py.)
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from .roles import classify_cs_role

EXP_NEW, EXP_EXPERIENCED, EXP_UNCLEAR = "New grad", "Experienced", "Unclear"
EXPERIENCE_VALUES = [EXP_NEW, EXP_EXPERIENCED, EXP_UNCLEAR]


SPONSOR_YES, SPONSOR_NO, SPONSOR_UNKNOWN = "Yes", "No", "Unknown"

LIST_SOURCES = ("simplify", "jobright")  # curated new-grad lists

# ---- experience level ---------------------------------------------------------------------------------

_SENIOR_TITLE = re.compile(
    r"\b(senior|sr|staff(?!\s+(?:accountant|auditor|nurse|assistant|attorney|analyst))|principal"
    r"|lead(?!\s+gen)|director|head\s+of|vp|vice\s+president|architect|distinguished)\b",
    re.I,
)
# "Software Engineer III", "Full-stack Engineer 5", "SWE IV (Platform)", "Engineer, Level 3": level 3 and up is past
# early career. "Engineer II" / "Engineer 2" are not matched.
_LEVEL_SENIOR = re.compile(
    r"\s(?:III|IV|V|VI)\s*$"
    r"|\b(?:engineer|developer|scientist|programmer|analyst|sde|swe|mts)\s*,?\s*(?:level\s*)?(?:III|IV|VI?|[3-9])\b(?![.\-/]?\d)",
    re.I)
_LEVEL_JUNIOR = re.compile(r"\s(?:I|II)\s*$")  # "Software Engineer II" is still within 0-3 years
_NEW_TITLE = re.compile(
    r"\b(new\s*grad(?:uate)?s?|entry[\s-]*level|junior|jr|graduate|early\s+career|associate"
    r"|apprentice|trainee|rotational|(?:university|campus)\s+(?:grad|hire))\b",
    re.I,
)
_NEW_DESC = re.compile(
    r"\b(new\s+grad(?:uate)?s?|recent\s+graduates?|entry[\s-]level|early[\s-]career|class\s+of\s+20\d\d"
    r"|no\s+(?:prior\s+)?experience\s+(?:is\s+)?(?:required|necessary))\b",
    re.I,
)
_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:(?:-|–|—|to)\s*(\d{1,2})\s*\+?\s*)?(?:years?|yrs?)\b", re.I)
_OPTIONAL = re.compile(r"prefer|nice to have|bonus|a plus|ideally|desired|optional", re.I)


def years_required(description: str) -> int | None:
    """Lowest 'N years of experience' in the description. Required lines beat preferred ones."""
    required: list[int] = []
    preferred: list[int] = []
    for sentence in re.split(r"[\n.;•]+", description or ""):
        if "experience" not in sentence.lower():
            continue
        for match in _YEARS.finditer(sentence):
            low = int(match.group(1))
            if low <= 20:
                (preferred if _OPTIONAL.search(sentence) else required).append(low)
    pool = required or preferred
    return min(pool) if pool else None


def classify_experience(title: str, description: str, source: str) -> tuple[str, str]:
    """New grad = 0-3 years, Experienced = 3+ years. Returns (label, short reason)."""
    title = title or ""
    if match := _SENIOR_TITLE.search(title):
        return EXP_EXPERIENCED, f"title: {match.group(0)}"
    if _LEVEL_SENIOR.search(title):
        return EXP_EXPERIENCED, "title level III or higher"
    if match := _NEW_TITLE.search(title):
        return EXP_NEW, f"title: {match.group(0)}"
    if _LEVEL_JUNIOR.search(title):
        return EXP_NEW, "title level I or II"
    if source in LIST_SOURCES:
        return EXP_NEW, "from a new-grad job list"
    years = years_required(description)
    if years is not None:
        label = EXP_EXPERIENCED if years >= 3 else EXP_NEW
        return label, f"description: {years}+ years"
    if _NEW_DESC.search(description or ""):
        return EXP_NEW, "description mentions new grad / entry level"
    return EXP_UNCLEAR, ""


_INTERNSHIP = re.compile(r"\b(?:intern(?:ship)?s?|co-?op|apprentice(?:ship)?)\b", re.I)


def is_internship(title: str) -> bool:
    return bool(_INTERNSHIP.search(title or ""))


# ---- US location --------------------------------------------------------------------------------------

_STATE_ABBR = re.compile(
    r"(?<![A-Za-z])(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH"
    r"|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)(?![A-Za-z])"
)
_STATE_NAMES = re.compile(
    r"\b(?:alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|hawaii"
    r"|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota"
    r"|mississippi|missouri|montana|nebraska|nevada|new\s+hampshire|new\s+jersey|new\s+mexico|new\s+york"
    r"|north\s+carolina|north\s+dakota|ohio|oklahoma|oregon|pennsylvania|rhode\s+island|south\s+carolina"
    r"|south\s+dakota|tennessee|texas|utah|vermont|virginia|washington|west\s+virginia|wisconsin|wyoming"
    r"|district\s+of\s+columbia)\b",
    re.I,
)
_US_WORDS = re.compile(
    r"(?<![A-Za-z])(?:united\s+states|usa|u\.s\.a?|us|america|bay\s+area|nyc|sf|silicon\s+valley)(?![A-Za-z])", re.I
)
_FOREIGN_COUNTRY = re.compile(
    r"\b(?:canada|united\s+kingdom|uk|england|scotland|wales|ireland|germany|france|india|singapore|australia"
    r"|japan|israel|brazil|mexico|netherlands|poland|spain|italy|sweden|china|hong\s+kong|taiwan|korea"
    r"|ukraine|portugal|switzerland|denmark|norway|finland|uae|united\s+arab\s+emirates|argentina|colombia"
    r"|philippines|vietnam|romania|czech(?:ia)?|belgium|austria|turkey|south\s+africa|nigeria|kenya|egypt"
    r"|new\s+zealand|indonesia|malaysia|thailand|chile|serbia|bulgaria|hungary|lithuania|estonia|latvia"
    r"|greece|pakistan|bangladesh|ontario|british\s+columbia|quebec|alberta|emea|apac|latam|europe|asia"
    r"|international|costa\s+rica|iceland|croatia|kuwait|saudi\s+arabia|ksa|qatar|middle\s+east|armenia|uruguay|peru"
    r"|united\s+kingdon)\b",
    re.I,
)
_FOREIGN_CITY = re.compile(
    r"\b(?:london|toronto|vancouver|montreal|ottawa|calgary|dublin|berlin|munich|paris|amsterdam|bangalore"
    r"|bengaluru|hyderabad|mumbai|pune|delhi|gurgaon|gurugram|chennai|noida|tokyo|sydney|melbourne|tel\s+aviv"
    r"|sao\s+paulo|mexico\s+city|warsaw|madrid|barcelona|zurich|stockholm|copenhagen|seoul|shanghai|beijing"
    r"|dubai|lisbon|krakow|bucharest|prague|vienna|brussels|milan|rome|oslo|helsinki|manila|jakarta|stuttgart"
    r"|cape\s+town|manchester|budapest|pisa|trento|yerevan|montevideo|ho\s+chi\s+minh|reykjav\w*|taipei|athens|porto"
    r"|s[aã]o\s+paulo|zagreb|mississauga|riyadh|edinburgh|cambridge,\s*uk|tallinn|vilnius|belgrade|sofia|cairo|lagos"
    r"|nairobi|bogot[aá]|buenos\s+aires|santiago|lima|medell[ií]n|guadalajara|monterrey)\b",
    re.I,
)


def is_us_location(location: str) -> bool:
    """True unless the location clearly looks non-US. Blank and plain 'Remote' count as US (kept)."""
    loc = (location or "").strip()
    if not loc:
        return True
    if _STATE_NAMES.search(loc) or _US_WORDS.search(loc):
        return True
    if _FOREIGN_COUNTRY.search(loc):
        return False
    abbreviations = set(_STATE_ABBR.findall(loc))
    if abbreviations:
        # 'Bangalore, IN' is India's code, not Indiana
        return not (abbreviations == {"IN"} and _FOREIGN_CITY.search(loc))
    return not _FOREIGN_CITY.search(loc)


# ---- sponsorship --------------------------------------------------------------------------------------

_SPONSOR_NO = re.compile(
    r"(?:will|would|can|could|do|does|is|are)\s*(?:not|n't)\s+(?:be\s+able\s+to\s+)?(?:provide\s+|offer\s+|support\s+)?"
    r"(?:visa\s+|immigration\s+|employment\s+)?sponsor"
    r"|(?:unable|not\s+able|not\s+in\s+a\s+position|not\s+eligible)\s+to\s+(?:provide\s+|offer\s+)?"
    r"(?:visa\s+|immigration\s+)?sponsor"
    r"|\bno\s+(?:visa\s+|immigration\s+|h-?1b\s+)?sponsorship"
    r"|without\s+(?:the\s+need\s+for\s+)?(?:current\s+or\s+future\s+)?(?:visa\s+|immigration\s+|employer\s+)?sponsorship"
    r"(?!\s+for\s+an?\s+export)"  # Cloudflare: "... without sponsorship for an export license" is not about visas
    r"|(?:not\s+(?:offer|provide|available)|unavailable)[^.]{0,30}sponsorship"
    r"|sponsorship\s+(?:is\s+)?(?:not\s+(?:available|offered|provided)|unavailable)"
    r"|u\.?s\.?\s+citizen(?:s|ship)?\s+(?:only|required)|must\s+be\s+a\s+u\.?s\.?\s+citizen"
    r"|citizenship\s+is\s+required|\bu\.?s\.?\s+persons?\b|security\s+clearance"
    # export-control (ITAR) and citizens-only wording, e.g. SpaceX: "must be a (i) U.S. citizen or national, (ii) ..."
    r"|\bitar\b|restricted\s+to\s+(?:u\.?s\.?\s+)?citizens|citizens?\s+or\s+(?:lawful\s+)?permanent\s+residents?"
    r"|currently\s+a\s+u\.?s\.?\s+citizen|\b(?:q|ts/sci|top\s+secret|secret)\s+clearance"
    # Accenture and many others: "work authorization that does not now or in the future require sponsorship of a visa".
    # Needs the "not": the plain question "Will you now or in the future require sponsorship?" says nothing either way.
    r"|(?:not|n't)\s+(?:now\s+or\s+in\s+the\s+future|currently\s+or\s+in\s+the\s+future|now\s+or\s+later)?\s*"
    r"require\s+(?:the\s+|any\s+)?(?:current\s+or\s+future\s+)?(?:employer\s+|company\s+|visa\s+|immigration\s+|employment\s+)?"
    r"sponsorship"
    r"|without\s+(?:now\s+or\s+in\s+the\s+future\s+)?requiring\s+(?:current\s+or\s+future\s+)?(?:visa\s+|immigration\s+|employer\s+)?"
    r"sponsorship",
    re.I,
)
_SPONSOR_YES = re.compile(
    r"\bwe\s+(?:will\s+|can\s+|do\s+)?sponsor\b"
    r"|(?:will|can|may)\s+(?:be\s+able\s+to\s+)?(?:provide\s+|offer\s+)?(?:visa\s+|immigration\s+|h-?1b\s+)?sponsor"
    r"|visa\s+sponsorship\s+(?:is\s+|may\s+be\s+)?(?:available|offered|provided|supported)"
    r"|(?:offer|provide|support)s?\s+(?:visa\s+|immigration\s+)?sponsorship"
    r"|(?:open|willing)\s+to\s+sponsor"
    r"|sponsorship\s+(?:is\s+)?(?:available|offered|provided)"
    r"|h-?1b\s+(?:visa\s+)?(?:sponsorship\s+)?(?:is\s+)?(?:available|supported|offered)",
    re.I,
)
_NOTE_SPONSORSHIP = re.compile(r"Sponsorship:\s*([^;]+)")


def detect_sponsorship(description: str, notes: str = "") -> str | None:
    """'Yes' / 'No' when the job says so, else None (left as Unknown for you to fill in)."""
    if match := _NOTE_SPONSORSHIP.search(notes or ""):  # Simplify's own field
        value = match.group(1).lower()
        if "not" in value or "citizen" in value:
            return SPONSOR_NO
        if "offers" in value or value.strip() == "yes":
            return SPONSOR_YES
    text = description or ""
    if _SPONSOR_NO.search(text):  # 'no' wins over 'yes' when a posting says both
        return SPONSOR_NO
    if _SPONSOR_YES.search(text):
        return SPONSOR_YES
    return None


# ---- company key --------------------------------------------------------------------------------------

_NAME_SUFFIXES = {"inc", "llc", "ltd", "corp", "corporation", "co", "company", "plc", "lp", "llp", "gmbh", "ag", "sa", "and"}


def company_key(name: str) -> str:
    """Normalized company name used to match the same company across sources."""
    text = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower().replace("&", " and "))
    tokens = text.split()
    while len(tokens) > 1 and tokens[-1] in _NAME_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def classify_all(db, cfg: dict, root: str | Path, force: bool = False) -> dict:
    """Fill the derived columns for jobs not classified yet (all of them with force=True)."""
    updates = []
    for row in db.rows_to_classify(force):
        experience, reason = classify_experience(row["title"], row["description"], row["source"])
        is_cs, cs_evidence = classify_cs_role(row["title"], row["department"], row["description"])
        updates.append(
            {
                "id": row["id"],
                "experience": experience,
                "exp_reason": reason,
                "is_us": int(is_us_location(row["location"])),
                "is_internship": int(is_internship(row["title"])),
                "company_key": company_key(row["company"]),
                "is_cs_role": int(is_cs),
                "cs_evidence": cs_evidence,
                "sponsorship": detect_sponsorship(row["description"], row["notes"]) or SPONSOR_UNKNOWN,
            }
        )
    db.save_classification(updates, datetime.now(timezone.utc).isoformat())
    return {"jobs": len(updates)}
