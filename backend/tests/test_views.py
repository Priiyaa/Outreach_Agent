from app.db.repository import DB
from app.domain import Job
from app.services.classify import classify_all
from app.services.views import (
    apply_job_edits,
    jobs_to_csv,
    query_jobs,
)

CFG = {}


def mk(tmp_path):
    (tmp_path / "config").mkdir(exist_ok=True)
    db = DB(tmp_path / "t.db")
    jobs = [
        Job(source="greenhouse", board="ibm", company="IBM", ext_id="1", title="Software Engineer, New Grad",
            url="https://x/1", location="Chicago, IL"),
        Job(source="greenhouse", board="ibm", company="IBM", ext_id="2", title="Senior Engineer",
            url="https://x/2", location="Remote", description="No visa sponsorship."),
        Job(source="lever", board="midco", company="Midco", ext_id="3", title="Data Analyst",
            url="https://x/3", location="London, UK"),
        Job(source="lever", board="midco", company="Midco", ext_id="4", title="Data Intern",
            url="https://x/4", location="Seattle, WA"),
        Job(source="lever", board="midco", company="Midco", ext_id="5", title="Junior Analyst",
            url="https://x/5", location="Seattle, WA"),
    ]
    for j in jobs:
        db.record_board(j.source, j.board, [j], "2026-10-01T00:00:00+00:00")
    classify_all(db, CFG, tmp_path)
    return db


def titles(rows):
    return sorted(r["title"] for r in rows)


def test_defaults_hide_non_us_and_internships(tmp_path):
    db = mk(tmp_path)
    assert titles(query_jobs(db)) == ["Junior Analyst", "Senior Engineer", "Software Engineer, New Grad"]
    assert titles(query_jobs(db, cs_related_only=True)) == ["Software Engineer, New Grad"]
    assert "Data Intern" in titles(query_jobs(db, include_internships=True))
    assert "Data Analyst" in titles(query_jobs(db, us_only=False))


def test_cs_related_filter_matches_computing_roles(tmp_path):
    db = mk(tmp_path)
    db.record_board("greenhouse", "ibm", [
        Job(source="greenhouse", board="ibm", company="IBM", ext_id="6", title="Machine Learning Engineer",
            url="https://x/6", location="Chicago, IL"),
        Job(source="greenhouse", board="ibm", company="IBM", ext_id="7", title="Business Operations Analyst",
            url="https://x/7", location="Chicago, IL",
            description="Build internal APIs and automate data pipelines using Python."),
        Job(source="greenhouse", board="ibm", company="IBM", ext_id="8", title="Operations Analyst",
            url="https://x/8", location="Chicago, IL",
            description="Coordinate vendor schedules, budgets, and quarterly business reviews."),
    ], "2026-10-01T00:00:00+00:00")
    classify_all(db, CFG, tmp_path)  # CS-role labels are stored at classification time, not computed per query
    assert titles(query_jobs(db, cs_related_only=True)) == [
        "Business Operations Analyst", "Machine Learning Engineer", "Software Engineer, New Grad",
    ]
    hidden = next(row for row in query_jobs(db, cs_related_only=True) if row["title"] == "Business Operations Analyst")
    assert hidden["cs_role_evidence"].startswith("description:")


def test_filters_combine(tmp_path):
    db = mk(tmp_path)
    assert titles(query_jobs(db, experience=["New grad"], source=["greenhouse"])) == ["Software Engineer, New Grad"]
    assert titles(query_jobs(db, source=["lever"])) == ["Junior Analyst"]
    assert titles(query_jobs(db, sponsorship=["No"])) == ["Senior Engineer"]
    assert titles(query_jobs(db, search="ibm engineer")) == ["Senior Engineer", "Software Engineer, New Grad"]
    assert titles(query_jobs(db, location="seattle")) == ["Junior Analyst"]
    assert titles(query_jobs(db, experience=[])) == titles(query_jobs(db))  # empty selection = no filter
    try:
        query_jobs(db, bogus=["x"])
        raise AssertionError("expected TypeError")
    except TypeError:
        pass


