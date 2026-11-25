from datetime import date

from app.db.repository import DB
from app.domain import Job
from app.services.storage import jobs_worth_storing, keep_job, prune_database

TECH = "Build services in Python and SQL on AWS with Docker."
TODAY = date(2026, 11, 18)


def test_keep_job_only_for_possible_us_tech_roles():
    assert keep_job("Software Engineer", "Chicago, IL")  # title alone is enough
    assert keep_job("Business Operations Specialist", "Austin, TX", TECH)  # disguised: 3+ technologies
    assert not keep_job("Business Operations Specialist", "Austin, TX", "Coordinate vendors.")
    assert not keep_job("Software Engineer", "London, UK", TECH)  # outside the US
    assert not keep_job("Account Executive", "Chicago, IL", TECH)  # never a tech title
    assert not keep_job("Nurse", "Chicago, IL")


def job(i, title, location="Chicago, IL", description=TECH, posted="2026-11-17"):
    return Job(source="greenhouse", board="acme", company="Acme", ext_id=str(i), title=title, url=f"https://x/{i}",
               location=location, description=description, posted_at=posted)


def test_fetch_keeps_fresh_possible_tech_jobs_only():
    fetched = [job(1, "Software Engineer"), job(2, "Nurse", description="Care for patients."),
               job(3, "Data Engineer", "Berlin, Germany"), job(4, "ML Engineer", posted="2026-11-01"),
               job(5, "Backend Engineer", posted=None)]
    assert [j.ext_id for j in jobs_worth_storing(fetched, 7, TODAY)] == ["1", "5"]  # no date: kept


def test_listed_jobs_stay_open_and_missing_ones_close(tmp_path):
    db = DB(tmp_path / "t.db")
    first = [job(1, "Software Engineer"), job(2, "Backend Engineer")]
    db.record_board("greenhouse", "acme", first, "2026-11-17T00:00:00")
    db.execute("UPDATE jobs SET status = 'applied' WHERE ext_id = '1'")
    # Next run: job 1 is still listed but too old to store again; job 2 is gone; a non-tech job is new.
    listed = [job(1, "Software Engineer", posted="2026-10-01"), job(9, "Nurse", description="Care.")]
    kept = jobs_worth_storing(listed, 7, TODAY)
    assert kept == []
    assert db.record_board("greenhouse", "acme", kept, "2026-11-18T00:00:00", seen=listed) == (0, 1)
    status = {r["ext_id"]: r["closed_at"] for r in db.query("SELECT ext_id, closed_at FROM jobs")}
    assert status["1"] is None and status["2"] == "2026-11-18T00:00:00"  # the applied job is still listed: open
    # An empty response (a glitch) never closes the board.
    assert db.record_board("greenhouse", "acme", [], "2026-11-19T00:00:00", seen=[]) == (0, 0)


def test_prune_removes_closed_and_old_untracked_jobs(tmp_path):
    db = DB(tmp_path / "t.db")
    db.record_board("greenhouse", "acme", [
        job(1, "Software Engineer"),                      # fresh: stays
        job(2, "Data Engineer", posted="2026-11-01"),     # old: goes
        job(3, "ML Engineer"),                            # closed: goes
        job(4, "AI Engineer", posted="2026-09-01"),       # old but applied: stays
        job(5, "Backend Engineer", posted="2026-09-01"),  # old but saved: stays
        job(6, "Nurse", description="Care."),             # fresh but not tech: goes with --full
    ], "2026-11-17T00:00:00")
    db.execute("UPDATE jobs SET closed_at = 'x' WHERE ext_id = '3'")
    db.execute("UPDATE jobs SET status = 'applied' WHERE ext_id = '4'")
    db.execute("UPDATE jobs SET status = 'saved' WHERE ext_id = '5'")
    db.execute("INSERT INTO job_matches (profile, job_id, score, reasons, scored_at) SELECT 'me', id, 50, '', 't' FROM jobs")

    dry = prune_database(db, 7, full=True, dry_run=True, today=TODAY)
    assert (dry["stale"], dry["irrelevant"]) == (2, 1)
    assert db.query("SELECT COUNT(*) AS n FROM jobs")[0]["n"] == 6  # a dry run deletes nothing
    assert prune_database(db, 7, today=TODAY)["deleted"] == 2
    assert prune_database(db, 7, full=True, today=TODAY)["irrelevant"] == 1
    assert {r["ext_id"] for r in db.query("SELECT ext_id FROM jobs")} == {"1", "4", "5"}
    assert db.query("SELECT COUNT(*) AS n FROM job_matches")[0]["n"] == 3  # scores went with their jobs
