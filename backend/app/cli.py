"""CLI: python -m app.cli <fetch|classify|llm-classify|match|sample|eval|check|discover|export|stats|prune|tune|copy-db> [options]"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

from .db.repository import EXPORT_COLUMNS
from .db.session import open_db
from .db.transfer import copy_database
from .services.ats_urls import parse_ats_url
from .services.classify import classify_all
from .services.llm import get_classifier, load_env_key, run_llm_stage
from .services.match import load_active_profile, profile_to_dict, score_all
from .services.storage import RETENTION_DAYS, jobs_worth_storing, prune_database
from .services.tune import evaluate as tune_evaluate
from .services.watch import sync_watched, watched_summary, watched_targets
from .services.yc import discover as yc_discover
from .services.yc import sync_tags
from .sources import SOURCES
from .sources.base import NotFound

ROOT = Path(__file__).resolve().parent.parent

# Where fetch targets come from: your companies, boards found by `discover`, and curated lists.
CONFIG_FILES = ("companies.yaml", "companies.discovered.yaml", "companies.yc.yaml", "lists.yaml")


def load_yaml(name: str, optional: bool = False) -> dict:
    path = ROOT / "config" / name
    if optional and not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def select_targets(only_source: str | None, only_company: str | None) -> list[tuple[str, dict]]:
    targets: list[tuple[str, dict]] = []
    seen: dict[tuple[str, str], dict] = {}
    for filename in CONFIG_FILES:
        for source, entries in load_yaml(filename, optional=filename != "companies.yaml").items():
            if source not in SOURCES:
                sys.exit(f"{filename}: unknown source '{source}' (known: {', '.join(SOURCES)})")
            if only_source and source != only_source:
                continue
            for entry in entries or []:
                if only_company and only_company.lower() not in (entry["slug"].lower(), entry["name"].lower()):
                    continue
                key = (source, entry["slug"].lower())
                if key in seen:  # a board listed in two files (e.g. a YC company also in companies.yaml)
                    if entry.get("yc"):
                        seen[key].setdefault("yc", entry["yc"])
                    continue
                entry = dict(entry)
                seen[key] = entry
                targets.append((source, entry))
    return targets


def fetch_all(cfg: dict, targets: list[tuple[str, dict]]):
    """Fetch every target in parallel. Yields (source, entry, jobs, error); exactly one of jobs/error is set."""
    http = cfg["http"]
    with requests.Session() as session:
        session.headers["User-Agent"] = http["user_agent"]
        sources = {name: cls(session, http["timeout_s"]) for name, cls in SOURCES.items()}

        def work(source: str, entry: dict):
            try:
                return source, entry, sources[source].fetch(entry), None
            except NotFound:
                return source, entry, None, "404: slug not found on this ATS"
            except Exception as exc:  # one bad company must not stop the run
                return source, entry, None, f"{type(exc).__name__}: {exc}"

        with ThreadPoolExecutor(max_workers=http["workers"]) as pool:
            futures = [pool.submit(work, s, e) for s, e in targets]
            for fut in as_completed(futures):
                yield fut.result()


def with_saved_descriptions(db, targets: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """Tell each Workday board which postings already have a description saved (and their full location), so
    only new postings cost the extra request for one."""
    if not any(source == "workday" for source, _ in targets):
        return targets
    known: dict[str, dict[str, str]] = {}
    for r in db.query("SELECT board, ext_id, location FROM jobs WHERE source = 'workday' AND description != ''"):
        known.setdefault(r["board"], {})[r["ext_id"]] = r["location"]
    return [(source, {**entry, "known": known.get(entry["slug"], {})} if source == "workday" else entry)
            for source, entry in targets]


def _no_stage(text: str, ready: bool = False) -> None:
    pass


def cmd_fetch(args, cfg: dict, on_stage=_no_stage) -> None:
    """Download every board, classify, rank (the board can show results from here), then let the LLM re-check
    the uncertain jobs and re-rank if it changed anything. `on_stage(text, ready)` reports progress to the board."""
    targets = select_targets(args.source, args.company)
    if not targets:
        sys.exit("No matching companies in companies.yaml")
    db = open_db(cfg["db_path"], ROOT)
    if not args.company:  # companies you applied to are always checked, even if no config file lists them
        sync_watched(db)
        have = {(s, e["slug"].lower()) for s, e in targets}
        targets += [(s, e) for s, e in watched_targets(db)
                    if (s, e["slug"].lower()) not in have and (not args.source or s == args.source)]
    if not args.source and not args.company:
        sync_tags(db, targets)  # YC batch labels follow config/companies.yc.yaml
    targets = with_saved_descriptions(db, targets)
    run_ts = datetime.now(timezone.utc).isoformat()
    fetched = new_total = closed_total = ok_boards = done = 0
    failures = []
    started = time.monotonic()
    on_stage(f"Downloading job boards (0/{len(targets)})")
    for source, entry, jobs, error in fetch_all(cfg, targets):
        done += 1
        if done % 10 == 0 or done == len(targets):
            on_stage(f"Downloading job boards ({done}/{len(targets)})")
        if error:
            db.log(run_ts, source, entry["slug"], False, 0, error)
            failures.append((source, entry["name"], error))
            continue
        kept = jobs_worth_storing(jobs, retention_days(cfg))  # fresh possible US tech roles only
        new, closed = db.record_board(source, entry["slug"], kept, run_ts, seen=jobs)
        db.log(run_ts, source, entry["slug"], True, len(jobs), None)
        ok_boards += 1
        fetched += len(jobs)
        new_total += new
        closed_total += closed
    print(f"{fetched} jobs fetched from {ok_boards}/{len(targets)} boards: {new_total} new, {closed_total} closed "
          f"since last run ({time.monotonic() - started:.0f} s).")
    if failures:
        print(f"\n{len(failures)} boards failed (run `check` to review slugs):")
        for source, name, error in sorted(failures):
            print(f"  [{source}] {name}: {error}")
    pruned = prune_database(db, retention_days(cfg))
    print(f"Removed {pruned['deleted']} closed or older-than-{retention_days(cfg)}-day jobs you hadn't saved or applied to.")
    print_classification(db, cfg, force=False, on_stage=on_stage)


def print_classification(db, cfg: dict, force: bool, on_stage=_no_stage) -> None:
    started = time.monotonic()
    on_stage("Classifying new jobs")
    result = classify_all(db, cfg, ROOT, force=force)
    print(f"Classified {result['jobs']} jobs ({time.monotonic() - started:.0f} s).")

    # Rank now, so the board can show the new jobs while the slower LLM check runs.
    on_stage("Ranking jobs for your profile")
    print_matches(db)
    print_watched(db)
    on_stage("New jobs are on the board", ready=True)

    load_env_key(ROOT, "GEMINI_API_KEY")
    if classifier := get_classifier(cfg):  # the LLM stage runs only when a provider and key are set
        started = time.monotonic()
        on_stage(f"New jobs are on the board. Double-checking unclear roles with {classifier.model}", ready=True)
        stats = run_llm_stage(
            db, classifier, max_calls=int(cfg.get("llm", {}).get("max_calls_per_run", 500)),
            progress=lambda n, total: on_stage(f"New jobs are on the board. Double-checking unclear roles ({n}/{total})", ready=True),
        )
        print(f"LLM stage: {stats['asked']} jobs sent to {classifier.model} in {stats['requests']} requests, "
              f"{stats['from_cache']} from cache, {stats['changed']} labels changed ({time.monotonic() - started:.0f} s)"
              + (" (provider stopped answering; will resume next run)." if stats["outage"] else "."))
        if stats["changed"]:
            on_stage("Re-ranking with the double-checked roles", ready=True)
            print_matches(db)


def print_watched(db) -> None:
    """Fresh matching postings at companies you applied to."""
    profile = load_active_profile(db, ROOT)
    if profile is None:
        return
    fresh = [c for c in watched_summary(db, profile.id) if c["fresh_matches"]]
    if fresh:
        listed = ", ".join(f"{c['company']} ({c['fresh_matches']})" for c in fresh[:8])
        print(f"New matching postings this week at companies you applied to: {listed}.")


def print_matches(db, top: int = 0) -> None:
    """Re-score jobs against the active profile (saved from the board, else PROFILE_YAML / config/profile.yaml).
    Skipped when there is none."""
    profile = load_active_profile(db, ROOT)
    if profile is None:
        return
    result = score_all(db, profile)
    print(f"Matched against profile '{profile.id}': {result['scored']} jobs scored "
          f"({result['strong']} scored 70+), {result['ineligible']} hidden as not a fit (too senior, no sponsorship ...).")
    if top:
        rows = db.query(
            "SELECT m.score, m.reasons, j.company, j.title, j.location FROM job_matches m JOIN jobs j ON j.id = m.job_id "
            "WHERE m.profile = :p ORDER BY m.score DESC, j.first_seen DESC LIMIT :n", p=profile.id, n=top,
        )
        for r in rows:
            print(f"  {r['score']:>3}  {r['company']} | {r['title'][:60]} | {r['location'][:30]}\n       {r['reasons']}")


def cmd_match(args, cfg: dict) -> None:
    db = open_db(cfg["db_path"], ROOT)
    if load_active_profile(db, ROOT) is None:
        print("No profile yet: upload a resume on the board's Profile page, or copy config/profile.example.yaml "
              "to config/profile.yaml and fill it in.")
        return
    print_matches(db, top=args.top)


def cmd_classify(args, cfg: dict) -> None:
    print_classification(open_db(cfg["db_path"], ROOT), cfg, force=args.all)


def cmd_check(args, cfg: dict) -> None:
    targets = select_targets(args.source, args.company)
    rows = []
    for source, entry, jobs, error in fetch_all(cfg, targets):
        rows.append((source, entry["name"], entry["slug"], "FAIL" if error else "ok", len(jobs or []), error or ""))
    rows.sort()
    print(f"{'source':<11}{'company':<22}{'slug':<18}{'status':<7}{'jobs':>5}  note")
    for source, name, slug, status, n, note in rows:
        print(f"{source:<11}{name:<22}{slug:<18}{status:<7}{n:>5}  {note}")
    bad = sum(1 for r in rows if r[3] == "FAIL")
    print(f"\n{len(rows) - bad} ok, {bad} failing. Fix or remove the failing slugs in companies.yaml.")


def cmd_discover_yc(args, cfg: dict) -> None:
    """Find job boards of hiring YC startups and write them to config/companies.yc.yaml."""
    with requests.Session() as session:
        session.headers["User-Agent"] = cfg["http"]["user_agent"]
        known = [(s, e) for s, e in select_targets(None, None) if s != "simplify" and s != "jobright"]
        result = yc_discover(session, known, progress=lambda i, n: print(f"  checked {i}/{n} YC companies", end="\r"))
    boards = result["boards"]
    header = ("# Hiring YC startups with a public job board, found by `python -m app.cli discover-yc` from the yc-oss\n"
              "# mirror of YC's company directory. Rewritten on every run. `yc` is the batch shown on the board.\n")
    path = ROOT / "config" / "companies.yc.yaml"
    path.write_text(header + yaml.safe_dump(boards, sort_keys=True, default_flow_style=None, allow_unicode=True),
                    encoding="utf-8")
    total = sum(len(v) for v in boards.values())
    counts = ", ".join(f"{len(v)} {k}" for k, v in sorted(boards.items()))
    print(f"\n{result['companies']} hiring YC companies in the US or remote; found boards for {total} ({counts}).")
    print(f"Wrote {path.name}. The next fetch pulls their jobs and tags them YC on the board.")


def cmd_discover(args, cfg: dict) -> None:
    """Find Greenhouse/Lever/Ashby/Workday boards in saved job links that aren't in companies.yaml yet."""
    db = open_db(cfg["db_path"], ROOT)
    manual = {
        (source, e["slug"].lower())
        for source, entries in load_yaml("companies.yaml").items()
        for e in entries or []
    }
    found: dict[tuple[str, str], dict] = {}
    for row in db.query("SELECT company, url FROM jobs"):
        hit = parse_ats_url(row["url"])
        if not hit:
            continue
        source, slug, _ = hit
        key = (source, slug.lower())
        if key not in manual and key not in found:
            found[key] = {"name": row["company"] or slug, "slug": slug}
    if not found:
        print("No new Greenhouse/Lever/Ashby/Workday boards found in the saved job links.")
        return
    by_source: dict[str, list[dict]] = {}
    for (source, _), entry in sorted(found.items()):
        by_source.setdefault(source, []).append(entry)
    header = (
        "# Auto-generated by `python -m app.cli discover` from job links in the curated lists.\n"
        "# Rewritten on every run: move any entry you want to keep into companies.yaml.\n"
    )
    path = ROOT / "config" / "companies.discovered.yaml"
    path.write_text(
        header + yaml.safe_dump(by_source, sort_keys=True, default_flow_style=None, allow_unicode=True),
        encoding="utf-8",
    )
    counts = ", ".join(f"{len(v)} {k}" for k, v in sorted(by_source.items()))
    print(f"Found {len(found)} new boards ({counts}); wrote {path.name}.")
    print("Next: `check` to confirm they resolve, then `fetch` to pull their full job descriptions.")


