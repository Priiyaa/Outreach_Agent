"""LLM stage of the classifier. The regex rules in classify.py decide the clear cases for free; this stage
re-reads only the uncertain ones (a role matched only by description wording, or a non-tech title whose
description still mentions technical work) and can overturn the rules either way.

Providers are swappable behind `Classifier`. With `llm.provider: none` (the default) nothing is sent anywhere
and the rule result stands. Answers are cached by a hash of the posting text, so a description is paid for once.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Protocol

import requests

from .roles import is_excluded_title, tech_terms

ROLE_FAMILIES = ["Software", "ML/AI", "Agentic AI", "Research", "Data", "Infra/Security", "Other tech", "Not tech"]
MIN_TECH_WORDS = 3  # a rule-negative needs this many technical terms in its description to be worth a second look
SAVE_EVERY = 20  # answers per database write during a run
MAX_DESCRIPTION_CHARS = 6000  # enough to read the responsibilities; keeps token use (and free-tier quota) low
BATCH_SIZE = 10  # postings per request: the free tier limits requests per minute, not postings
BATCH_DESCRIPTION_CHARS = 3000  # per posting inside a batch, so a 10-posting request stays around 10k tokens

PROMPT = """You classify job postings for new graduates looking for technical roles.
Decide whether the main day-to-day work of this role is technical (writing code, building or running software,
data, ML/AI, security, infrastructure, or research in those areas). Look at what the person actually does, not
just the title: a "Business Operations Analyst" who builds APIs and data pipelines IS technical; a "Solutions
Manager" who only coordinates vendors is NOT.

Answer with JSON only: {{"is_tech": true|false, "role_family": one of {families}, "reason": "max 15 words"}}.
Use "Not tech" as the role_family when is_tech is false.

Title: {title}
Department: {department}
Description:
{description}
"""


BATCH_PROMPT = """You classify job postings for new graduates looking for technical roles.
For each posting decide whether the main day-to-day work is technical (writing code, building or running software,
data, ML/AI, security, infrastructure, or research in those areas). Look at what the person actually does, not
just the title: a "Business Operations Analyst" who builds APIs and data pipelines IS technical; a "Solutions
Manager" who only coordinates vendors is NOT.

Answer with JSON only: an array with one object per posting, in order:
[{{"id": <posting number>, "is_tech": true|false, "role_family": one of {families}, "reason": "max 15 words"}}]
Use "Not tech" as the role_family when is_tech is false.

{postings}
"""


@dataclass
class Verdict:
    is_tech: bool
    role_family: str
    reason: str


Posting = tuple  # (title, department, description)


class Classifier(Protocol):
    model: str

    def classify(self, title: str, department: str, description: str) -> Verdict: ...

    # Optional: classify_batch(postings) -> list[Verdict | None] and batch_size, to send several postings per request.


class LLMUnavailable(Exception):
    """The provider could not answer (bad key, quota, network). The stage stops and retries next run."""


def text_hash(title: str, department: str, description: str) -> str:
    key = "\x1f".join((title or "", department or "", (description or "")[:MAX_DESCRIPTION_CHARS]))
    return hashlib.sha1(key.encode()).hexdigest()


def build_prompt(title: str, department: str, description: str) -> str:
    return PROMPT.format(families=json.dumps(ROLE_FAMILIES), title=title or "", department=department or "",
                         description=(description or "")[:MAX_DESCRIPTION_CHARS])


def build_batch_prompt(postings: list[Posting]) -> str:
    parts = [
        f"### Posting {i}\nTitle: {t or ''}\nDepartment: {d or ''}\nDescription:\n{(desc or '')[:BATCH_DESCRIPTION_CHARS]}"
        for i, (t, d, desc) in enumerate(postings, start=1)
    ]
    return BATCH_PROMPT.format(families=json.dumps(ROLE_FAMILIES), postings="\n\n".join(parts))


def _load_json(raw: str):
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    return json.loads(text)


def parse_batch(raw: str, n: int) -> list[Optional[Verdict]]:
    """One verdict per posting (None where the reply skipped or garbled one). Raises ValueError if the reply
    isn't a JSON array at all."""
    data = _load_json(raw)
    if not isinstance(data, list):
        raise ValueError(f"expected a JSON array: {raw[:120]!r}")
    out: list[Optional[Verdict]] = [None] * n
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("id"), int) and 1 <= item["id"] <= n:
            try:
                out[item["id"] - 1] = _verdict(item, raw)
            except ValueError:
                pass
    return out


