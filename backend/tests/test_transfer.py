import pytest
from sqlalchemy import create_engine

from app.db.models import Base
from app.db.repository import DB
from app.db.transfer import copy_database
from app.domain import Job


def job(i):
    return Job(source="greenhouse", board="acme", company="Acme", ext_id=str(i), title=f"Engineer {i}",
               url=f"https://x/{i}", description="Build APIs " * 5)


@pytest.fixture
def source(tmp_path):
    db = DB(tmp_path / "src.db")
    db.record_board("greenhouse", "acme", [job(i) for i in range(5)], "2026-10-01T00:00:00+00:00")
    db.log("2026-10-01T00:00:00+00:00", "greenhouse", "acme", True, 5, None)
    db.execute("INSERT INTO companies (key, name, size, employees, size_source, updated_at) "
               "VALUES ('acme', 'Acme', 'Big', NULL, 'manual', 't')")  # the table is kept, though sizing is gone
    db.save_llm_labels([{"hash": "h", "model": "m", "is_tech": 1, "role_family": "Software", "reason": "r", "created_at": "t"}])
    return f"sqlite:///{tmp_path / 'src.db'}"


def empty_target(tmp_path):
    url = f"sqlite:///{tmp_path / 'dst.db'}"
    Base.metadata.create_all(create_engine(url))
    return url


def test_copy_moves_every_table_and_verifies_counts(tmp_path, source):
    target = empty_target(tmp_path)
    seen = []
    copied = copy_database(source, target, lambda t, done, total: seen.append((t, done, total)))
    assert copied == {"companies": 1, "fetch_log": 1, "jobs": 5, "llm_labels": 1, "job_matches": 0, "profiles": 0}
    assert ("jobs", 5, 5) in seen
    dst = DB(target)
    assert dst.scalar("SELECT COUNT(*) FROM jobs") == 5
    assert dst.query("SELECT size, size_source FROM companies")[0]["size"] == "Big"


def test_copy_refuses_a_target_that_already_has_data(tmp_path, source):
    target = empty_target(tmp_path)
    copy_database(source, target)
    with pytest.raises(RuntimeError, match="already has rows"):
        copy_database(source, target)
    assert DB(target).scalar("SELECT COUNT(*) FROM jobs") == 5  # untouched
