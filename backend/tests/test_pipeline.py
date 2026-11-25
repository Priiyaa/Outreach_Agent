"""End-to-end: the real CLI against a local fake ATS server (no internet needed)."""
import contextlib
import csv
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from app import cli
from app.sources import ashby, greenhouse, lever

GH = {
    "jobs": [
        {"id": 1, "title": "Data Analyst", "absolute_url": "https://gh/1", "location": {"name": "Chicago, IL"},
         "updated_at": "2026-10-14T10:00:00-04:00", "content": "&lt;p&gt;SQL&lt;/p&gt;"},
        {"id": 2, "title": "Business Operations Analyst", "absolute_url": "https://gh/2",
         "location": {"name": "Seattle, WA"}, "updated_at": "2026-10-13T10:00:00-04:00", "content": ""},
    ]
}
LV = [{"id": "l1", "text": "ML Engineer", "hostedUrl": "https://lv/1", "createdAt": 1760000000000,
       "categories": {"location": "San Jose, CA"}, "descriptionPlain": "Models."}]
AS = {"jobs": [{"id": "a1", "title": "Solutions Engineer", "location": "Remote", "isRemote": True,
                "descriptionPlain": "APIs.", "publishedAt": "2026-10-10T12:00:00Z", "jobUrl": "https://as/1"}]}


@contextlib.contextmanager
def fake_ats(routes):
    """Serve `routes` (path -> JSON). /ashby/flaky answers 503 once, then succeeds. Unknown paths 404."""
    hits = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            hits[path] = hits.get(path, 0) + 1
            if path == "/ashby/flaky" and hits[path] == 1:
                status, body = 503, {"error": "busy"}
            elif path in routes:
                status, body = 200, routes[path]
            else:
                status, body = 404, {"error": "not found"}
            data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with patch.object(greenhouse, "API", base + "/gh/{slug}/jobs"), \
             patch.object(lever, "HOSTS", {"us": base + "/lever", "eu": base + "/lever-eu"}), \
             patch.object(ashby, "API", base + "/ashby/{slug}"), \
             patch("app.sources.base.time.sleep"):
            yield hits, base
    finally:
        server.shutdown()
        server.server_close()


def make_project(root):
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "config.yaml").write_text(
        "db_path: data/t.db\nexport_dir: data/exports\n"
        "http:\n  timeout_s: 5\n  workers: 4\n  user_agent: test\n"
        "retention:\n  days: 100000\n"  # the fixtures are dated; age-based cleanup is tested in test_storage
    )
    (root / "config" / "companies.yaml").write_text(
        "greenhouse:\n  - {name: Acme, slug: acme}\n  - {name: Ghost, slug: ghost}\n"
        "lever:\n  - {name: Zed, slug: zed}\n"
        "ashby:\n  - {name: Flaky, slug: flaky}\n"
    )


