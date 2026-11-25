import random
from datetime import date

from fastapi.testclient import TestClient

from app.api.deps import active_profile_id, get_db
from app.db.repository import DB
from app.domain import Job
from app.main import app
from app.services.match import WEIGHTS, Profile, combine, score_job
from app.services.storage import prune_database
from app.services.tune import Example, agreement, best_weights, cross_validate, precision_at

CURRENT = dict(WEIGHTS)


def example(i, good, **parts):
    base = {"role": 1.0, "skills": 0.5, "seniority": 0.6, "sponsorship": 0.4, "freshness": 0.6, "location": 1.0}
    return Example(str(i), f"Job {i}", "Co", good, {**base, **parts}, False, [])


def test_score_parts_reproduce_the_old_score():
    row = {"title": "Software Engineer, New Grad", "description": "Python and React services on AWS.",
           "experience": "New grad", "exp_reason": "title", "sponsorship": "Yes", "location": "Austin, TX",
           "first_seen": "2026-11-17", "posted_at": "2026-11-17", "company_key": "x"}
    profile = Profile(skills={"python": 3, "react": 3, "aws": 3}, role_weights={"software": 1.0})
    score, reasons = score_job(profile, row)
    assert "sponsors visas" in reasons and 0 < score <= 100
    tuned = Profile(skills=profile.skills, role_weights=profile.role_weights, weights={"skills": 60, "role": 5})
    assert score_job(tuned, row)[0] != score  # profile weights take effect
    assert combine({"role": 1.0}, 15, {"role": 10}) == 0  # penalties can't push below zero


def test_tuning_finds_what_the_labels_care_about_and_beats_current_on_held_out_labels():
    rng = random.Random(3)
    examples = []
    for i in range(40):  # you care about the kind of role; skill overlap is noise that today's weights reward most
        role, skills = rng.random(), rng.random()
        examples.append(example(i, role > 0.5, role=role, skills=skills))
    assert agreement(examples, CURRENT) < 0.9
    tuned = best_weights(examples, CURRENT, n=1500)
    assert agreement(examples, tuned) > agreement(examples, CURRENT)
    # only role and skills vary here, so what matters is how much role outweighs skills
    assert tuned["role"] / max(tuned["skills"], 1) > CURRENT["role"] / CURRENT["skills"]
    assert sum(tuned.values()) in range(97, 104)
    held_now, held_tuned = cross_validate(examples, CURRENT, n=800)
    assert held_tuned > held_now
    assert precision_at(examples, tuned, 10) == 1.0


def test_random_labels_do_not_look_learnable():
    rng = random.Random(7)
    examples = [example(i, rng.random() > 0.5, skills=rng.random(), freshness=rng.random()) for i in range(30)]
    held_now, held_tuned = cross_validate(examples, CURRENT, n=800)
    assert held_tuned - held_now < 0.1  # nothing real to learn, so no big held-out gain


def test_label_api_and_labelled_jobs_survive_cleanup(tmp_path):
    db = DB(tmp_path / "t.db")
    db.record_board("greenhouse", "acme", [
        Job(source="greenhouse", board="acme", company="Acme", ext_id="1", title="Software Engineer",
            url="https://x/1", location="Chicago, IL", posted_at="2026-09-01")], "2026-09-01T00:00:00")
    (job_id,) = [r["id"] for r in db.query("SELECT id FROM jobs")]
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[active_profile_id] = lambda: "me"
    try:
        client = TestClient(app)
        assert client.put(f"/api/jobs/{job_id}/label", json={"label": "good"}).json() == {"good": 1, "bad": 0}
        assert client.get("/api/jobs", params={"cs_only": False}).json()["rows"][0]["match_label"] == "good"
        assert client.put(f"/api/jobs/{job_id}/label", json={"label": "meh"}).status_code == 422
        assert client.put("/api/jobs/nope/label", json={"label": "bad"}).status_code == 404
        assert prune_database(db, 7, today=date(2026, 11, 18))["deleted"] == 0  # old, but labelled: kept
        assert client.put(f"/api/jobs/{job_id}/label", json={"label": None}).json() == {"good": 0, "bad": 0}
    finally:
        app.dependency_overrides.clear()
    assert prune_database(db, 7, today=date(2026, 11, 18))["deleted"] == 1  # label cleared: now cleaned up


