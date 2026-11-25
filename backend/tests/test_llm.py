import pytest

from app import cli
from app.db.repository import DB
from app.domain import Job
from app.services.classify import classify_all
from app.services.llm import (
    GeminiClassifier,
    LLMUnavailable,
    Verdict,
    get_classifier,
    needs_llm,
    parse_batch,
    parse_verdict,
    run_llm_stage,
    text_hash,
)

CFG = {}
TECH_TEXT = "Build internal APIs and automate data pipelines in Python. Maintain backend services and databases."
OPS_TEXT = "Coordinate vendor schedules, budgets and quarterly business reviews."


class Fake:
    model = "fake-1"

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def classify(self, title, department, description):
        self.calls.append(title)
        answer = self.answers[title]
        if isinstance(answer, Exception):
            raise answer
        return answer


def job(i, title, description, **kw):
    return Job(source="greenhouse", board="acme", company="Acme", ext_id=str(i), title=title,
               url=f"https://x/{i}", location="Chicago, IL", description=description, **kw)


@pytest.fixture
def db(tmp_path):
    (tmp_path / "config").mkdir()
    db = DB(tmp_path / "t.db")
    db.record_board("greenhouse", "acme", [
        job(1, "Software Engineer", TECH_TEXT),                                       # title match: trusted
        job(2, "Business Operations Analyst", TECH_TEXT),                             # weak: description only
        job(3, "Operations Analyst", OPS_TEXT),                                       # not tech, no tech words
        job(4, "Operations Specialist", "Own the data platform: design APIs, databases, data pipelines and backend services in Python."),  # negative with tech words
        job(5, "Senior Business Analyst", TECH_TEXT),                                 # senior: never a candidate
    ], "2026-10-01T00:00:00+00:00")
    classify_all(db, CFG, tmp_path)
    return db


def ids_by_title(db):
    return {r["title"]: r for r in db.query("SELECT title, is_cs_role, cs_evidence, role_family FROM jobs")}


def test_parse_verdict_accepts_json_and_fenced_json_and_normalizes():
    assert parse_verdict('{"is_tech": true, "role_family": "ML/AI", "reason": "trains models"}') == Verdict(True, "ML/AI", "trains models")
    assert parse_verdict('```json\n{"is_tech": false, "role_family": "Software", "reason": "sales"}\n```').role_family == "Not tech"
    assert parse_verdict('{"is_tech": true, "role_family": "Wizardry"}').role_family == "Other tech"


@pytest.mark.parametrize("raw", ["not json", '{"is_tech": "yes"}', "[]", '{"role_family": "Software"}'])
def test_parse_verdict_rejects_malformed_output(raw):
    with pytest.raises(ValueError):
        parse_verdict(raw)


def test_only_uncertain_jobs_are_candidates(db):
    picked = {r["title"] for r in db.llm_candidates() if needs_llm(r)}
    assert picked == {"Business Operations Analyst", "Operations Specialist"}


def test_stage_without_a_provider_changes_nothing(db):
    before = ids_by_title(db)
    stats = run_llm_stage(db, None)
    assert stats["candidates"] == 2 and stats["asked"] == 0
    assert ids_by_title(db) == before


def test_llm_can_overturn_rules_in_both_directions_and_results_are_cached(db):
    fake = Fake({"Business Operations Analyst": Verdict(False, "Not tech", "mostly reporting"),   # rules said tech
                 "Operations Specialist": Verdict(True, "Data", "owns the data platform")})          # rules said not
    stats = run_llm_stage(db, fake)
    assert stats["asked"] == 2 and stats["changed"] == 2
    rows = ids_by_title(db)
    assert rows["Business Operations Analyst"]["is_cs_role"] == 0 and rows["Business Operations Analyst"]["role_family"] == "Not tech"
    assert rows["Operations Specialist"]["is_cs_role"] == 1 and rows["Operations Specialist"]["role_family"] == "Data"
    assert rows["Operations Specialist"]["cs_evidence"] == "llm: owns the data platform"
    again = run_llm_stage(db, fake)  # already labelled: no new calls
    assert again["candidates"] == 0 and len(fake.calls) == 2


def test_cached_answer_is_reused_after_a_reclassify_with_no_new_call(db, tmp_path):
    fake = Fake({"Business Operations Analyst": Verdict(True, "Data", "builds pipelines"),
                 "Operations Specialist": Verdict(False, "Not tech", "pm")})
    run_llm_stage(db, fake)
    classify_all(db, CFG, tmp_path, force=True)  # rules overwrite the labels...
    run_llm_stage(db, fake)                      # ...the cache puts the verdicts back for free
    assert len(fake.calls) == 2
    assert ids_by_title(db)["Business Operations Analyst"]["cs_evidence"].startswith("llm:")


