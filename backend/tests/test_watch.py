from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.api.deps import active_profile_id, get_db
from app.db.repository import DB
from app.domain import Job
from app.main import app
from app.services.classify import classify_all
from app.services.match import Profile, score_all
from app.services.views import apply_job_edits, query_jobs
from app.services.watch import sync_watched, watched_summary, watched_targets

NOW = datetime(2026, 11, 18, tzinfo=timezone.utc)
WD_URL = "https://acme.wd5.myworkdayjobs.com/Careers/job/US-IL-Chicago/Software-Engineer_JR9"


def make(tmp_path):
    db = DB(tmp_path / "t.db")
    db.record_board("greenhouse", "zed", [
        Job(source="greenhouse", board="zed", company="Zed", ext_id="1", title="Software Engineer",
            url="https://boards.greenhouse.io/zed/jobs/1", location="Chicago, IL", posted_at="2026-11-17"),
        Job(source="greenhouse", board="zed", company="Zed", ext_id="2", title="Backend Engineer",
            url="https://boards.greenhouse.io/zed/jobs/2", location="Chicago, IL", posted_at="2026-09-01"),
    ], "2026-11-17T00:00:00+00:00")
    db.record_board("simplify", "list", [
        Job(source="simplify", board="list", company="Acme", ext_id="a", title="Software Engineer", url=WD_URL,
            location="Chicago, IL"),
        Job(source="simplify", board="list", company="Homegrown", ext_id="h", title="Software Engineer",
            url="https://careers.homegrown.com/jobs/7", location="Austin, TX"),
    ], "2026-11-17T00:00:00+00:00")
    classify_all(db, {}, tmp_path)
    return db


def ids(db):
    return {r["title"] + "@" + r["company"]: r["id"] for r in db.query("SELECT id, title, company FROM jobs")}


def test_marking_applied_watches_the_company_and_its_board(tmp_path):
    db = make(tmp_path)
    jobs = ids(db)
    apply_job_edits(db, {jobs["Software Engineer@Zed"]: {"status": "applied"},
                         jobs["Software Engineer@Acme"]: {"status": "Applied"},  # label works too
                         jobs["Software Engineer@Homegrown"]: {"status": "saved"}})  # saved isn't applied
    rows = {r["company_key"]: (r["source"], r["board"]) for r in db.query("SELECT * FROM watched_companies")}
    assert rows == {"zed": ("greenhouse", "zed"),  # the job's own board
                    "acme": ("workday", "acme.wd5.myworkdayjobs.com/acme/Careers")}  # found through the list link
    assert sorted(t[0] for t in watched_targets(db)) == ["greenhouse", "workday"]
    assert sync_watched(db) == 0  # a re-sync adds nothing twice


def test_a_company_on_an_unreadable_site_is_kept_by_name(tmp_path):
    db = make(tmp_path)
    apply_job_edits(db, {ids(db)["Software Engineer@Homegrown"]: {"status": "applied"}})
    (row,) = db.query("SELECT * FROM watched_companies")
    assert (row["company_key"], row["board"]) == ("homegrown", "")
    assert watched_targets(db) == []  # nothing to fetch, but it is listed


def test_summary_counts_fresh_matching_postings(tmp_path):
    db = make(tmp_path)
    apply_job_edits(db, {ids(db)["Software Engineer@Zed"]: {"status": "applied"}})
    score_all(db, Profile(id="me", skills={"python": 3}, role_weights={"software": 1.0}), NOW)
    (zed,) = watched_summary(db, "me", NOW)
    assert zed["company"] == "Zed" and zed["boards"] == ["greenhouse:zed"]
    assert zed["open_matches"] == 2
    assert zed["fresh_matches"] == 0  # the fresh one is the job already applied to; the other is two months old
    db.record_board("greenhouse", "zed", [
        Job(source="greenhouse", board="zed", company="Zed", ext_id="3", title="ML Engineer",
            url="https://boards.greenhouse.io/zed/jobs/3", location="Chicago, IL", posted_at="2026-11-16")],
        "2026-11-18T00:00:00+00:00", seen=[])
    classify_all(db, {}, tmp_path)
    score_all(db, Profile(id="me", skills={"python": 3}, role_weights={"software": 1.0, "ml": 1.0}), NOW)
    assert watched_summary(db, "me", NOW)[0]["fresh_matches"] == 1


def test_api_filter_flag_and_unwatch(tmp_path):
    db = make(tmp_path)
    apply_job_edits(db, {ids(db)["Software Engineer@Zed"]: {"status": "applied"}})
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[active_profile_id] = lambda: "me"
    try:
        client = TestClient(app)
        rows = client.get("/api/jobs", params={"watched": True}).json()["rows"]
        assert {r["company"] for r in rows} == {"Zed"} and all(r["watched"] for r in rows)
        others = [r for r in client.get("/api/jobs").json()["rows"] if r["company"] != "Zed"]
        assert others and not any(r["watched"] for r in others)
        assert [c["company"] for c in client.get("/api/watched").json()] == ["Zed"]
        assert client.delete("/api/watched/zed").json() == {"saved": 1}
        assert client.get("/api/watched").json() == []
    finally:
        app.dependency_overrides.clear()
    assert query_jobs(db, watched_only=True) == []
