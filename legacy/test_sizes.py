"""Company-size pipeline: seed -> job text -> openings -> Claude -> default. Claude is always faked."""
from app.db.repository import DB
from app.domain import Job
from app.services.classify import ClaudeUnavailable, classify_all

CFG = {"size": {"small_max": 200, "mid_max": 5000, "big_openings": 3}, "claude": {"max_companies_per_run": 2}}


def job(company, ext, desc="", source="greenhouse"):
    return Job(source=source, board=company.lower(), company=company, ext_id=ext, title="Analyst",
               url=f"https://x/{company}/{ext}", description=desc)


def setup(tmp_path, jobs, seed="big:\n  - IBM\nmid: []\nsmall: []\n"):
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "company_sizes.yaml").write_text(seed)
    db = DB(tmp_path / "t.db")
    for j in jobs:
        db.record_board(j.source, j.board, [j], "2026-10-01T00:00:00+00:00")
    return db


def sizes(db):
    return {k: (r["size"], r["size_source"]) for k, r in db.company_sizes().items()}


def test_pipeline_order_and_default_without_key(tmp_path):
    db = setup(tmp_path, [job("IBM", "1"), job("Textco", "1", "We have 800 employees."), job("Mystery", "1")])
    out = classify_all(db, CFG, tmp_path, api_key=None)
    assert sizes(db) == {"ibm": ("Big", "seed"), "textco": ("Mid-size", "text"), "mystery": ("Startup/Small", "default")}
    assert out["sizes"]["no_key"] == 1


def test_many_openings_means_big(tmp_path):
    db = setup(tmp_path, [job("Huge", str(i)) for i in range(3)])
    classify_all(db, CFG, tmp_path, api_key=None)
    assert sizes(db)["huge"] == ("Big", "openings")


def test_claude_fallback_and_unknown_answer(tmp_path):
    db = setup(tmp_path, [job("Alpha", "1"), job("Beta", "1")])
    answers = {"Alpha": 10000, "Beta": None}
    calls = []

    def ask(name, key, model):
        calls.append(name)
        return answers[name]

    classify_all(db, CFG, tmp_path, api_key="k", ask=ask)
    assert sizes(db) == {"alpha": ("Big", "claude"), "beta": ("Startup/Small", "unknown")}
    classify_all(db, CFG, tmp_path, api_key="k", ask=ask)  # already asked: not paid for twice
    assert sorted(calls) == ["Alpha", "Beta"]


def test_claude_budget_and_outage(tmp_path):
    db = setup(tmp_path, [job(n, "1") for n in ("A", "B", "C")])
    calls = []

    def ask(name, key, model):
        calls.append(name)
        return 300

    out = classify_all(db, CFG, tmp_path, api_key="k", ask=ask)  # budget is 2
    assert len(calls) == 2 and out["sizes"]["default"] == 1

    def down(name, key, model):
        raise ClaudeUnavailable("no network")

    db2 = setup(tmp_path / "x" if (tmp_path / "x").mkdir() is None else tmp_path, [job("D", "1"), job("E", "1")])
    out = classify_all(db2, CFG, tmp_path / "x", api_key="k", ask=down)
    assert out["sizes"]["claude_error"] and out["sizes"]["claude_calls"] == 1  # stops after first failure
    assert all(v == ("Startup/Small", "default") for v in sizes(db2).values())  # retried next run


def test_manual_size_is_never_overwritten(tmp_path):
    db = setup(tmp_path, [job("IBM", "1")])
    classify_all(db, CFG, tmp_path)
    db.set_company_size("ibm", "IBM", "Mid-size", "manual")
    classify_all(db, CFG, tmp_path, force=True)
    assert sizes(db)["ibm"] == ("Mid-size", "manual")
