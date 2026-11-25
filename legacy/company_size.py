"""Company sizing, removed from the app on 2026-11-16 (the board no longer shows company size).
Kept for reference; it was part of app/services/classify.py. The companies table and its saved sizes are still in
the database. Needed: company_key and the db methods company_sizes, companies_with_jobs and set_company_size
(see legacy/repository_company_methods.py), plus config/company_sizes.yaml (moved here as company_sizes.yaml)."""

SIZE_SMALL, SIZE_MID, SIZE_BIG = "Startup/Small", "Mid-size", "Big"
SIZE_VALUES = [SIZE_SMALL, SIZE_MID, SIZE_BIG]


def tier_for_employees(employees: int, small_max: int = 200, mid_max: int = 5000) -> str:
    """Under 200 = Startup/Small, 200 to 5,000 = Mid-size, over 5,000 = Big."""
    if employees < small_max:
        return SIZE_SMALL
    if employees <= mid_max:
        return SIZE_MID
    return SIZE_BIG


_EMPLOYEES = re.compile(
    r"(?<![\w,.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(\+|k\+?)?\s+(?:full[- ]time\s+)?"
    r"(?:employees|team\s+members|teammates)\b",
    re.I,
)


def employees_from_text(texts: list[str]) -> int | None:
    """Headcount stated in job descriptions ('over 10,000 employees'); the median across postings."""
    found: list[float] = []
    for text in texts:
        for match in _EMPLOYEES.finditer(text or ""):
            number = float(match.group(1).replace(",", ""))
            if (match.group(2) or "").lower().startswith("k"):
                number *= 1000
            if number >= 10:
                found.append(number)
    return int(statistics.median(found)) if found else None


def load_seed(root: str | Path) -> dict[str, str]:
    """company_sizes.yaml -> {company_key: size label}. Missing file means no seed."""
    path = Path(root) / "config" / "company_sizes.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    seed: dict[str, str] = {}
    for tier, label in (("small", SIZE_SMALL), ("mid", SIZE_MID), ("big", SIZE_BIG)):
        for name in data.get(tier) or []:
            seed[company_key(str(name))] = label
    return seed


# ---- Claude fallback for company size -----------------------------------------------------------------

API_URL = "https://api.anthropic.com/v1/messages"


class ClaudeUnavailable(Exception):
    """The request failed or the reply couldn't be read. The company is retried on the next run."""


