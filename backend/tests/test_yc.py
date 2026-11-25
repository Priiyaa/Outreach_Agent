from app.db.repository import DB
from app.domain import Job
from app.services.classify import classify_all
from app.services.views import query_jobs
from app.services.yc import discover, find_board, short_batch, slug_candidates, sync_tags

HIRING = [
    {"name": "GovDash", "slug": "govdash", "website": "https://www.govdash.com", "batch": "Winter 2024",
     "status": "Active", "regions": ["America / Canada"]},
    {"name": "Acme Robotics", "slug": "acme-robotics", "website": "https://acmebots.ai", "batch": "Summer 2023",
     "status": "Active", "regions": ["Remote"]},
    {"name": "Known Co", "slug": "knownco", "website": "https://known.co", "batch": "Fall 2024",
     "status": "Active", "regions": ["America / Canada"]},
    {"name": "Euro Only", "slug": "euro", "website": "https://euro.eu", "batch": "Winter 2025",
     "status": "Active", "regions": ["Europe"]},  # not hiring in the US: skipped
    {"name": "Silent", "slug": "silent", "website": "https://silent.dev", "batch": "Spring 2025",
     "status": "Active", "regions": ["America / Canada"]},  # no public board: skipped
]
BOARDS = {"https://api.ashbyhq.com/posting-api/job-board/govdash": {"jobs": [{"id": 1}]},
          "https://api.lever.co/v0/postings/acmebots?mode=json&limit=1": [{"id": "x"}],
          "https://boards-api.greenhouse.io/v1/boards/acme-robotics/jobs": {"jobs": []}}  # empty board: not a hit


class Resp:
    def __init__(self, status, body):
        self.status_code, self.ok, self.body = status, status < 400, body

    def json(self):
        return self.body


class FakeSession:
    def __init__(self):
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        if url.endswith("hiring.json"):
            return Resp(200, HIRING)
        return Resp(200, BOARDS[url]) if url in BOARDS else Resp(404, {})


def test_batch_and_slug_guesses():
    assert [short_batch(b) for b in ("Winter 2024", "Summer 2023", "Fall 2024", "Spring 2025", "IK12")] == \
        ["W24", "S23", "F24", "X25", "IK12"]
    assert slug_candidates(HIRING[1]) == ["acme-robotics", "acmebots", "acmerobotics"]
    assert find_board(FakeSession(), HIRING[0]) == ("ashby", "govdash")
    assert find_board(FakeSession(), HIRING[1]) == ("lever", "acmebots")  # the empty Greenhouse board was skipped


def test_discover_reuses_known_boards_and_skips_the_rest():
    session = FakeSession()
    known = [("greenhouse", {"name": "Known Co", "slug": "known-co"})]
    result = discover(session, known, workers=2)
    assert result["companies"] == 4  # the Europe-only company is left out
    assert result["boards"] == {
        "ashby": [{"name": "GovDash", "slug": "govdash", "yc": "W24"}],
        "lever": [{"name": "Acme Robotics", "slug": "acmebots", "yc": "S23"}],
        "greenhouse": [{"name": "Known Co", "slug": "known-co", "yc": "F24"}],  # matched by name, not probed
    }
    assert not any("knownco" in u for u in session.urls)


def test_tags_drive_the_badge_and_filter(tmp_path):
    db = DB(tmp_path / "t.db")
    for company, board in (("GovDash", "govdash"), ("Big Corp", "bigcorp")):
        db.record_board("ashby", board, [Job(source="ashby", board=board, company=company, ext_id="1",
                                             title="Software Engineer", url=f"https://x/{board}", location="Remote, US")],
                        "2026-11-18T00:00:00")
    classify_all(db, {}, tmp_path)
    assert sync_tags(db, [("ashby", {"name": "GovDash", "slug": "govdash", "yc": "W24"}),
                          ("ashby", {"name": "Big Corp", "slug": "bigcorp"})]) == 1
    rows = {r["company"]: r["yc_batch"] for r in query_jobs(db)}
    assert rows == {"GovDash": "W24", "Big Corp": ""}
    assert [r["company"] for r in query_jobs(db, yc_only=True)] == ["GovDash"]
    sync_tags(db, [])  # a company dropped from companies.yc.yaml loses its tag
    assert query_jobs(db, yc_only=True) == []