def test_no_recommendation_when_nothing_beats_chance():
    from app.services.tune import MIN_AGREEMENT
    # good and bad jobs look identical to the score: labels driven by something it doesn't measure
    examples = [example(i, i % 2 == 0) for i in range(24)]
    held_now, held_tuned = cross_validate(examples, CURRENT, n=300)
    assert held_now == held_tuned == 0.5 < MIN_AGREEMENT  # a coin flip, so evaluate() won't recommend


def test_skill_coverage_counts_core_and_nice_to_have_skills():
    from app.services.match import SKILL_GAP_PENALTY, jd_skills, skill_coverage
    jd = ("About the role\nYou will build services in Python and Java on AWS with Kubernetes.\n"
          "Requirements:\n- Experience with React and SQL\n"
          "Nice to have:\n- Kafka\n- Spark\n"
          "Bonus if you know Rust, which is a plus.\nBenefits\nHealth insurance")
    named, core = jd_skills(jd)
    assert named == {"python", "java", "aws", "kubernetes", "react", "sql", "kafka", "spark", "rust"}
    assert core == {"python", "java", "aws", "kubernetes", "react", "sql"}  # Kafka, Spark, Rust are optional
    me = Profile(skills={"python": 3, "aws": 3, "react": 2, "sql": 2, "kafka": 1}, role_weights={"software": 1.0})
    c = skill_coverage(me, jd)
    assert (c["matched"], c["named"], c["core_matched"], c["core"]) == (5, 9, 4, 6) and c["fits"]
    weak = Profile(skills={"python": 3, "kafka": 1, "spark": 1, "rust": 1, "go": 1}, role_weights={"software": 1.0})
    c = skill_coverage(weak, jd)  # 4 of 9 named, and only 1 of 6 core: penalised
    assert not c["fits"] and c["missing_core"] == ["aws", "java", "kubernetes", "react", "sql"]
    row = {"title": "Software Engineer", "description": jd, "experience": "New grad", "exp_reason": "title",
           "sponsorship": "Yes", "location": "Austin, TX", "first_seen": "2026-11-17", "company_key": "x"}
    fit, gap = score_job(me, row)[0], score_job(weak, row)
    assert "you have 4 of 9 skills it names" in gap[1] and any(r.startswith("missing core skills") for r in gap[1])
    assert skill_coverage(me, "We use Python.") is None  # too few named skills to judge: no penalty
    assert fit - gap[0] >= SKILL_GAP_PENALTY - 1


def test_level_numbers_and_spoken_languages_make_a_job_ineligible():
    from app.services.match import required_language
    me = Profile(skills={"python": 3}, role_weights={"software": 1.0, "ai": 1.0})
    base = {"description": "Python services.", "experience": "Unclear", "exp_reason": "", "sponsorship": "Unknown",
            "location": "Austin, TX", "first_seen": "2026-11-17", "company_key": "x"}
    for title in ("Full-stack Engineer 5", "AI Engineer 4 (AI Platforms)", "Software Engineer III", "SWE IV, Platform",
                  "Engineer III - MacOS Sensor", "Software Engineer, Level 3"):
        assert score_job(me, {**base, "title": title}) is None, title
    for title in ("Software Engineer II", "Software Engineer 2", "Software Engineer I", "Engineer 3D Graphics",
                  "Python 3 Developer", "Software Engineer, Web3"):
        assert score_job(me, {**base, "title": title}) is not None, title
    assert required_language("Applied AI Engineer, Spanish speaking", "", []) == "spanish"
    assert required_language("Engineer", "Requirements:\n- Fluent English and German", []) == "german"
    assert required_language("Engineer", "- German language skills are an advantage.", []) is None
    assert required_language("Engineer", "- Mandarin is a plus", []) is None
    assert required_language("Engineer", "Must be bilingual in Hindi and English", ["Hindi"]) is None  # you speak it
    assert required_language("Engineer", "We serve customers in Germany and Japan.", []) is None
    assert score_job(me, {**base, "title": "Software Engineer (Japanese bilingual)"}) is None