def test_call_budget_and_outage_stop_the_run_but_keep_finished_work(db):
    fake = Fake({"Business Operations Analyst": Verdict(True, "Software", "x"),
                 "Operations Specialist": Verdict(False, "Not tech", "y")})
    assert run_llm_stage(db, fake, max_calls=1)["asked"] == 1
    down = Fake({"Operations Specialist": LLMUnavailable("HTTP 429"), "Business Operations Analyst": Verdict(True, "Software", "x")})
    stats = run_llm_stage(db, down)
    assert stats["outage"] is True
    assert ids_by_title(db)["Business Operations Analyst"]["cs_evidence"].startswith("llm:")


def test_unusable_reply_is_counted_and_not_stored(db):
    fake = Fake({"Business Operations Analyst": ValueError("bad json"), "Operations Specialist": Verdict(False, "Not tech", "y")})
    stats = run_llm_stage(db, fake)
    assert stats["failed"] == 1
    assert not ids_by_title(db)["Business Operations Analyst"]["cs_evidence"].startswith("llm:")


def test_identical_text_is_one_call():
    assert text_hash("T", "D", "x" * 10) == text_hash("T", "D", "x" * 10)
    assert text_hash("T", "D", "a") != text_hash("T", "D", "b")


class FakeSession:
    def __init__(self, status=200, body=None):
        self.status, self.body, self.sent = status, body, []

    def post(self, url, json=None, headers=None, timeout=None):
        self.sent.append((url, json, headers))
        return FakeResponse(self.status, self.body)


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")


