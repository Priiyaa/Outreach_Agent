from datetime import datetime, timezone

from app.db.repository import DB
from app.domain import Job


def mk(i, title="Analyst", location="Chicago, IL"):
    return Job(source="greenhouse", board="acme", company="Acme", ext_id=str(i),
               title=title, url=f"https://x/{i}", location=location, description="desc " * 3)


def count(db, where="1=1"):
    return db.scalar(f"SELECT COUNT(*) FROM jobs WHERE {where}")


def test_rerun_is_idempotent(tmp_path):
    db = DB(tmp_path / "t.db")
    assert db.record_board("greenhouse", "acme", [mk(1), mk(2)], "2026-10-15T00:00:00") == (2, 0)
    assert db.record_board("greenhouse", "acme", [mk(1), mk(2)], "2026-10-16T00:00:00") == (0, 0)
    assert count(db) == 2


def test_duplicates_within_one_fetch_collapse(tmp_path):
    db = DB(tmp_path / "t.db")
    assert db.record_board("greenhouse", "acme", [mk(1), mk(1)], "2026-10-15T00:00:00") == (1, 0)


def test_close_and_reopen(tmp_path):
    db = DB(tmp_path / "t.db")
    db.record_board("greenhouse", "acme", [mk(1), mk(2)], "2026-10-15T00:00:00")
    assert db.record_board("greenhouse", "acme", [mk(1)], "2026-10-16T00:00:00") == (0, 1)
    assert count(db, "closed_at IS NULL") == 1
    assert db.record_board("greenhouse", "acme", [mk(1), mk(2)], "2026-10-17T00:00:00") == (0, 0)
    assert count(db, "closed_at IS NULL") == 2


def test_empty_response_does_not_close_everything(tmp_path):
    db = DB(tmp_path / "t.db")
    db.record_board("greenhouse", "acme", [mk(1)], "2026-10-15T00:00:00")
    assert db.record_board("greenhouse", "acme", [], "2026-10-16T00:00:00") == (0, 0)
    assert count(db, "closed_at IS NULL") == 1


def test_other_boards_untouched(tmp_path):
    db = DB(tmp_path / "t.db")
    other = Job(source="lever", board="zed", company="Zed", ext_id="9", title="X", url="u")
    db.record_board("lever", "zed", [other], "2026-10-15T00:00:00")
    db.record_board("greenhouse", "acme", [mk(1)], "2026-10-16T00:00:00")
    assert count(db, "board = 'zed' AND closed_at IS NULL") == 1


def test_status_survives_refetch_and_fields_update(tmp_path):
    db = DB(tmp_path / "t.db")
    db.record_board("greenhouse", "acme", [mk(1, title="Analyst")], "2026-10-15T00:00:00")
    db.execute("UPDATE jobs SET status = 'applied'")
    db.record_board("greenhouse", "acme", [mk(1, title="Senior Analyst")], "2026-10-16T00:00:00")
    (row,) = db.query("SELECT title, status, first_seen FROM jobs")
    assert (row["title"], row["status"], row["first_seen"]) == ("Senior Analyst", "applied", "2026-10-15T00:00:00")


def test_export_filters_and_stats(tmp_path):
    db = DB(tmp_path / "t.db")
    now = datetime(2026, 10, 16, tzinfo=timezone.utc)
    db.record_board("greenhouse", "acme",
                    [mk(1, location="Seattle, WA"), mk(2, location="Chicago, IL"), mk(3, location="Remote")],
                    "2026-10-15T00:00:00+00:00")
    rows = db.export_rows(locations=["seattle", "chicago"], now=now)
    assert sorted(r["location"] for r in rows) == ["Chicago, IL", "Seattle, WA"]
    assert len(db.export_rows(since_days=1, now=now)) == 3
    assert len(db.export_rows(since_days=0, now=now)) == 0
    s = db.stats(now=now)
    assert s["open"] == 3 and s["by_source"] == {"greenhouse": 3} and s["new_24h"] == 3


def test_list_duplicate_of_a_direct_job_is_hidden(tmp_path):
    db = DB(tmp_path / "t.db")
    listed = Job(source="simplify", board="s", company="Acme", ext_id="x", title="Eng",
                 url="https://jobs.ashbyhq.com/acme/U1", ats_ref="ashby:acme:u1")
    direct = Job(source="ashby", board="acme", company="Acme", ext_id="U1", title="Eng",
                 url="https://jobs.ashbyhq.com/acme/U1", description="full text")
    db.record_board("simplify", "s", [listed], "2026-10-15T00:00:00")
    assert [r["source"] for r in db.export_rows()] == ["simplify"]  # nothing better yet
    db.record_board("ashby", "acme", [direct], "2026-10-16T00:00:00")
    assert [r["source"] for r in db.export_rows()] == ["ashby"]  # direct row wins
    assert db.stats()["open"] == 1
    assert count(db) == 2  # the list row is hidden, not deleted


def test_closed_direct_job_does_not_hide_the_list_copy(tmp_path):
    db = DB(tmp_path / "t.db")
    listed = Job(source="simplify", board="s", company="Acme", ext_id="x", title="Eng",
                 url="u", ats_ref="ashby:acme:u1")
    direct = Job(source="ashby", board="acme", company="Acme", ext_id="U1", title="Eng", url="u")
    other = Job(source="ashby", board="acme", company="Acme", ext_id="U2", title="Other", url="u2")
    db.record_board("simplify", "s", [listed], "2026-10-15T00:00:00")
    db.record_board("ashby", "acme", [direct, other], "2026-10-15T00:00:00")
    db.record_board("ashby", "acme", [other], "2026-10-16T00:00:00")  # U1 taken down
    assert sorted(r["source"] for r in db.export_rows()) == ["ashby", "simplify"]
