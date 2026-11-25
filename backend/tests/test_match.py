from datetime import datetime, timezone

import pytest

from app.db.repository import DB
from app.domain import Job
from app.services.classify import classify_all
from app.services.match import Profile, matched_skills, role_family, score_all, score_job

NOW = datetime(2026, 11, 15, tzinfo=timezone.utc)
PROFILE = Profile(
    id="me", years_experience=2, max_years_required=3, needs_sponsorship=True,
    preferred_locations=["chicago", "remote"],
    role_weights={"ai": 1.0, "software": 1.0, "ml": 0.85, "research": 0.55, "data": 0.5, "other": 0.3},
    skills={"python": 3, "typescript": 3, "react": 3, "aws": 3, "llm": 3, "rag": 3, "go": 2},
)
AI_JD = "Build LLM agents with RAG in Python and TypeScript on AWS. React frontend. 1+ years of experience."


def row(title="Software Engineer", description=AI_JD, experience="New grad", exp_reason="", sponsorship="Unknown",
        location="Chicago, IL", first_seen="2026-11-12T00:00:00+00:00"):
    return {"title": title, "description": description, "experience": experience, "exp_reason": exp_reason,
            "sponsorship": sponsorship, "location": location, "first_seen": first_seen, "posted_at": None}


def test_role_family_from_title():
    assert role_family("Forward Deployed Engineer, New Grad") == "ai"
    assert role_family("Applied AI Engineer") == "ai"
    assert role_family("Full-Stack Engineer") == "software"
    assert role_family("Machine Learning Engineer") == "ml"
    assert role_family("Research Scientist") == "research"
    assert role_family("Data Engineer") == "data"
    assert role_family("Developer Advocate") == "other"
    assert role_family("Site Reliability Engineer") == "other"


def test_skills_are_matched_heaviest_first_and_go_needs_tech_context():
    assert matched_skills(PROFILE, AI_JD)[:3] == ["python", "typescript", "react"]
    assert "go" in matched_skills(PROFILE, "Services in Python, Go, and Rust")
    assert "go" not in matched_skills(PROFILE, "Go beyond the call of duty. Let's go!")


@pytest.mark.parametrize("change", [
    {"experience": "Experienced", "exp_reason": "title: Senior", "title": "Senior Software Engineer"},
    {"title": "Manager, Software Engineering"},
    {"description": AI_JD.replace("1+ years", "5+ years")},
    {"sponsorship": "No"},
])
def test_jobs_this_profile_cannot_get_are_not_scored(change):
    assert score_job(PROFILE, row(**change), NOW) is None


def test_a_close_fit_outranks_a_weak_one_and_says_why():
    best, reasons = score_job(PROFILE, row(title="AI Engineer, New Grad", sponsorship="Yes"), NOW)
    weak, _ = score_job(PROFILE, row(title="QA Engineer", description="Manual testing of Excel reports.",
                                     location="Austin, TX", first_seen="2026-09-01T00:00:00+00:00"), NOW)
    assert best > 80 > 40 > weak
    assert "AI/agentic role" in reasons and "sponsors visas" in reasons and "posted this week" in reasons
    assert any(r.startswith("skills: python") for r in reasons)


def test_phd_requirement_lowers_the_score_for_a_profile_without_one():
    plain, _ = score_job(PROFILE, row(), NOW)
    phd, reasons = score_job(PROFILE, row(description=AI_JD + " PhD in Computer Science required."), NOW)
    assert phd < plain and "asks for a PhD" in reasons


def test_unknown_profile_skill_is_rejected():
    with pytest.raises(ValueError, match="unknown skill"):
        Profile(skills={"cobol": 3})


def test_score_all_stores_scores_and_replaces_old_ones(tmp_path):
    (tmp_path / "config").mkdir()
    db = DB(tmp_path / "t.db")
    jobs = [Job(source="greenhouse", board="acme", company="Acme", ext_id=str(i), title=title, url=f"https://x/{i}",
                location="Chicago, IL", description=AI_JD) for i, title in enumerate(["Software Engineer", "Senior Software Engineer"])]
    db.record_board("greenhouse", "acme", jobs, "2026-11-14T00:00:00+00:00")
    classify_all(db, {"size": {}, "claude": {}}, tmp_path)
    assert score_all(db, PROFILE, NOW) == {"scored": 1, "ineligible": 1, "strong": 1}
    score_all(db, PROFILE, NOW)  # re-run replaces instead of duplicating
    assert db.scalar("SELECT COUNT(*) FROM job_matches WHERE profile = 'me'") == 1


def test_profile_comes_from_env_before_the_file(tmp_path, monkeypatch):
    from app.services.match import load_profile

    (tmp_path / "config").mkdir()
    monkeypatch.delenv("PROFILE_YAML", raising=False)
    assert load_profile(tmp_path) is None
    (tmp_path / "config" / "profile.yaml").write_text("id: file\nskills: {python: 3}\n")
    assert load_profile(tmp_path).id == "file"
    monkeypatch.setenv("PROFILE_YAML", "id: env\nskills: {react: 2}\n")
    assert load_profile(tmp_path).id == "env"


def test_blank_posting_from_a_company_that_never_sponsors_is_not_scored():
    blank = {**row(description=""), "company_key": "spacex"}
    assert score_job(PROFILE, blank, NOW, frozenset({"spacex"})) is None
    assert score_job(PROFILE, blank, NOW, frozenset({"acme"})) is not None
    says_yes = {**row(sponsorship="Yes"), "company_key": "spacex"}
    assert score_job(PROFILE, says_yes, NOW, frozenset({"spacex"})) is not None  # the posting itself wins