def cmd_export(args, cfg: dict) -> None:
    db = open_db(cfg["db_path"], ROOT)
    locations = [x.strip() for x in args.location.split(",") if x.strip()] if args.location else None
    rows = db.export_rows(args.since_days, locations, args.include_closed)
    out_dir = ROOT / cfg["export_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"jobs_{datetime.now().strftime('%Y-%m-%d')}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} jobs to {path}")


def cmd_stats(args, cfg: dict) -> None:
    s = open_db(cfg["db_path"], ROOT).stats()
    print(f"Open jobs: {s['open']}   Closed: {s['closed']}   New in last 24h: {s['new_24h']}")
    print("By source: " + ", ".join(f"{k} {v}" for k, v in s["by_source"].items()))
    print("Top companies: " + ", ".join(f"{c} ({n})" for c, n in s["top_companies"]))
    print(f"Last fetch run: {s['last_run'] or 'never'}")
    for source, board, error in s["last_run_failures"]:
        print(f"  failed: [{source}] {board}: {error}")


def cmd_llm_classify(args, cfg: dict) -> None:
    """Second opinion from an LLM on the jobs the rules were unsure about. Needs llm.provider set in config.yaml."""
    load_env_key(ROOT, "GEMINI_API_KEY")
    classifier = get_classifier(cfg)
    db = open_db(cfg["db_path"], ROOT)
    if classifier is None:
        provider = cfg.get("llm", {}).get("provider", "none")
        stats = run_llm_stage(db, None)
        print(f"{stats['candidates']} jobs are uncertain and would be sent to an LLM.")
        print(f"LLM stage is off (provider: {provider}, or its API key is missing). The rule labels stand.")
        print("To turn it on: set llm.provider in config/config.yaml and GEMINI_API_KEY in backend/.env.")
        return
    budget = args.limit or int(cfg.get("llm", {}).get("max_calls_per_run", 500))
    stats = run_llm_stage(db, classifier, max_calls=budget)
    print(f"{stats['candidates']} uncertain jobs: {stats['from_cache']} answered from cache, "
          f"{stats['asked']} sent to {classifier.model} in {stats['requests']} requests, {stats['changed']} labels changed, "
          f"{stats['failed']} unusable replies.")
    if stats["outage"]:
        print(f"The provider stopped answering ({stats['reason']}). Run again later; finished work is kept.")
    if stats["changed"]:
        print_matches(db)


