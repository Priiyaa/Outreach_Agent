from datetime import date

from app.db.repository import DB
from app.services.ats_urls import ats_ref_for_url, parse_ats_url
from app.sources.workday import Workday, find_us_facet, page_base, posted_date, posting_id, worth_a_description

SLUG = "acme.wd5.myworkdayjobs.com/acme/Careers"
US_ID = "us-1"
FACETS = [
    {"facetParameter": "jobFamilyGroup", "values": [{"descriptor": "Engineering", "id": "e"}]},
    {"facetParameter": None, "values": [  # a group, as NVIDIA's board has
        {"facetParameter": "locationHierarchy1", "descriptor": "Locations",
         "values": [{"descriptor": "Canada", "id": "ca"}, {"descriptor": "United States", "id": US_ID}]},
    ]},
]
POSTINGS = [
    {"title": "Software Engineer", "externalPath": "/job/US-CA-Santa-Clara/Software-Engineer_JR1",
     "locationsText": "US, CA, Santa Clara", "postedOn": "Posted Today"},
    {"title": "Account Executive", "externalPath": "/job/US-NY-New-York/Account-Executive_JR2",
     "locationsText": "US, NY, New York", "postedOn": "Posted 3 Days Ago"},
    {"title": "Data Engineer", "externalPath": "/job/2-Locations/Data-Engineer_JR3",
     "locationsText": "2 Locations", "postedOn": "Posted 30+ Days Ago"},
]
DETAILS = {
    "JR1": {"jobDescription": "<p>Build services in <b>Python</b>.</p>", "location": "US, CA, Santa Clara",
            "startDate": "2026-11-14", "country": {"descriptor": "United States of America"}},
    "JR3": {"jobDescription": "<p>Pipelines</p>", "location": "Austin, TX", "additionalLocations": ["Remote, US"],
            "startDate": "2026-10-01", "country": {"descriptor": "United States of America"}},
}


class FakeWorkday:
    """Answers the listing (paged, filtered by the US facet) and the per-posting detail requests."""

    def __init__(self, postings=POSTINGS, page=2):
        self.postings, self.page, self.posts, self.gets = postings, page, [], []

    def post(self, url, json=None, params=None, timeout=None):
        self.posts.append(json)
        assert url == "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers/jobs"
        rows = self.postings[json["offset"]:json["offset"] + self.page]
        filtered = bool(json["appliedFacets"])
        body = {"total": len(self.postings) if json["offset"] == 0 else 0,  # Workday only counts on page 1
                "jobPostings": rows, "facets": [] if filtered else FACETS}
        return Resp(body)

    def get(self, url, params=None, timeout=None):
        self.gets.append(url)
        ext = url.rsplit("_", 1)[-1]
        return Resp({"jobPostingInfo": DETAILS[ext]})


class Resp:
    status_code, ok = 200, True

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body

    def raise_for_status(self):
        pass


def test_fetch_lists_us_postings_and_reads_descriptions_only_for_possible_tech_roles(monkeypatch):
    monkeypatch.setattr("app.sources.workday.PAGE", 2)
    session = FakeWorkday()
    jobs = {j.ext_id: j for j in Workday(session).fetch({"name": "Acme", "slug": SLUG})}

    assert session.posts[1]["appliedFacets"] == {"locationHierarchy1": [US_ID]}  # US filter found and used
    assert sorted(jobs) == ["JR1", "JR2", "JR3"]  # paged past the first page
    assert len(session.gets) == 2  # the sales role gets no description request
    eng = jobs["JR1"]
    assert eng.description == "Build services in Python." and eng.posted_at == "2026-11-14"
    assert eng.url == "https://acme.wd5.myworkdayjobs.com/Careers/job/US-CA-Santa-Clara/Software-Engineer_JR1"
    assert eng.ats_ref == f"workday:{SLUG.lower()}:jr1"
    assert jobs["JR3"].location == "Austin, TX; Remote, US" and jobs["JR3"].remote
    assert jobs["JR2"].description == "" and jobs["JR2"].posted_at is not None


def test_saved_descriptions_are_not_fetched_again(monkeypatch):
    monkeypatch.setattr("app.sources.workday.PAGE", 2)
    session = FakeWorkday()
    known = {"JR1": "US, CA, Santa Clara", "JR3": "Austin, TX; Remote, US"}
    jobs = {j.ext_id: j for j in Workday(session).fetch({"name": "Acme", "slug": SLUG, "known": known})}
    assert session.gets == []
    assert jobs["JR3"].location == "Austin, TX; Remote, US"  # the saved full location, not "2 Locations"


def test_an_empty_description_keeps_the_saved_one(tmp_path, monkeypatch):
    monkeypatch.setattr("app.sources.workday.PAGE", 2)
    db = DB(tmp_path / "t.db")
    db.record_board("workday", SLUG, Workday(FakeWorkday()).fetch({"name": "Acme", "slug": SLUG}), "2026-11-15T00:00:00")
    db.execute("UPDATE jobs SET classified_at = 'x'")
    again = Workday(FakeWorkday()).fetch({"name": "Acme", "slug": SLUG, "known": {"JR1": "US, CA, Santa Clara"}})
    assert next(j for j in again if j.ext_id == "JR1").description == ""
    new, closed = db.record_board("workday", SLUG, again, "2026-11-16T00:00:00")
    row = db.query("SELECT description, classified_at FROM jobs WHERE ext_id = 'JR1'")[0]
    assert (new, closed) == (0, 0)
    assert row["description"] == "Build services in Python." and row["classified_at"] == "x"  # kept, no reclassify


def test_helpers():
    assert posting_id("/job/US-CA/Software-Engineer_JR2017486-1") == "JR2017486-1"
    today = date(2026, 11, 16)
    assert posted_date("Posted Today", today) == "2026-11-16"
    assert posted_date("Posted Yesterday", today) == "2026-11-15"
    assert posted_date("Posted 3 Days Ago", today) == "2026-11-13"
    assert posted_date("Posted 30+ Days Ago", today) is None
    assert find_us_facet(FACETS) == ("locationHierarchy1", US_ID)
    assert find_us_facet([{"facetParameter": "x", "values": [{"descriptor": "Canada", "id": "c"}]}]) is None
    assert page_base("wd5.myworkdaysite.com/microchiphr/External") == "https://wd5.myworkdaysite.com/recruiting/microchiphr/External"
    assert worth_a_description("Software Engineer", "US, CA, Santa Clara")
    assert worth_a_description("Data Engineer", "3 Locations")
    assert not worth_a_description("Account Executive", "US, NY, New York")
    assert not worth_a_description("Mechanical Engineer", "Austin, TX")
    assert not worth_a_description("Software Engineer", "Bangalore, India")


def test_workday_links_are_recognized():
    url = "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/ASIC-Engineer_JR2013177/apply"
    assert parse_ats_url(url) == ("workday", "nvidia.wd5.myworkdayjobs.com/nvidia/NVIDIAExternalCareerSite", "JR2013177")
    site = "https://wd12.myworkdaysite.com/recruiting/caris/CLS/job/Irving-TX/Associate-Software-Engineer_JR105464"
    assert ats_ref_for_url(site) == "workday:wd12.myworkdaysite.com/caris/cls:jr105464"
    assert parse_ats_url("https://acme.wd1.myworkdayjobs.com/Careers")[2] is None
    assert parse_ats_url("https://acme.wd1.myworkdayjobs.com/") is None
