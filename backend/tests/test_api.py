import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.db.repository import DB
from app.domain import Job
from app.main import app
from app.services.classify import classify_all

CFG = {}


@pytest.fixture
def client(tmp_path):
    (tmp_path / "config").mkdir()
    db = DB(tmp_path / "t.db")
    db.record_board("greenhouse", "ibm", [
        Job(source="greenhouse", board="ibm", company="IBM", ext_id="1", title="Software Engineer, New Grad",
            url="https://x/1", location="Chicago, IL"),
        Job(source="greenhouse", board="ibm", company="IBM", ext_id="2", title="Senior Engineer",
            url="https://x/2", location="Chicago, IL"),
        Job(source="greenhouse", board="ibm", company="IBM", ext_id="3", title="Operations Analyst",
            url="https://x/3", location="Chicago, IL", description="Coordinate vendor schedules and budgets."),
    ], "2026-10-01T00:00:00+00:00")
    classify_all(db, CFG, tmp_path)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health_and_meta(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    meta = client.get("/api/meta").json()
    assert meta["sponsorship"] == ["Yes", "No", "Unknown"] and meta["status"]["new"] == "New"


def test_jobs_list_filters_and_stats(client):
    page = client.get("/api/jobs").json()
    assert page["stats"]["total"] == 1  # CS-only by default hides the generic and the operations titles
    assert [r["title"] for r in page["rows"]] == ["Software Engineer, New Grad"]
    everything = client.get("/api/jobs", params={"cs_only": False}).json()
    assert everything["stats"]["total"] == 3
    new_grad = client.get("/api/jobs", params={"experience": ["New grad"]}).json()
    assert [r["title"] for r in new_grad["rows"]] == ["Software Engineer, New Grad"]


def test_pagination_limits_rows_but_not_stats(client):
    page = client.get("/api/jobs", params={"cs_only": False, "limit": 1, "offset": 1}).json()
    assert len(page["rows"]) == 1 and page["stats"]["total"] == 3
    assert client.get("/api/jobs", params={"limit": 0}).status_code == 422


def test_edit_jobs_saves_and_rejects_bad_values(client):
    job = client.get("/api/jobs").json()["rows"][0]  # the only CS role
    ok = client.patch("/api/jobs", json={job["id"]: {"status": "applied", "sponsorship": "Yes"}})
    assert ok.status_code == 200 and ok.json() == {"saved": 1}
    after = next(r for r in client.get("/api/jobs", params={"status": ["applied"]}).json()["rows"])
    assert after["sponsorship"] == "Yes"
    bad = client.patch("/api/jobs", json={job["id"]: {"status": "nonsense"}})
    assert bad.status_code == 422


def test_bulk_sponsorship_applies_to_every_match(client):
    assert client.post("/api/jobs/bulk-sponsorship", json={"value": "No"}).json() == {"saved": 1}
    assert client.post("/api/jobs/bulk-sponsorship", json={"value": "Maybe"}).status_code == 422


def test_csv_export_covers_all_matches(client):
    res = client.get("/api/jobs.csv", params={"cs_only": False})
    assert res.headers["content-type"].startswith("text/csv")
    assert len(res.text.strip().splitlines()) == 4  # header + 3 jobs


def test_second_fetch_is_refused_while_one_runs(client, monkeypatch):
    from app.services.fetch_runner import fetch_runner

    monkeypatch.setattr(fetch_runner, "running", True)
    assert client.post("/api/fetch").status_code == 409


def test_writes_need_the_access_code_when_one_is_set(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "write_token", "s3cret")
    job = client.get("/api/jobs").json()["rows"][0]
    assert client.get("/api/meta").json()["writes_locked"] is True
    assert client.get("/api/jobs").status_code == 200  # reads stay open
    edit = {job["id"]: {"status": "saved"}}
    assert client.patch("/api/jobs", json=edit).status_code == 401
    assert client.patch("/api/jobs", json=edit, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.patch("/api/jobs", json=edit, headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert client.get("/api/auth/check").status_code == 401
    assert client.get("/api/auth/check", headers={"Authorization": "Bearer s3cret"}).json() == {"ok": True}
    assert client.post("/api/jobs/bulk-sponsorship", json={"value": "No"}).status_code == 401


def test_no_access_code_means_writes_are_open(client):
    assert client.get("/api/meta").json()["writes_locked"] is False
    assert client.get("/api/auth/check").status_code == 200


def test_fetch_can_be_disabled_for_hosts_that_sleep(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "allow_fetch", False)
    assert client.get("/api/meta").json()["fetch_enabled"] is False
    assert client.post("/api/fetch").status_code == 403


def test_best_match_sort_shows_only_scored_jobs_with_reasons(client):
    from app.api.deps import active_profile_id
    from app.services.match import Profile, score_all

    app.dependency_overrides[active_profile_id] = lambda: "tester"
    db = app.dependency_overrides[get_db]()
    score_all(db, Profile(id="tester", skills={"python": 3}, role_weights={"software": 1.0}))
    newest = client.get("/api/jobs").json()["rows"]
    assert newest[0]["match_score"] is not None and "software role" in newest[0]["match_reasons"]
    best = client.get("/api/jobs?sort=match").json()
    assert best["stats"]["total"] == 1 and best["rows"][0]["title"] == "Software Engineer, New Grad"
    assert client.get("/api/jobs?min_score=99").json()["stats"]["total"] == 0
    assert client.get("/api/jobs?sort=nonsense").status_code == 422


def test_profile_save_rescores_and_wins_over_file(client, monkeypatch):
    monkeypatch.setenv("PROFILE_YAML", "id: me\nskills: {python: 3}\n")
    state = client.get("/api/profile").json()
    assert state["source"] == "file" and state["profile"]["skills"] == {"python": 3} and "react" in state["known_skills"]

    body = {**state["profile"], "skills": {"react": 3, "go": 2}, "years_experience": 1}
    saved = client.put("/api/profile", json=body)
    assert saved.status_code == 200 and saved.json()["scored"] == 1
    state = client.get("/api/profile").json()
    assert state["source"] == "board" and state["profile"]["skills"] == {"react": 3, "go": 2}
    assert client.get("/api/jobs?sort=match").json()["stats"]["total"] == 1

    assert client.put("/api/profile", json={**body, "skills": {"cobol": 3}}).status_code == 422
    assert client.put("/api/profile", json={**body, "skills": {"react": 9}}).status_code == 422
    assert client.put("/api/profile", json={**body, "role_weights": {"ai": 2}}).status_code == 422


def test_resume_upload_returns_a_draft_and_saves_nothing(client, monkeypatch):
    from app.api import routes

    monkeypatch.setattr(routes, "pdf_text", lambda data: "Austin, TX\nEXPERIENCE\nEngineer 2020 - 2023\nPython, Python, Python, React")
    draft = client.post("/api/profile/resume", content=b"%PDF fake", headers={"Content-Type": "application/pdf"})
    assert draft.status_code == 200
    assert draft.json()["skills"]["python"] == 3 and draft.json()["years_experience"] == 4
    assert client.get("/api/profile").json()["source"] != "board"  # a draft isn't saved
    monkeypatch.undo()
    bad = client.post("/api/profile/resume", content=b"not a pdf")
    assert bad.status_code == 422 and "PDF" in bad.json()["detail"]
