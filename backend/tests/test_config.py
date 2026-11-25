from app.core.config import Settings, parse_origins

ONE, TWO = "https://outreach.vercel.app", "http://localhost:3100"


def test_cors_origins_accept_every_common_form():
    for value in (f'["{ONE}"]', ONE, f"{ONE}/", f' "{ONE}" ', f"['{ONE}']"):
        assert parse_origins(value) == [ONE], value
    for value in (f'["{ONE}", "{TWO}"]', f"{ONE},{TWO}", f"{ONE}, {TWO}/", f"[{ONE}, {TWO}]"):
        assert parse_origins(value) == [ONE, TWO], value
    assert parse_origins("") == []


def test_settings_start_with_a_plain_url_in_the_environment(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", ONE)  # used to fail start-up: a list setting only took JSON
    assert Settings().cors_origin_list == [ONE]