def gemini_body(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def test_gemini_sends_key_in_header_and_parses_reply():
    session = FakeSession(body=gemini_body('{"is_tech": true, "role_family": "Software", "reason": "writes code"}'))
    verdict = GeminiClassifier("k", "gemini-x", session=session).classify("Eng", "R&D", "desc")
    assert verdict == Verdict(True, "Software", "writes code")
    url, body, headers = session.sent[0]
    assert "gemini-x:generateContent" in url and headers == {"x-goog-api-key": "k"} and "key=" not in url
    assert body["generationConfig"]["temperature"] == 0


@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_gemini_quota_and_auth_errors_mean_unavailable(status):
    with pytest.raises(LLMUnavailable):
        GeminiClassifier("k", "m", session=FakeSession(status=status), sleep=lambda s: None).classify("t", "d", "x")


def test_gemini_garbage_reply_is_a_value_error():
    with pytest.raises(ValueError):
        GeminiClassifier("k", "m", session=FakeSession(body={"candidates": []})).classify("t", "d", "x")


def test_provider_selection_needs_both_config_and_key():
    assert get_classifier({}, env={}) is None
    assert get_classifier({"llm": {"provider": "gemini"}}, env={}) is None
    assert get_classifier({"llm": {"provider": "none"}}, env={"GEMINI_API_KEY": "k"}) is None
    assert get_classifier({"llm": {"provider": "gemini", "model": "m"}}, env={"GEMINI_API_KEY": "k"}).model == "m"


def test_scores():
    s = cli._scores([(1, 1), (1, 0), (0, 1), (0, 0), (1, 1)])
    assert (s["tp"], s["fp"], s["fn"], s["tn"]) == (2, 1, 1, 1)
    assert round(s["precision"], 3) == 0.667 and round(s["recall"], 3) == 0.667


def test_gemini_paces_requests_and_retries_a_rate_limited_call_once():
    waits = []
    ok = gemini_body('{"is_tech": true, "role_family": "Software", "reason": "code"}')

    class Limited(FakeSession):
        def post(self, url, json=None, headers=None, timeout=None):
            super().post(url, json, headers, timeout)
            if len(self.sent) == 1:  # first call is rate limited, with Google's hint in the body
                resp = FakeResponse(429, None)
                resp.text = "Please retry in 8.4s."
                return resp
            return FakeResponse(200, ok)

    session = Limited()
    classifier = GeminiClassifier("k", "m", session=session, requests_per_minute=12, sleep=waits.append)
    assert classifier.classify("t", "d", "x").is_tech
    assert len(session.sent) == 2 and any(abs(w - 9.4) < 0.01 for w in waits)  # waited the hinted 8.4s + 1s
    classifier.classify("t", "d", "x")
    assert waits[-1] > 4  # 12/min means at least ~5s between calls


def test_answers_are_saved_during_the_run_not_only_at_the_end(db, monkeypatch):
    import app.services.llm as llm

    monkeypatch.setattr(llm, "SAVE_EVERY", 1)

    class Crashes(Fake):
        def classify(self, title, department, description):
            if self.calls:
                raise KeyboardInterrupt  # the run dies after the first paid answer
            return super().classify(title, department, description)

    fake = Crashes({"Business Operations Analyst": Verdict(True, "Software", "x"), "Operations Specialist": Verdict(True, "Data", "y")})
    with pytest.raises(KeyboardInterrupt):
        run_llm_stage(db, fake)
    assert db.scalar("SELECT COUNT(*) FROM llm_labels") == 1


class FakeBatch(Fake):
    """A classifier that answers several postings per request, like Gemini."""

    batch_size = 10

    def __init__(self, answers):
        super().__init__(answers)
        self.requests = []

    def classify_batch(self, postings):
        self.requests.append([t for t, _d, _desc in postings])
        return [self.answers.get(t) for t, _d, _desc in postings]


def test_parse_batch_maps_answers_by_id_and_tolerates_gaps():
    raw = ('[{"id": 2, "is_tech": false, "role_family": "Not tech", "reason": "sales"},'
           ' {"id": 1, "is_tech": true, "role_family": "Data", "reason": "pipelines"}, {"id": 9, "is_tech": true},'
           ' {"id": 3, "is_tech": "maybe"}]')
    assert parse_batch(raw, 4) == [Verdict(True, "Data", "pipelines"), Verdict(False, "Not tech", "sales"), None, None]
    with pytest.raises(ValueError):
        parse_batch('{"is_tech": true}', 1)


def test_gemini_batch_sends_every_posting_in_one_request():
    reply = '[{"id": 1, "is_tech": true, "role_family": "Software", "reason": "a"}, {"id": 2, "is_tech": false, "reason": "b"}]'
    session = FakeSession(body=gemini_body(reply))
    verdicts = GeminiClassifier("k", "m", session=session).classify_batch([("Eng", "R&D", "x" * 5000), ("Sales", "", "y")])
    assert verdicts == [Verdict(True, "Software", "a"), Verdict(False, "Not tech", "b")]
    assert len(session.sent) == 1
    prompt = session.sent[0][1]["contents"][0]["parts"][0]["text"]
    assert "### Posting 1" in prompt and "### Posting 2" in prompt and "x" * 3001 not in prompt  # descriptions trimmed


def test_stage_batches_requests_and_asks_identical_postings_once(db, tmp_path):
    db.record_board("greenhouse", "acme", [  # the same posting in a second city
        job(1, "Software Engineer", TECH_TEXT), job(2, "Business Operations Analyst", TECH_TEXT),
        job(3, "Operations Analyst", OPS_TEXT), job(5, "Senior Business Analyst", TECH_TEXT),
        job(4, "Operations Specialist", "Own the data platform: design APIs, databases, data pipelines and backend services in Python."),
        Job(source="greenhouse", board="acme", company="Acme", ext_id="6", title="Business Operations Analyst",
            url="https://x/6", location="Austin, TX", description=TECH_TEXT),
    ], "2026-10-02T00:00:00+00:00")
    classify_all(db, CFG, tmp_path)
    fake = FakeBatch({"Business Operations Analyst": Verdict(False, "Not tech", "reporting"),
                      "Operations Specialist": None})  # left out of the reply
    stats = run_llm_stage(db, fake)
    assert fake.requests == [["Business Operations Analyst", "Operations Specialist"]]  # one request, no repeat
    assert stats["requests"] == 1 and stats["asked"] == 2 and stats["failed"] == 1
    rows = db.query("SELECT cs_evidence FROM jobs WHERE title = 'Business Operations Analyst'")
    assert len(rows) == 2 and all(r["cs_evidence"] == "llm: reporting" for r in rows)


def test_daily_quota_stops_at_once_without_retrying():
    class QuotaSession(FakeSession):
        def post(self, url, json=None, headers=None, timeout=None):
            self.sent.append(url)
            resp = FakeResponse(429, {})
            resp.text = "Quota exceeded ... GenerateRequestsPerDayPerProjectPerModel-FreeTier, retry in 10766s"
            return resp

    session, slept = QuotaSession(), []
    with pytest.raises(LLMUnavailable, match="daily"):
        GeminiClassifier("k", "m", session=session, sleep=slept.append).classify_batch([("t", "d", "x")])
    assert len(session.sent) == 1 and slept == []