def parse_verdict(raw: str) -> Verdict:
    """Parse the model's JSON reply. Raises ValueError on anything malformed, so bad output is never stored."""
    return _verdict(_load_json(raw), raw)


def _verdict(data, raw: str) -> Verdict:
    if not isinstance(data, dict) or not isinstance(data.get("is_tech"), bool):
        raise ValueError(f"missing boolean is_tech: {raw[:120]!r}")
    family = data.get("role_family") if data.get("role_family") in ROLE_FAMILIES else None
    if data["is_tech"]:
        family = family if family and family != "Not tech" else "Other tech"
    else:
        family = "Not tech"
    return Verdict(data["is_tech"], family, str(data.get("reason", ""))[:200])


def _daily_quota_hit(resp) -> bool:
    """A 429 for the per-day quota: retrying won't help until it resets, so stop at once."""
    return resp.status_code == 429 and "PerDay" in (getattr(resp, "text", "") or "")


class GeminiClassifier:
    """Google Gemini over plain REST (free tier via an AI Studio key). Verify the model name in config.yaml."""

    def __init__(self, api_key: str, model: str, timeout: float = 30, session: Optional[requests.Session] = None,
                 requests_per_minute: float = 0, sleep: Callable[[float], None] = time.sleep):
        self.api_key, self.model, self.timeout = api_key, model, timeout
        self.session = session or requests.Session()
        self.min_interval = 60.0 / requests_per_minute if requests_per_minute else 0.0  # free tier is rate limited
        self._sleep, self._last_call = sleep, 0.0

    def _post(self, url: str, body: dict) -> requests.Response:
        """One request, paced to the configured rate. Rate limits (429) and overload (5xx) are retried a few times
        with a growing delay, using the wait Google asks for when it says."""
        delays = (5.0, 20.0, 45.0)  # waits before the 2nd, 3rd and 4th try
        for attempt in range(len(delays) + 1):
            wait = self._last_call + self.min_interval - time.monotonic()
            if wait > 0:
                self._sleep(wait)
            self._last_call = time.monotonic()
            resp = self.session.post(url, json=body, headers={"x-goog-api-key": self.api_key}, timeout=self.timeout)
            if (resp.status_code != 429 and resp.status_code < 500) or attempt == len(delays) or _daily_quota_hit(resp):
                return resp
            hint = re.search(r"retry in ([\d.]+)s", getattr(resp, "text", "") or "")
            self._sleep(min(float(hint.group(1)) + 1 if hint else delays[attempt], 60.0))
        return resp  # pragma: no cover

    batch_size = BATCH_SIZE

    def _generate(self, prompt: str) -> str:
        """The model's text reply. LLMUnavailable stops the run; ValueError skips just this request."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        try:
            resp = self._post(url, body)
        except requests.RequestException as exc:
            raise LLMUnavailable(f"{type(exc).__name__}: {exc}") from None
        if _daily_quota_hit(resp):
            raise LLMUnavailable("HTTP 429: the free tier's daily request quota is used up (it resets daily)")
        if resp.status_code in (401, 403, 404, 429) or resp.status_code >= 500:  # key, model name or quota: stop the run
            raise LLMUnavailable(f"HTTP {resp.status_code}")
        if not resp.ok:  # this one request was refused (e.g. blocked content): skip it, keep going
            raise ValueError(f"HTTP {resp.status_code}")
        try:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, ValueError) as exc:
            raise ValueError(f"unusable reply: {exc}") from None

    def classify(self, title: str, department: str, description: str) -> Verdict:
        raw = self._generate(build_prompt(title, department, description))
        try:
            return parse_verdict(raw)
        except ValueError as exc:  # json.JSONDecodeError is a ValueError
            raise ValueError(f"unusable reply: {exc}") from None

    def classify_batch(self, postings: list[Posting]) -> list[Optional[Verdict]]:
        """Several postings in one request. None for any posting the reply left out or garbled."""
        raw = self._generate(build_batch_prompt(postings))
        try:
            return parse_batch(raw, len(postings))
        except ValueError as exc:
            raise ValueError(f"unusable reply: {exc}") from None


def get_classifier(cfg: dict, env: Optional[dict] = None) -> Optional[Classifier]:
    """The configured provider, or None when the stage is off or its key is missing."""
    llm_cfg = cfg.get("llm", {})
    provider = llm_cfg.get("provider", "none")
    env = os.environ if env is None else env
    if provider == "gemini":
        key = env.get("GEMINI_API_KEY")
        return GeminiClassifier(key, llm_cfg.get("model", "gemini-3.5-flash-lite"),
                                requests_per_minute=llm_cfg.get("requests_per_minute", 0)) if key else None
    return None


def needs_llm(row) -> bool:
    """True for the uncertain cases. A title match is trusted; so is a description with no technical wording."""
    if not (row["description"] or "").strip():
        return False
    if (row["cs_evidence"] or "").startswith("llm:"):
        return False
    if row["is_cs_role"] == 1:
        return (row["cs_evidence"] or "").startswith("description:")
    if is_excluded_title(row["title"]):
        return False
    return len(tech_terms(row["description"])) >= MIN_TECH_WORDS


def _batch_call(classifier) -> tuple[int, Callable[[list[Posting]], list[Optional[Verdict]]]]:
    """(postings per request, function) for a classifier, batching when it supports it."""
    if hasattr(classifier, "classify_batch"):
        return max(1, int(getattr(classifier, "batch_size", BATCH_SIZE))), classifier.classify_batch

    def one_by_one(postings: list[Posting]) -> list[Optional[Verdict]]:
        out = []
        for p in postings:
            try:
                out.append(classifier.classify(*p))
            except ValueError:
                out.append(None)
        return out

    return 1, one_by_one


def run_llm_stage(db, classifier: Optional[Classifier], max_calls: int = 500,
                  progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """Label the uncertain jobs. Cached answers are applied free; new ones are fetched in batches, up to
    `max_calls` requests. Identical postings (same text in several locations) are asked once.
    Returns counts. Safe to run repeatedly: finished jobs are skipped and a provider outage just stops the run."""
    rows = [r for r in db.llm_candidates() if needs_llm(r)]
    model = classifier.model if classifier else ""
    cache = db.llm_labels(model) if classifier else {}
    stats = {"candidates": len(rows), "from_cache": 0, "asked": 0, "requests": 0, "changed": 0, "failed": 0,
             "outage": False, "reason": ""}
    now = datetime.now(timezone.utc).isoformat()
    updates, fresh = [], {}

    def flush() -> None:  # paid answers are saved as they come, so a crash or Ctrl-C loses at most one batch
        if fresh:
            db.save_llm_labels([{"hash": h, "model": model, "created_at": now, **v} for h, v in fresh.items()])
            cache.update(fresh)
            fresh.clear()
        db.apply_llm_labels(updates)
        updates.clear()

    def apply(row, label: dict) -> None:
        stats["changed"] += int(label["is_tech"]) != int(row["is_cs_role"] or 0)
        updates.append({"id": row["id"], "is_cs_role": label["is_tech"], "role_family": label["role_family"],
                        "cs_evidence": f"llm: {label['reason']}"[:200]})

    todo: dict[str, list] = {}  # text hash -> jobs with that text
    for row in rows:
        h = text_hash(row["title"], row["department"], row["description"])
        if h in cache:
            stats["from_cache"] += 1
            apply(row, cache[h])
        else:
            todo.setdefault(h, []).append(row)

    if classifier is not None and todo:
        size, call = _batch_call(classifier)
        hashes = list(todo)
        for start in range(0, len(hashes), size):
            if stats["requests"] >= max_calls:
                break
            chunk = hashes[start:start + size]
            stats["requests"] += 1
            postings = [(todo[h][0]["title"], todo[h][0]["department"], todo[h][0]["description"]) for h in chunk]
            try:
                verdicts = call(postings)
            except LLMUnavailable as exc:
                stats["outage"], stats["reason"] = True, str(exc)
                break
            except ValueError:
                stats["failed"] += len(chunk)
                continue
            for h, verdict in zip(chunk, verdicts):
                stats["asked"] += 1
                if verdict is None:
                    stats["failed"] += 1
                    continue
                label = {"is_tech": int(verdict.is_tech), "role_family": verdict.role_family, "reason": verdict.reason}
                fresh[h] = label
                for row in todo[h]:
                    apply(row, label)
            if progress:
                progress(min(start + size, len(hashes)), len(hashes))
            if len(fresh) >= SAVE_EVERY:
                flush()
    flush()
    return stats


def load_env_key(root: Path, name: str) -> None:
    """Make NAME from backend/.env visible to get_classifier without overriding a real environment variable."""
    env_file = root / ".env"
    if name in os.environ or not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{name}="):
            os.environ[name] = line.split("=", 1)[1].strip().strip("'\"")