def get_api_key(root: str | Path) -> str | None:
    """ANTHROPIC_API_KEY from the environment, or from a .env file in the project folder."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    env_file = Path(root) / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "ANTHROPIC_API_KEY" and value.strip():
                return value.strip().strip("\"'")
    return None


def ask_claude_employees(name: str, api_key: str, model: str, timeout: float = 30) -> int | None:
    """Ask Claude for the company's approximate headcount.

    Returns an int, or None when Claude says it doesn't know or isn't confident. Raises ClaudeUnavailable
    when the request fails or the reply isn't usable (so the company is asked again next time).
    """
    prompt = (
        f'How many employees does the company "{name}" have worldwide? Answer only if you actually know '
        "this company. If you don't recognize it or are unsure, say so instead of guessing. Reply with "
        'JSON only: {"employees": <approximate integer or null>, "confidence": "high" | "medium" | "low"}'
    )
    try:
        response = requests.post(
            API_URL,
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": 100, "messages": [{"role": "user", "content": prompt}]},
            timeout=timeout,
        )
        response.raise_for_status()
        text = "".join(b.get("text", "") for b in response.json().get("content", []) if b.get("type") == "text")
        data = json.loads(re.search(r"\{.*\}", text, re.S).group(0))  # type: ignore[union-attr]
    except (requests.RequestException, ValueError, AttributeError) as exc:
        raise ClaudeUnavailable(str(exc)) from exc
    employees = data.get("employees")
    confident = str(data.get("confidence", "")).lower() in ("high", "medium")
    if isinstance(employees, (int, float)) and not isinstance(employees, bool) and employees > 0 and confident:
        return int(employees)
    return None


def size_companies(db, cfg: dict, root: str | Path, api_key: str | None = None, ask=None) -> dict:
    """Give every company with open jobs a size. Order: your seed list, headcount in job text, a very large
    number of postings, then Claude, then the Startup/Small default. Hand-set sizes are never touched."""
    ask = ask or ask_claude_employees
    size_cfg = cfg.get("size", {})
    small_max = size_cfg.get("small_max", 200)
    mid_max = size_cfg.get("mid_max", 5000)
    big_openings = size_cfg.get("big_openings", 300)
    claude_cfg = cfg.get("claude", {})
    model = claude_cfg.get("model", "claude-haiku-5-5")
    budget = int(claude_cfg.get("max_companies_per_run", 200))

    seed = load_seed(root)
    existing = db.company_sizes()
    counts: Counter = Counter()
    calls = 0
    no_key = 0
    claude_error = False

    for company in db.companies_with_jobs():
        key, name = company["key"], company["name"]
        previous = existing[key]["size_source"] if key in existing else None
        if previous == "manual":
            continue
        if key in seed:
            db.set_company_size(key, name, seed[key], "seed")
            counts["seed"] += 1
            continue
        if previous in ("claude", "unknown"):  # already asked once; don't pay for it again
            continue
        employees = employees_from_text(db.descriptions_for(key))
        if employees is not None:
            db.set_company_size(key, name, tier_for_employees(employees, small_max, mid_max), "text", employees)
            counts["text"] += 1
            continue
        if company["openings"] >= big_openings:
            db.set_company_size(key, name, SIZE_BIG, "openings")
            counts["openings"] += 1
            continue
        if not api_key:
            no_key += 1
        elif calls < budget and not claude_error:
            calls += 1
            try:
                employees = ask(name, api_key, model)
            except ClaudeUnavailable:
                claude_error = True  # stop asking this run; leave as default so it's retried
            else:
                if employees is not None:
                    tier = tier_for_employees(employees, small_max, mid_max)
                    db.set_company_size(key, name, tier, "claude", employees)
                    counts["claude"] += 1
                else:
                    db.set_company_size(key, name, SIZE_SMALL, "unknown")
                    counts["unknown"] += 1
                continue
        db.set_company_size(key, name, SIZE_SMALL, "default")
        counts["default"] += 1

    return {**counts, "claude_calls": calls, "no_key": no_key, "claude_error": claude_error}




# ---- from app/services/views.py (Companies tab) ----

def company_rows(db) -> list[dict]:
    """Companies with open jobs, their size and where it came from, for the Companies tab."""
    sizes = db.company_sizes()
    open_counts = {
        r["company_key"]: r["n"]
        for r in db.query(
            f"SELECT company_key, COUNT(*) AS n FROM jobs WHERE closed_at IS NULL AND NOT {HIDDEN_DUPLICATE} "
            "GROUP BY company_key"
        )
    }
    rows = []
    for c in db.companies_with_jobs():
        s = sizes.get(c["key"])
        open_jobs = open_counts.get(c["key"], 0)
        rows.append(
            {
                "key": c["key"],
                "company": c["name"],
                "size": s["size"] if s else "Unknown",
                "size_source": s["size_source"] if s else "unsized",
                "employees": s["employees"] if s else None,
                "open_jobs": open_jobs,
            }
        )
    rows.sort(key=lambda r: (-r["open_jobs"], r["company"].lower()))
    return rows


def apply_company_edits(db, edits: dict[str, dict]) -> int:
    """edits: {company_key: {"size": "Startup/Small|Mid-size|Big"}}. A size set here is marked manual and
    is never replaced by later classification runs."""
    names = {c["key"]: c["name"] for c in db.companies_with_jobs()}
    n = 0
    for key, changes in edits.items():
        size = changes.get("size")
        if size is None:
            continue
        if size not in SIZE_VALUES:
            raise ValueError(f"invalid size: {size!r}")
        if key not in names:
            raise KeyError(f"unknown company: {key}")
        old = db.company_sizes().get(key)
        db.set_company_size(key, names[key], size, "manual", old["employees"] if old else None)
        n += 1
    return n


