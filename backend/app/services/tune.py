"""Checks the match ranking against your own verdicts and tunes its weights.

You mark ranked jobs "good" or "bad" on the board. Agreement is measured as the share of (good, bad) pairs where the
good job scores higher (AUC: 1.0 always, 0.5 a coin flip). The tuner tries thousands of weightings of the score
parts (still adding up to 100) and keeps the one that agrees with you most, preferring small changes. With few
labels that easily overfits, so it is also checked by 5-fold cross-validation: tuned on four fifths of your labels,
scored on the fifth it never saw. A change is only recommended when that held-out agreement beats the current weights.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone

from .match import WEIGHTS, Profile, score_parts

PARTS = list(WEIGHTS)
MIN_LABELS, MIN_EACH = 20, 5  # below this, report only: too few labels to tune on
SEARCH_SIZE = 3000
FOLDS = 5
MIN_GAIN = 0.02  # held-out agreement must improve by at least this much to recommend a change
MIN_AGREEMENT = 0.6  # ...and beat a coin flip (0.5) clearly; below that the labels disagree for reasons weights can't fix


@dataclass
class Example:
    job_id: str
    title: str
    company: str
    good: bool
    parts: dict
    penalty: float  # points taken off (PhD asked, skill gap); not tuned
    reasons: list


def labeled_examples(db, profile: Profile, now: datetime | None = None) -> tuple[list[Example], int]:
    """Your labelled jobs as score parts, and how many labelled jobs the profile now hides (too senior, ...)."""
    now = now or datetime.now(timezone.utc)
    no_sponsor = frozenset(db.no_sponsorship_companies()) if profile.needs_sponsorship else frozenset()
    rows = db.query(
        "SELECT j.id, j.company, j.company_key, j.title, j.description, j.experience, j.exp_reason, j.sponsorship, "
        "j.location, j.posted_at, j.first_seen, l.label FROM match_labels l JOIN jobs j ON j.id = l.job_id "
        "WHERE l.profile = :p", p=profile.id)
    examples, hidden = [], 0
    for r in rows:
        result = score_parts(profile, r, now, no_sponsor)
        if result is None:
            hidden += 1
            continue
        parts, penalty, reasons = result
        examples.append(Example(r["id"], r["title"], r["company"], r["label"] == "good", parts, penalty, reasons))
    return examples, hidden


def raw_score(ex: Example, weights: dict) -> float:
    return sum(weights[k] * ex.parts[k] for k in PARTS) - ex.penalty


def agreement(examples: list[Example], weights: dict) -> float:
    """Share of (good, bad) pairs where the good job scores higher; ties count half. 0.5 = no better than chance."""
    goods = [raw_score(e, weights) for e in examples if e.good]
    bads = [raw_score(e, weights) for e in examples if not e.good]
    if not goods or not bads:
        return float("nan")
    wins = sum(1.0 if g > b else 0.5 if g == b else 0.0 for g in goods for b in bads)
    return wins / (len(goods) * len(bads))


def precision_at(examples: list[Example], weights: dict, k: int = 10) -> float:
    top = sorted(examples, key=lambda e: -raw_score(e, weights))[:k]
    return sum(e.good for e in top) / len(top) if top else float("nan")


def _candidates(current: dict, n: int, rng: random.Random) -> list[dict]:
    out = [dict(current)]
    for _ in range(n):
        draws = [rng.gammavariate(1.0, 1.0) for _ in PARTS]
        total = sum(draws)
        out.append({k: round(100 * d / total) for k, d in zip(PARTS, draws)})
    return out


def best_weights(examples: list[Example], current: dict, n: int = SEARCH_SIZE, seed: int = 0) -> dict:
    """The weighting that agrees most with the labels; among equals, the one closest to the current weights."""
    rng = random.Random(seed)

    def key(w):
        return (agreement(examples, w), -sum(abs(w[k] - current[k]) for k in PARTS))

    return max(_candidates(current, n, rng), key=key)


def cross_validate(examples: list[Example], current: dict, folds: int = FOLDS, seed: int = 0,
                   n: int = SEARCH_SIZE) -> tuple[float, float]:
    """(held-out agreement of the current weights, held-out agreement of weights tuned on the other folds)."""
    rng = random.Random(seed)
    goods = [e for e in examples if e.good]
    bads = [e for e in examples if not e.good]
    rng.shuffle(goods)
    rng.shuffle(bads)
    now_scores, tuned_scores = [], []
    for f in range(folds):
        test = goods[f::folds] + bads[f::folds]
        held = {id(e) for e in test}
        train = [e for e in examples if id(e) not in held]
        if not any(e.good for e in test) or not any(not e.good for e in test):
            continue
        tuned = best_weights(train, current, n, seed + f)
        now_scores.append(agreement(test, current))
        tuned_scores.append(agreement(test, tuned))
    if not now_scores:
        return float("nan"), float("nan")
    return sum(now_scores) / len(now_scores), sum(tuned_scores) / len(tuned_scores)


def evaluate(db, profile: Profile, now: datetime | None = None, search: int = SEARCH_SIZE) -> dict:
    """Everything `tune` prints: label counts, current agreement, tuned weights, held-out check, disagreements."""
    examples, hidden = labeled_examples(db, profile, now)
    current = {k: profile.weight(k) for k in PARTS}
    good = sum(e.good for e in examples)
    report = {"labels": len(examples), "good": good, "bad": len(examples) - good, "hidden": hidden,
              "current": current, "agreement": agreement(examples, current),
              "precision_at_10": precision_at(examples, current), "enough": False, "recommend": False}
    ranked = sorted(examples, key=lambda e: raw_score(e, current))
    report["good_ranked_low"] = [(round(raw_score(e, current)), e) for e in ranked if e.good][:5]
    report["bad_ranked_high"] = [(round(raw_score(e, current)), e) for e in reversed(ranked) if not e.good][:5]
    if len(examples) < MIN_LABELS or good < MIN_EACH or len(examples) - good < MIN_EACH:
        return report
    tuned = best_weights(examples, current, search)
    held_now, held_tuned = cross_validate(examples, current, n=search)
    report.update(enough=True, tuned=tuned, tuned_agreement=agreement(examples, tuned),
                  tuned_precision_at_10=precision_at(examples, tuned),
                  held_out_current=held_now, held_out_tuned=held_tuned,
                  recommend=held_tuned - held_now >= MIN_GAIN and held_tuned >= MIN_AGREEMENT and tuned != current,
                  better_than_chance=held_tuned >= MIN_AGREEMENT)
    return report
