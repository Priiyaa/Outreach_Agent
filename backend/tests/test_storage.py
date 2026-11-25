from app.db.repository import DB
from app.domain import Job
from app.services.storage import drop_unneeded_descriptions, keep_description, trim_database

TECH = "Build services in Python and SQL on AWS with Docker."


def test_keep_description_only_for_possible_us_tech_roles():
    assert keep_description("Software Engineer", "Chicago, IL", "Ship features.")
    assert keep_description("Business Operations Specialist", "Austin, TX", TECH)  # disguised: 3+ technologies
    assert not keep_description("Business Operations Specialist", "Austin, TX", "Coordinate vendors.")
    assert not keep_description("Software Engineer", "London, UK", TECH)  # outside the US
    assert not keep_description("Account Executive", "Chicago, IL", TECH)  # never a tech title
    assert not keep_description("Software Engineer", "Chicago, IL", "")


def job(i, title, location, description):
    return Job(source="greenhouse", board="acme", company="Acme", ext_id=str(i), title=title, url=f"https://x/{i}",
               location=location, description=description)


def test_fetch_side_drop_and_database_trim(tmp_path):
    jobs = [job(1, "Software Engineer", "Chicago, IL", TECH), job(2, "Nurse", "Chicago, IL", "Care for patients."),
            job(3, "Data Engineer", "Berlin, Germany", TECH), job(4, "ML Engineer", "Remote, US", TECH)]
    assert drop_unneeded_descriptions(jobs) == 2
    assert [bool(j.description) for j in jobs] == [True, False, False, True]

    db = DB(tmp_path / "t.db")
    full = [job(1, "Software Engineer", "Chicago, IL", TECH), job(2, "Nurse", "Chicago, IL", "Care for patients."),
            job(4, "ML Engineer", "Remote, US", TECH), job(5, "Data Engineer", "Chicago, IL", TECH)]
    db.record_board("greenhouse", "acme", full, "2026-11-01T00:00:00")
    db.execute("UPDATE jobs SET closed_at = 'x' WHERE ext_id IN ('4', '5')")
    db.execute("UPDATE jobs SET status = 'applied' WHERE ext_id = '5'")  # tracked: keeps its text even closed
    assert trim_database(db) == {"checked": 4, "trimmed": 2, "kept": 2}
    kept = {r["ext_id"] for r in db.query("SELECT ext_id FROM jobs WHERE description != ''")}
    assert kept == {"1", "5"}
