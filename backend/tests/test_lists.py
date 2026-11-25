from datetime import date

from app.services.ats_urls import ats_ref_for_url, parse_ats_url
from app.sources import greenhouse
from app.sources.lists import parse_jobright, parse_simplify

SIMPLIFY = [
    {"id": "s1", "category": "Software", "company_name": "Flaky", "title": "Backend Engineer",
     "active": True, "is_visible": True, "date_posted": 1760000000, "date_updated": 1760000000,
     "url": "https://jobs.ashbyhq.com/Flaky/U-1?utm_source=Simplify", "locations": ["SF", "Remote"],
     "sponsorship": "Offers Sponsorship", "degrees": ["Bachelor's", "Master's"]},
    {"id": "s2", "company_name": "OldCo", "title": "Gone", "active": False, "is_visible": True,
     "url": "https://example.com/1", "locations": []},
    {"id": "s3", "company_name": "HiddenCo", "title": "Hidden", "active": True, "is_visible": False,
     "url": "https://example.com/2", "locations": []},
    {"id": "s4", "company_name": "NewCo", "title": "Analyst", "active": True, "is_visible": True,
     "url": "https://boards.greenhouse.io/newco/jobs/555", "locations": ["Seattle, WA"],
     "date_posted": 1760000000},
]

JOBRIGHT = """# Daily New Grad Jobs in Business Analyst

Some intro text.

| Company | Job Title | Location | Work Model | Date Posted |
| --- | --- | --- | --- | --- |
| **[SpaceX](https://www.spacex.com)** | **[Business Operations Analyst (Starlink)](https://jobright.ai/jobs/info/abc123?utm_campaign=BA&utm_source=1103)** | Hawthorne, CA | On Site | Oct 14 |
| ↳ | **[Strategy Analyst](https://jobright.ai/jobs/info/def456?utm_campaign=BA&utm_source=1103)** | Remote, US | Remote | Oct 13 |
| **[NoLink Inc](https://nolink.example)** | No link here | Austin, TX | Hybrid | Oct 12 |

Footer text.
"""


def test_parse_ats_url():
    assert parse_ats_url("https://boards.greenhouse.io/stripe/jobs/123?gh_src=x") == ("greenhouse", "stripe", "123")
    assert parse_ats_url("https://job-boards.greenhouse.io/stripe") == ("greenhouse", "stripe", None)
    assert parse_ats_url("https://boards.greenhouse.io/embed/job_app?for=acme&token=99") == ("greenhouse", "acme", "99")
    assert parse_ats_url("https://jobs.lever.co/palantir/abc-def") == ("lever", "palantir", "abc-def")
    assert parse_ats_url("https://jobs.ashbyhq.com/openai/uuid/application") == ("ashby", "openai", "uuid")
    assert parse_ats_url("https://www.example.com/careers?gh_jid=5") is None
    assert parse_ats_url("https://jobright.ai/jobs/info/abc") is None
    assert parse_ats_url("not a url") is None
    assert ats_ref_for_url("https://jobs.lever.co/Palantir/ABC") == "lever:palantir:abc"
    assert ats_ref_for_url("https://jobs.lever.co/palantir") is None


def test_direct_jobs_get_an_ats_ref():
    job = greenhouse.parse({"jobs": [{"id": 123, "title": "T", "absolute_url": "u"}]}, "Acme", "Acme")[0]
    assert job.ats_ref == "greenhouse:acme:123"


def test_parse_simplify():
    jobs = parse_simplify(SIMPLIFY, "simplify-new-grad")
    assert [j.ext_id for j in jobs] == ["s1", "s4"]  # inactive and hidden entries skipped
    first, second = jobs
    assert first.source == "simplify" and first.board == "simplify-new-grad"
    assert first.company == "Flaky" and first.department == "Software"
    assert first.location == "SF; Remote" and first.remote
    assert first.posted_at == "2025-10-09"
    assert first.notes == "Sponsorship: Offers Sponsorship; Degrees: Bachelor's, Master's"
    assert first.ats_ref == "ashby:flaky:u-1"
    assert second.ats_ref == "greenhouse:newco:555" and second.notes == "" and not second.remote


def test_parse_simplify_rejects_non_list():
    try:
        parse_simplify({"message": "rate limited"}, "x")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_parse_jobright():
    jobs = parse_jobright(JOBRIGHT, "jobright-ba", today=date(2026, 10, 15))
    assert [j.title for j in jobs] == ["Business Operations Analyst (Starlink)", "Strategy Analyst"]
    first, second = jobs
    assert first.company == "SpaceX" and second.company == "SpaceX"  # '↳' reuses the row above
    assert first.url == "https://jobright.ai/jobs/info/abc123"  # tracking params stripped
    assert first.ext_id == "abc123"
    assert first.location == "Hawthorne, CA" and not first.remote
    assert first.notes == "Work model: On Site" and first.posted_at == "2026-10-14"
    assert second.remote and second.posted_at == "2026-10-13"
    assert first.ats_ref is None


def test_jobright_year_rollover_and_column_order():
    md = (
        "| Job Title | Company | Date Posted |\n| --- | --- | --- |\n"
        "| [Analyst](https://jobright.ai/jobs/info/z9) | Acme | Dec 30 |\n"
    )
    (job,) = parse_jobright(md, "x", today=date(2027, 1, 2))
    assert job.company == "Acme" and job.posted_at == "2026-12-30"


def test_jobright_without_a_table_raises():
    try:
        parse_jobright("# Moved\nThis repo was archived.", "x")
    except ValueError:
        return
    raise AssertionError("expected ValueError")