def test_sponsorship_edit_is_per_job_and_survives_refetch_and_reclassify(tmp_path):
    db = mk(tmp_path)
    rows = {r["title"]: r for r in query_jobs(db)}
    ng, sr = rows["Software Engineer, New Grad"], rows["Senior Engineer"]
    assert apply_job_edits(db, {ng["id"]: {"sponsorship": "Yes", "sponsorship_note": "recruiter said so"}}) == 1
    # re-fetch the same job (changed description forces re-classification) and force reclassify
    db.record_board("greenhouse", "ibm", [
        Job(source="greenhouse", board="ibm", company="IBM", ext_id="1", title="Software Engineer, New Grad",
            url="https://x/1", location="Chicago, IL", description="We do not sponsor visas."),
        Job(source="greenhouse", board="ibm", company="IBM", ext_id="2", title="Senior Engineer",
            url="https://x/2", location="Remote", description="No visa sponsorship."),
    ], "2026-10-02T00:00:00+00:00")
    classify_all(db, CFG, tmp_path)
    classify_all(db, CFG, tmp_path, force=True)
    after = {r["title"]: r for r in query_jobs(db)}
    assert after[ng["title"]]["sponsorship"] == "Yes"
    assert after[ng["title"]]["sponsorship_note"] == "recruiter said so"
    assert after[sr["title"]]["sponsorship"] == "No"  # the other IBM job is untouched (and still auto)
    assert after[sr["title"]]["sponsorship_source"] == "auto"


def test_status_edit_and_validation(tmp_path):
    db = mk(tmp_path)
    job = query_jobs(db)[0]
    assert apply_job_edits(db, {job["id"]: {"status": "Applied"}}) == 1
    assert [r["status"] for r in query_jobs(db, status=["applied"])] == ["applied"]
    for bad in ({"status": "Hired"}, {"sponsorship": "Maybe"}):
        try:
            apply_job_edits(db, {job["id"]: bad})
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
    # note-only edits do not lock sponsorship
    apply_job_edits(db, {job["id"]: {"sponsorship_note": "hmm"}})
    assert query_jobs(db, status=["applied"])[0]["sponsorship_source"] == "auto"


def test_csv_has_columns_and_respects_the_filtered_rows(tmp_path):
    db = mk(tmp_path)
    text = jobs_to_csv(query_jobs(db, source=["greenhouse"]))
    lines = text.strip().splitlines()
    assert lines[0].startswith("company,title,location,experience,sponsorship")
    assert "size" not in lines[0].split(",")
    assert len(lines) == 3 and "id" not in lines[0].split(",")


def test_stats_match_the_rows_and_paging_is_stable(tmp_path):
    from app.services.views import job_ids, job_stats

    db = mk(tmp_path)
    # identical company and title: only the id tells them apart, so paging must still be repeatable
    db.record_board("greenhouse", "twin", [
        Job(source="greenhouse", board="twin", company="Twin", ext_id=str(i), title="Software Engineer, New Grad",
            url=f"https://x/t{i}", location="Chicago, IL") for i in range(5)
    ], "2026-10-02T00:00:00+00:00")
    classify_all(db, CFG, tmp_path)
    everything = query_jobs(db, cs_related_only=True)
    stats = job_stats(db, cs_related_only=True)
    assert stats["total"] == len(everything) == len(job_ids(db, cs_related_only=True))
    assert stats["new_grad"] == sum(r["experience"] == "New grad" for r in everything)
    pages = [query_jobs(db, cs_related_only=True, limit=2, offset=o) for o in range(0, stats["total"], 2)]
    assert [r["id"] for page in pages for r in page] == [r["id"] for r in everything]  # no repeats, no gaps


def test_stats_of_nothing_are_zero(tmp_path):
    from app.services.views import job_stats

    assert job_stats(mk(tmp_path), search="zzz-no-match") == {"total": 0, "new_grad": 0, "sponsor_yes": 0, "not_applied": 0}


def test_since_days_uses_the_posting_date(tmp_path):
    from datetime import datetime, timezone

    db = mk(tmp_path)  # every job first seen 2026-10-01
    db.execute("UPDATE jobs SET posted_at = '2026-09-01' WHERE title = 'Senior Engineer'")
    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
    recent = titles(query_jobs(db, since_days=7, now=now))
    assert "Senior Engineer" not in recent  # posted a month earlier, though only just seen
    assert "Software Engineer, New Grad" in recent  # no posting date: falls back to first seen
