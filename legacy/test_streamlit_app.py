"""Runs app.py against a fake `streamlit` (the real one needs a browser). This checks the wiring: that the page
builds, the table has the right rows/columns, and the save callbacks write to the database. It cannot check how
the page looks: open it with `streamlit run app.py` for that."""
import contextlib
import runpy
import sys
import types
from pathlib import Path
from unittest.mock import patch

from app import cli
from app.services.classify import classify_all
from app.db.repository import DB
from app.domain import Job

APP = Path(__file__).resolve().parent.parent / "app.py"


class State(dict):
    __getattr__ = dict.get

    def __setattr__(self, k, v):
        self[k] = v


class Any:
    """Absorbs any call; works as a context manager; unpacks into any number of columns."""
    def __call__(self, *a, **k): return Any()
    def __getattr__(self, name): return Any()
    def __enter__(self): return self
    def __exit__(self, *a): return False


class FakeSt:
    def __init__(self):
        self.session_state = State()
        self.pressed = set()
        self.editors = {}       # key -> rows passed to data_editor
        self.messages = []
        self.column_config = Any()
        self.sidebar = Any()

    def button(self, label, **k): return label in self.pressed and not k.get("disabled")
    def multiselect(self, label, options, default=None, **k): return list(default if default is not None else [])
    def text_input(self, *a, **k): return ""
    def number_input(self, label, value=0, **k): return value
    def toggle(self, label, value=False, **k): return value
    def checkbox(self, label, value=False, **k): return value
    def selectbox(self, label, options, **k): return options[0]
    def tabs(self, names): return [Any() for _ in names]
    def columns(self, spec): return [Any() for _ in (range(spec) if isinstance(spec, int) else spec)]
    def data_editor(self, rows, key=None, **k): self.editors[key] = rows; return rows
    def success(self, m): self.messages.append(("success", m))
    def error(self, m): self.messages.append(("error", m))
    def info(self, m): self.messages.append(("info", m))
    def __getattr__(self, name): return Any()


def run_app(fake):
    mod = types.ModuleType("streamlit")
    mod.__dict__.update({n: getattr(fake, n) for n in dir(fake) if not n.startswith("_")})
    mod.__getattr__ = lambda name: getattr(fake, name)
    with patch.dict(sys.modules, {"streamlit": mod}):
        return runpy.run_path(str(APP))


def project(root):
    (root / "config.yaml").write_text("db_path: data/t.db\nexport_dir: data/exports\n"
                                      "http: {timeout_s: 5, workers: 2, user_agent: t}\n")
    (root / "company_sizes.yaml").write_text("big:\n  - IBM\nmid: []\nsmall: []\n")
    db = DB(root / "data" / "t.db")
    jobs = [Job(source="greenhouse", board="ibm", company="IBM", ext_id=str(i), title=t, url=f"https://x/{i}",
                location="Chicago, IL") for i, t in enumerate(["Software Engineer, New Grad", "Senior Engineer"])]
    db.record_board("greenhouse", "ibm", jobs, "2026-10-01T00:00:00+00:00")
    classify_all(db, {}, root)
    return db


def test_page_builds_and_edits_are_saved(tmp_path):
    db = project(tmp_path)
    fake = FakeSt()
    with patch.object(cli, "ROOT", tmp_path):
        g = run_app(fake)
        (table,) = [v for k, v in fake.editors.items() if k.startswith("jobs_editor")]
        # The default CS-related filter hides the generic engineering role.
        assert [r["Title"] for r in table] == ["Software Engineer, New Grad"]
        assert set(table[0]) >= {"Company", "Title", "Experience", "Size", "Sponsors?", "Sponsorship note", "Status", "Link"}
        assert {r["Size"] for r in table} == {"Big"}
        assert len(fake.session_state.job_ids) == 1

        # the user marks row 0 as sponsoring + applied, and writes a note, then presses Save
        fake.session_state["jobs_editor_0"] = {"edited_rows": {"0": {
            "Sponsors?": "Yes", "Status": "Applied", "Sponsorship note": "recruiter confirmed"}}}
        g["save_job_edits"]()
        row = db.conn.execute("SELECT * FROM jobs WHERE id = ?", (fake.session_state.job_ids[0],)).fetchone()
        assert (row["sponsorship"], row["sponsorship_source"], row["status"], row["sponsorship_note"]) == \
               ("Yes", "manual", "applied", "recruiter confirmed")
        assert fake.session_state.gen == 1 and fake.session_state.flash[0] == "success"

        # an invalid value is reported, not raised, and nothing is written
        fake.session_state["jobs_editor_1"] = {"edited_rows": {"0": {"Sponsors?": "Maybe"}}}
        g["save_job_edits"]()
        assert fake.session_state.flash[0] == "error"
        unchanged = db.conn.execute("SELECT sponsorship FROM jobs WHERE id = ?", (fake.session_state.job_ids[0],)).fetchone()
        assert unchanged["sponsorship"] == "Yes"

        # company size edit through the Companies tab callback
        run_app(fake)
        assert fake.session_state.company_keys == ["ibm"]
        fake.session_state["companies_editor_0"] = {"edited_rows": {"0": {"Size": "Mid-size"}}}
        g["save_company_edits"]()
        assert db.company_sizes()["ibm"]["size"] == "Mid-size"
        assert db.company_sizes()["ibm"]["size_source"] == "manual"


def test_fetch_button_runs_the_fetch_command(tmp_path):
    project(tmp_path)
    fake = FakeSt()
    fake.pressed.add("Fetch new jobs now")
    seen = []
    with patch.object(cli, "ROOT", tmp_path), patch.object(cli, "cmd_fetch", lambda a, c: seen.append((a.source, c["db_path"])) or print("fetched")):
        run_app(fake)
    assert seen == [(None, "data/t.db")]


def test_empty_database_shows_a_hint(tmp_path):
    (tmp_path / "config.yaml").write_text("db_path: data/empty.db\n")
    fake = FakeSt()
    with patch.object(cli, "ROOT", tmp_path):
        run_app(fake)
    assert any(level == "info" and "Fetch" in m for level, m in fake.messages)
