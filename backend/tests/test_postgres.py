"""The same behaviour on real Postgres. Skipped unless TEST_DATABASE_URL is set; CI runs it against a service container.

    TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost/test pytest tests/test_postgres.py
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.db.repository import DB
from app.db.transfer import copy_database
from app.domain import Job
from app.services.classify import classify_all
from app.services.llm import Verdict, run_llm_stage
from app.services.views import apply_job_edits, jobs_to_csv, query_jobs

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")

BACKEND = Path(__file__).resolve().parents[1]


def job(i, title, description="", **kw):
    return Job(source="greenhouse", board="acme", company="Acme", ext_id=str(i), title=title,
               url=f"https://x/{i}", location="Chicago, IL", description=description, **kw)


@pytest.fixture
def db(tmp_path):
    engine = create_engine(URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    # build the schema the way production does: through the migrations
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True,
                   env={**os.environ, "DATABASE_URL": URL})
    (tmp_path / "config").mkdir()
    return DB(URL), tmp_path


def seed(db, tmp_path):
    db.record_board("greenhouse", "acme", [
        job(1, "Software Engineer, New Grad"),
        job(2, "Business Operations Analyst", "Build internal APIs in Python and SQL and automate data pipelines."),
        job(3, "Operations Analyst", "Coordinate vendor schedules and budgets."),
    ], "2026-10-01T00:00:00+00:00")
    classify_all(db, {"size": {}, "claude": {}}, tmp_path)


def test_ingest_is_idempotent_and_closes_missing_postings(db):
    db, _ = db
    assert db.record_board("greenhouse", "acme", [job(1, "A"), job(2, "B")], "2026-10-01T00:00:00+00:00") == (2, 0)
    assert db.record_board("greenhouse", "acme", [job(1, "A")], "2026-10-02T00:00:00+00:00") == (0, 1)
    assert db.scalar("SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL") == 1


def test_filters_edits_stats_and_export_work_on_postgres(db):
    db, tmp_path = db
    seed(db, tmp_path)
    rows = query_jobs(db, cs_related_only=True, experience=["New grad"], search="software", location="chicago")
    assert [r["title"] for r in rows] == ["Software Engineer, New Grad"]
    assert len(query_jobs(db, cs_related_only=False)) == 3
    assert apply_job_edits(db, {rows[0]["id"]: {"status": "applied", "sponsorship": "Yes"}}) == 1
    (edited,) = query_jobs(db, status=["applied"])
    assert edited["sponsorship"] == "Yes"
    assert db.stats()["open"] == 3 and db.export_rows()
    assert jobs_to_csv(query_jobs(db, cs_related_only=False)).count("\n") == 4


def test_llm_stage_and_cache_on_postgres(db):
    db, tmp_path = db
    seed(db, tmp_path)

    class Fake:
        model = "fake"
        calls = 0

        def classify(self, title, department, description):
            Fake.calls += 1
            return Verdict(False, "Not tech", "reporting")

    assert run_llm_stage(db, Fake())["asked"] == 1
    assert run_llm_stage(db, Fake())["candidates"] == 0
    assert db.scalar("SELECT COUNT(*) FROM llm_labels") == 1


def test_copy_from_sqlite_into_postgres_and_new_log_rows_still_insert(db, tmp_path):
    pg, _ = db
    local = DB(tmp_path / "local.db")
    local.record_board("greenhouse", "acme", [job(1, "A"), job(2, "B")], "2026-10-01T00:00:00+00:00")
    local.log("2026-10-01T00:00:00+00:00", "greenhouse", "acme", True, 2, None)
    assert copy_database(f"sqlite:///{tmp_path / 'local.db'}", URL)["jobs"] == 2
    pg.log("2026-10-02T00:00:00+00:00", "greenhouse", "acme", True, 2, None)  # would collide if the id counter were not reset
    assert pg.scalar("SELECT COUNT(*) FROM fetch_log") == 2