def run_cli(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.main(list(argv))
    return buf.getvalue()


def test_cli_end_to_end(tmp_path):
    make_project(tmp_path)
    routes = {"/gh/acme/jobs": GH, "/lever/v0/postings/zed": LV, "/ashby/flaky": AS}
    with patch.object(cli, "ROOT", tmp_path), fake_ats(routes) as (hits, _base):
        out = run_cli("fetch")
        assert "4 jobs fetched from 3/4 boards: 4 new, 0 closed" in out
        assert "Classified 4 jobs" in out
        assert "[greenhouse] Ghost: 404" in out  # bad slug reported, run still completed
        assert hits["/ashby/flaky"] == 2  # one 503, then retried successfully

        # re-running is idempotent
        assert "4 jobs fetched from 3/4 boards: 0 new, 0 closed" in run_cli("fetch")

        # a posting disappears upstream -> marked closed, then removed (not saved or applied to)
        routes["/gh/acme/jobs"] = {"jobs": [GH["jobs"][0]]}
        assert "3 jobs fetched from 3/4 boards: 0 new, 1 closed" in run_cli("fetch")

        out = run_cli("export", "--location", "chicago,san jose")
        assert "Wrote 2 jobs" in out
        (csv_path,) = (tmp_path / "data" / "exports").glob("jobs_*.csv")
        rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
        assert sorted(r["title"] for r in rows) == ["Data Analyst", "ML Engineer"]
        assert {r["company"] for r in rows} == {"Acme", "Zed"}

        assert "Wrote 3 jobs" in run_cli("export", "--include-closed")  # the closed one was removed
        assert {r["experience"] for r in rows} <= {"New grad", "Experienced", "Unclear"}
        assert "size" not in rows[0]
        assert all(r["sponsorship"] == "Unknown" for r in rows)

        stats = run_cli("stats")
        assert "Open jobs: 3   Closed: 0" in stats
        assert "failed: [greenhouse] ghost" in stats

        checked = run_cli("check", "--source", "lever")
        assert "Zed" in checked and "1 ok, 0 failing" in checked


SIMPLIFY_FEED = [
    {"id": "s1", "company_name": "Flaky", "title": "Solutions Engineer", "active": True, "is_visible": True,
     "date_posted": 1760000000, "url": "https://jobs.ashbyhq.com/flaky/a1?utm_source=Simplify",
     "locations": ["Remote"], "category": "Software", "sponsorship": "Other", "degrees": ["Bachelor's"]},
    {"id": "s2", "company_name": "NewCo", "title": "Analyst", "active": True, "is_visible": True,
     "date_posted": 1760000000, "url": "https://boards.greenhouse.io/newco/jobs/555",
     "locations": ["Seattle, WA"], "category": "Software"},
    {"id": "s3", "company_name": "Dead", "title": "Closed role", "active": False, "is_visible": True,
     "url": "https://example.com/3", "locations": []},
]
JOBRIGHT_MD = (
    "# Daily jobs\n\n"
    "| Company | Job Title | Location | Work Model | Date Posted |\n| --- | --- | --- | --- | --- |\n"
    "| **[SpaceX](https://www.spacex.com)** | **[Ops Analyst](https://jobright.ai/jobs/info/abc123?utm_source=1)** "
    "| Hawthorne, CA | On Site | Oct 14 |\n"
    "| ↳ | **[Strategy Analyst](https://jobright.ai/jobs/info/def456?utm_source=1)** | Remote, US | Remote | Oct 13 |\n"
)
NEWCO_BOARD = {
    "jobs": [{"id": 555, "title": "Analyst", "absolute_url": "https://boards.greenhouse.io/newco/jobs/555",
              "location": {"name": "Seattle, WA"}, "updated_at": "2026-10-14T00:00:00Z",
              "content": "&lt;p&gt;Full description&lt;/p&gt;"}]
}


def read_export(root):
    (path,) = (root / "data" / "exports").glob("jobs_*.csv")
    return list(csv.DictReader(open(path, encoding="utf-8")))


def test_lists_dedupe_and_discover(tmp_path):
    make_project(tmp_path)
    (tmp_path / "config" / "companies.yaml").write_text("ashby:\n  - {name: Flaky, slug: flaky}\n")
    routes = {"/ashby/flaky": AS, "/lists/simplify.json": SIMPLIFY_FEED, "/lists/jobright.md": JOBRIGHT_MD}
    with patch.object(cli, "ROOT", tmp_path), fake_ats(routes) as (_hits, base):
        (tmp_path / "config" / "lists.yaml").write_text(
            f"simplify:\n  - {{name: S, slug: s, url: '{base}/lists/simplify.json'}}\n"
            f"jobright:\n  - {{name: J, slug: j, url: '{base}/lists/jobright.md'}}\n"
        )
        # 1 direct Ashby + 2 active Simplify (one inactive skipped) + 2 Jobright
        assert "5 jobs fetched from 3/3 boards: 5 new" in run_cli("fetch")

        # Simplify's copy of Flaky's Ashby posting is hidden: the company's own board has the full record
        assert "Wrote 4 jobs" in run_cli("export")
        assert sorted(r["source"] for r in read_export(tmp_path)) == ["ashby", "jobright", "jobright", "simplify"]

        out = run_cli("discover")
        assert "Found 1 new boards (1 greenhouse)" in out
        discovered = (tmp_path / "config" / "companies.discovered.yaml").read_text()
        assert "newco" in discovered and "flaky" not in discovered  # already-known boards are not re-proposed

        # the discovered board is now fetched directly, which supersedes the thin Simplify row
        routes["/gh/newco/jobs"] = NEWCO_BOARD
        assert "6 jobs fetched from 4/4 boards: 1 new" in run_cli("fetch")
        run_cli("export")
        rows = read_export(tmp_path)
        assert sorted(r["source"] for r in rows) == ["ashby", "greenhouse", "jobright", "jobright"]
        (newco,) = [r for r in rows if r["source"] == "greenhouse"]
        assert int(newco["description_chars"]) > 0

        # re-running discover with nothing new left to find is harmless
        assert "boards" in run_cli("discover")