def cmd_sample(args, cfg: dict) -> None:
    """Write a random sample of jobs to a CSV so you can fill in human_label (1 = tech role, 0 = not)."""
    db = open_db(cfg["db_path"], ROOT)
    rows = db.query(
        "SELECT id, company, title, department, is_cs_role AS label_at_sample, cs_evidence, "
        "SUBSTR(description, 1, 400) AS description_start FROM jobs "
        "WHERE closed_at IS NULL AND is_cs_role IS NOT NULL AND is_us = 1 ORDER BY RANDOM() LIMIT :n", n=args.size,
    )
    path = ROOT / cfg.get("eval_dir", "data/eval") / "sample.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not args.force:
        sys.exit(f"{path} already exists (it may hold your labels). Use --force to replace it.")
    fields = ["id", "company", "title", "department", "label_at_sample", "cs_evidence", "description_start", "human_label"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows({**dict(r), "human_label": ""} for r in rows)
    print(f"Wrote {len(rows)} jobs to {path}. Fill the human_label column (1 = tech role, 0 = not), then run `eval`.")


def _scores(pairs: list[tuple[int, int]]) -> dict:
    tp = sum(1 for g, p in pairs if g and p)
    fp = sum(1 for g, p in pairs if not g and p)
    fn = sum(1 for g, p in pairs if g and not p)
    tn = sum(1 for g, p in pairs if not g and not p)
    return {"n": len(pairs), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None,
            "accuracy": (tp + tn) / len(pairs) if pairs else None}


def cmd_eval(args, cfg: dict) -> None:
    """Score the labels against your hand labels: as they were when sampled, and as they are now."""
    path = ROOT / cfg.get("eval_dir", "data/eval") / "sample.csv"
    if not path.exists():
        sys.exit(f"No {path}. Run `sample` first.")
    with open(path, newline="", encoding="utf-8") as f:
        labelled = [r for r in csv.DictReader(f) if r["human_label"].strip() in ("0", "1")]
    if not labelled:
        sys.exit("No rows have human_label filled in (use 1 or 0).")
    db = open_db(cfg["db_path"], ROOT)
    current = {r["id"]: int(r["is_cs_role"] or 0) for r in db.query("SELECT id, is_cs_role FROM jobs")}
    gold = {r["id"]: int(r["human_label"]) for r in labelled}
    fmt = lambda x: "n/a" if x is None else f"{x:.1%}"  # noqa: E731
    for name, pairs in (
        ("At sample time", [(gold[r["id"]], int(r["label_at_sample"] or 0)) for r in labelled]),
        ("Now", [(gold[i], current.get(i, 0)) for i in gold]),
    ):
        s = _scores(pairs)
        print(f"{name:<15} n={s['n']}  precision {fmt(s['precision'])}  recall {fmt(s['recall'])}  accuracy {fmt(s['accuracy'])}"
              f"   (tp {s['tp']}, fp {s['fp']}, fn {s['fn']}, tn {s['tn']})")
    wrong = [r for r in labelled if current.get(r["id"], 0) != gold[r["id"]]]
    if wrong:
        print(f"\n{len(wrong)} still wrong now (first 15):")
        for r in wrong[:15]:
            print(f"  human={gold[r['id']]} now={current.get(r['id'], 0)}  {r['company']}: {r['title']}")


def retention_days(cfg: dict) -> int:
    return int(cfg.get("retention", {}).get("days", RETENTION_DAYS))


def cmd_tune(args, cfg: dict) -> None:
    """Check the ranking against your good/bad labels from the board and suggest (or apply) better weights."""
    db = open_db(cfg["db_path"], ROOT)
    profile = load_active_profile(db, ROOT)
    if profile is None:
        sys.exit("No profile yet: upload a resume on the Profile page first.")
    r = tune_evaluate(db, profile)
    pct = lambda x: "n/a" if x != x else f"{x:.0%}"  # noqa: E731 (NaN check)
    print(f"Labels: {r['good']} good, {r['bad']} bad" + (f" ({r['hidden']} more are now hidden as not a fit)" if r["hidden"] else "") + ".")
    print(f"Current weights {r['current']}: agree with you on {pct(r['agreement'])} of good/bad pairs; "
          f"{pct(r['precision_at_10'])} of the top 10 labelled jobs are ones you marked good.")
    for title, rows in (("Marked good but ranked low:", r["good_ranked_low"]), ("Marked bad but ranked high:", r["bad_ranked_high"])):
        if rows:
            print(title)
            for score, e in rows:
                print(f"  {score:>3}  {e.company} | {e.title[:60]}\n       {'; '.join(e.reasons)}")
    if not r["enough"]:
        print("\nLabel at least 20 jobs (5 good and 5 bad) on the board to tune the weights.")
        return
    print(f"\nBest weights for your labels {r['tuned']}: {pct(r['tuned_agreement'])} agreement, "
          f"top-10 precision {pct(r['tuned_precision_at_10'])}.")
    print(f"Checked on labels held out of tuning: current {pct(r['held_out_current'])}, tuned {pct(r['held_out_tuned'])}.")
    if not r["better_than_chance"]:
        print("Not recommended: even tuned, the score barely beats a coin flip on unseen labels. Your good and bad jobs "
              "differ in ways the score doesn't measure; the disagreements above show which (a rule fix, not weights).")
        return
    if not r["recommend"]:
        print("Not recommended: on unseen labels the tuned weights don't do clearly better. Keeping the current ones.")
        return
    if not args.apply:
        print("Recommended. Run `python -m app.cli tune --apply` to use them.")
        return
    profile.weights = {k: float(v) for k, v in r["tuned"].items()}
    db.save_profile(profile.id, profile_to_dict(profile), datetime.now(timezone.utc).isoformat())
    result = score_all(db, profile)
    print(f"Applied and saved to the profile; re-ranked {result['scored']} jobs ({result['strong']} scored 70+).")


def cmd_prune(args, cfg: dict) -> None:
    """Delete stored jobs that are closed, older than the retention window, or (with --full) can't be US tech roles.
    Saved and applied jobs always stay."""
    db = open_db(cfg["db_path"], ROOT)
    days = retention_days(cfg)
    result = prune_database(db, days, full=args.full, dry_run=args.dry_run)
    verb = "Would delete" if args.dry_run else "Deleted"
    print(f"{verb} {result['deleted']} jobs ({result['stale']} closed or older than {days} days, "
          f"{result['irrelevant']} not possible US tech roles); {result['kept']} remain.")
    if not args.dry_run and db.engine.dialect.name == "sqlite" and args.vacuum:
        with db.engine.connect() as conn:
            conn.exec_driver_sql("VACUUM")
        print("Compacted the SQLite file.")


def cmd_copy_db(args, cfg: dict) -> None:
    """Copy the local SQLite database into another database, e.g. hosted Postgres. Run its migrations first."""
    source = f"sqlite:///{ROOT / cfg['db_path']}"
    target = args.to or os.environ.get("TARGET_DATABASE_URL")
    if not target:
        sys.exit("Give the destination with --to URL (or set TARGET_DATABASE_URL).")
    try:
        copied = copy_database(source, target, lambda t, done, total: print(f"  {t}: {done}/{total}", end="\r"))
    except RuntimeError as exc:
        sys.exit(f"\n{exc}")
    print("\nCopied and verified: " + ", ".join(f"{n} {t}" for t, n in copied.items()))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="outreach-agent")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_filters(p):
        p.add_argument("--source", choices=sorted(SOURCES), help="only this ATS")
        p.add_argument("--company", help="only this company (name or slug)")

    add_filters(sub.add_parser("fetch", help="pull jobs from every company in companies.yaml"))
    add_filters(sub.add_parser("check", help="test each slug without saving anything"))
    export = sub.add_parser("export", help="write open jobs to a CSV")
    export.add_argument("--since-days", type=int, help="only jobs first seen in the last N days")
    export.add_argument("--location", help="comma-separated substrings, e.g. 'seattle,chicago,san jose'")
    export.add_argument("--include-closed", action="store_true")
    classify = sub.add_parser("classify", help="(re)label experience, US, sponsorship and tech role")
    classify.add_argument("--all", action="store_true", help="redo every job, not just unclassified ones")
    sub.add_parser("discover", help="turn job links in saved jobs into new company boards to fetch")
    sub.add_parser("discover-yc", help="find the job boards of hiring YC startups (writes companies.yc.yaml)")
    tune = sub.add_parser("tune", help="check the ranking against your good/bad labels and tune its weights")
    tune.add_argument("--apply", action="store_true", help="save the tuned weights to your profile and re-rank")
    sub.add_parser("stats", help="show what's in the database")
    llm = sub.add_parser("llm-classify", help="LLM second opinion on jobs the rules are unsure about")
    llm.add_argument("--limit", type=int, help="max API requests this run, up to 10 postings each (default: llm.max_calls_per_run)")
    match = sub.add_parser("match", help="rank open jobs against your profile (config/profile.yaml)")
    match.add_argument("--top", type=int, default=15, help="print this many best matches")
    sample = sub.add_parser("sample", help="write a random sample of jobs to label by hand")
    sample.add_argument("--size", type=int, default=200)
    sample.add_argument("--force", action="store_true", help="replace an existing sample.csv")
    sub.add_parser("eval", help="precision and recall of the labels against your hand labels")
    copy = sub.add_parser("copy-db", help="copy the local SQLite data into another database (e.g. hosted Postgres)")
    copy.add_argument("--to", help="destination SQLAlchemy URL, e.g. postgresql+psycopg2://user:pass@host/db")
    prune = sub.add_parser("prune", help="delete closed and old jobs you haven't saved or applied to")
    prune.add_argument("--dry-run", action="store_true", help="only count what would be deleted")
    prune.add_argument("--full", action="store_true", help="also re-check every stored job against the US-tech rule")
    prune.add_argument("--vacuum", action="store_true", help="also compact the SQLite file afterwards")

    args = parser.parse_args(argv)
    cfg = load_yaml("config.yaml")
    commands = {
        "fetch": cmd_fetch, "classify": cmd_classify, "check": cmd_check, "export": cmd_export,
        "discover": cmd_discover, "discover-yc": cmd_discover_yc, "stats": cmd_stats, "llm-classify": cmd_llm_classify,
        "sample": cmd_sample, "eval": cmd_eval, "copy-db": cmd_copy_db, "match": cmd_match, "prune": cmd_prune, "tune": cmd_tune,
    }
    commands[args.command](args, cfg)


if __name__ == "__main__":
    main()
