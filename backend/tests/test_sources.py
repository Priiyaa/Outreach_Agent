from app.sources import ashby, greenhouse, lever
from app.sources.base import html_to_text, to_date

GREENHOUSE = {
    "jobs": [
        {
            "id": 123,
            "title": "Data Analyst ",
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
            "location": {"name": "Chicago, IL"},
            "updated_at": "2026-10-14T10:00:00-04:00",
            "first_published": "2026-10-01T09:00:00-04:00",
            "departments": [{"name": "Operations"}],
            "content": "&lt;p&gt;Build &amp;amp; run &lt;b&gt;SQL&lt;/b&gt; pipelines.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Python&lt;/li&gt;&lt;/ul&gt;",
        }
    ]
}

LEVER = [
    {
        "id": "abc-1",
        "text": "Research Engineer",
        "hostedUrl": "https://jobs.lever.co/acme/abc-1",
        "createdAt": 1760000000000,
        "categories": {"location": "Remote - US", "team": "Research"},
        "workplaceType": "remote",
        "descriptionPlain": "Work on models.",
        "lists": [{"text": "Requirements", "content": "<li>PhD</li>"}],
        "additionalPlain": "Equal opportunity employer.",
    }
]

ASHBY = {
    "jobs": [
        {
            "id": "j1",
            "title": "Solutions Engineer",
            "location": "Seattle, WA",
            "department": "Customer",
            "isRemote": False,
            "descriptionPlain": "Help customers integrate APIs.",
            "publishedAt": "2026-10-10T12:00:00.000+00:00",
            "jobUrl": "https://jobs.ashbyhq.com/acme/j1",
        },
        {"id": "j2", "title": "Hidden role", "isListed": False, "jobUrl": "https://x"},
    ]
}


def test_greenhouse_parse():
    (job,) = greenhouse.parse(GREENHOUSE, "acme", "Acme")
    assert job.source == "greenhouse" and job.ext_id == "123"
    assert job.title == "Data Analyst"
    assert job.location == "Chicago, IL" and not job.remote
    assert job.department == "Operations"
    assert job.posted_at == "2026-10-01"
    assert "Build & run SQL pipelines." in job.description
    assert "- Python" in job.description


def test_lever_parse():
    (job,) = lever.parse(LEVER, "acme", "Acme")
    assert job.title == "Research Engineer" and job.remote
    assert job.posted_at == "2025-10-09"
    assert job.department == "Research"
    assert "Work on models." in job.description and "- PhD" in job.description
    assert job.description.endswith("Equal opportunity employer.")


def test_lever_error_payload_raises():
    try:
        lever.parse({"ok": False, "error": "Document not found"}, "acme", "Acme")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_ashby_parse_skips_unlisted():
    jobs = ashby.parse(ASHBY, "acme", "Acme")
    assert [j.ext_id for j in jobs] == ["j1"]
    assert jobs[0].location == "Seattle, WA" and jobs[0].posted_at == "2026-10-10"


def test_job_ids_are_stable_and_distinct():
    a = greenhouse.parse(GREENHOUSE, "acme", "Acme")[0]
    b = greenhouse.parse(GREENHOUSE, "acme", "Acme")[0]
    c = greenhouse.parse(GREENHOUSE, "other", "Other")[0]
    assert a.id == b.id and a.id != c.id


def test_helpers():
    assert to_date(None) is None and to_date("garbage") is None
    assert to_date("2026-10-15T01:02:03Z") == "2026-10-15"
    assert html_to_text("<p>a</p><p>b</p>") == "a\n\nb"
