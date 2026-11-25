from datetime import date

import pytest

from app.services.match import Profile
from app.services.resume import (
    ResumeError,
    draft_profile,
    home_location,
    pdf_text,
    skill_weights,
    years_of_experience,
)

RESUME = """Jane Doe
Austin, TX | jane@example.com
SUMMARY
Software engineer building Python services and React apps.
EXPERIENCE
Software Engineer, Acme May 2024 - Present
• Built REST APIs in Python and FastAPI on AWS
• Added Python unit tests
Research Assistant, State University Jan 2025 - Jul 2025
• Trained PyTorch models
Intern, Widgets Inc. Jun 2022 - Aug 2022
PROJECTS
Side project | React, TypeScript Jan 2019 - Dec 2019
EDUCATION
State University, M.S. Computer Science Aug 2023 - May 2025
"""
TODAY = date(2026, 11, 15)


def test_years_merge_overlaps_and_skip_education_and_projects():
    # May 2024 - Nov 2026 (31 months, the 2025 job overlaps) + Jun-Aug 2022 (3 months) = 34 months
    assert years_of_experience(RESUME, TODAY) == 2
    assert years_of_experience("EXPERIENCE\nEngineer 2015 - 2020\n", TODAY) == 6  # whole years count Jan to Dec
    assert years_of_experience("no dates here", TODAY) == 0


def test_skills_weighted_by_mentions():
    skills = skill_weights(RESUME)
    assert skills["python"] == 3 and skills["react"] == 2 and skills["fastapi"] == 1
    assert "java" not in skills  # "JavaScript" isn't Java
    assert list(skills)[0] == "python"  # heaviest first


def test_location_and_phd():
    assert home_location(RESUME) == ["austin", ", tx"]
    assert home_location("Jane\nno location") == []
    phd = draft_profile(RESUME.replace("M.S. Computer Science", "Ph.D. Computer Science"), None, TODAY)
    assert phd["has_phd"] is True and draft_profile(RESUME, None, TODAY)["has_phd"] is False


def test_draft_keeps_current_preferences():
    current = Profile(id="me", max_years_required=4, needs_sponsorship=False,
                      preferred_locations=["chicago"], role_weights={"ai": 1.0}, skills={"go": 3})
    draft = draft_profile(RESUME, current, TODAY)
    assert draft["id"] == "me" and draft["max_years_required"] == 4 and draft["needs_sponsorship"] is False
    assert draft["role_weights"] == {"ai": 1.0}
    assert draft["preferred_locations"] == ["austin", ", tx", "chicago", "remote"]
    assert "go" not in draft["skills"]  # skills come from the resume, not the old profile
    Profile(**draft)  # a valid profile as is


def test_pdf_text_rejects_non_pdfs():
    with pytest.raises(ResumeError, match="isn't a PDF"):
        pdf_text(b"hello")
    with pytest.raises(ResumeError, match="larger than 5 MB"):
        pdf_text(b"%PDF" + b"0" * (5 * 1024 * 1024))
    with pytest.raises(ResumeError):
        pdf_text(b"%PDF-1.4 broken")
