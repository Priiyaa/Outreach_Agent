from __future__ import annotations

import html
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser

import requests

from ..domain import Job


class NotFound(Exception):
    """The board slug (or list file) does not exist."""


RETRY_STATUSES = {429, 500, 502, 503, 504}


def get_response(session: requests.Session, url: str, params: dict | None = None,
                 timeout: float = 30, attempts: int = 4, json_body: dict | None = None) -> requests.Response:
    """GET (or POST when json_body is given) with retries on network errors and 429/5xx (exponential backoff).
    404 -> NotFound."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            if json_body is not None:
                resp = session.post(url, json=json_body, params=params, timeout=timeout)
            else:
                resp = session.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:  # connection errors, timeouts
            last = exc
        else:
            if resp.status_code == 404:
                raise NotFound(url)
            if resp.status_code not in RETRY_STATUSES:
                resp.raise_for_status()
                return resp
            last = requests.HTTPError(f"{resp.status_code} from {url}", response=resp)
        if attempt < attempts - 1:
            time.sleep(min(2 ** attempt, 20))
    raise last  # type: ignore[misc]


def get_json(session: requests.Session, url: str, params: dict | None = None,
             timeout: float = 30, attempts: int = 4):
    return get_response(session, url, params, timeout, attempts).json()


def get_text(session: requests.Session, url: str, params: dict | None = None,
             timeout: float = 30, attempts: int = 4) -> str:
    resp = get_response(session, url, params, timeout, attempts)
    resp.encoding = resp.encoding or "utf-8"
    return resp.text


_BLOCK_TAGS = {"p", "div", "br", "ul", "ol", "tr", "section", "h1", "h2", "h3", "h4", "h5", "h6"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "li":
            self.out.append("\n- ")
        elif tag in _BLOCK_TAGS:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag == "li" or tag in _BLOCK_TAGS:
            self.out.append("\n")

    def handle_data(self, data):
        self.out.append(data)


def html_to_text(raw: str | None, escaped: bool = False) -> str:
    """HTML -> readable plain text. Greenhouse returns HTML that is itself entity-escaped (escaped=True)."""
    if not raw:
        return ""
    if escaped:
        raw = html.unescape(raw)
    parser = _TextExtractor()
    parser.feed(raw)
    parser.close()
    text = "".join(parser.out).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def to_date(value) -> str | None:
    """Normalize ISO strings and epoch-millisecond ints to YYYY-MM-DD."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date().isoformat()
    text = str(value)
    return text[:10] if re.match(r"\d{4}-\d{2}-\d{2}", text) else None


class Source:
    """One data source. fetch() takes a config entry (companies.yaml / lists.yaml) and returns normalized jobs."""

    name: str = ""

    def __init__(self, session: requests.Session, timeout: float = 30) -> None:
        self.session = session
        self.timeout = timeout

    def get(self, url: str, params: dict | None = None):
        return get_json(self.session, url, params, self.timeout)

    def post(self, url: str, body: dict):
        return get_response(self.session, url, None, self.timeout, json_body=body).json()

    def get_text(self, url: str, params: dict | None = None) -> str:
        return get_text(self.session, url, params, self.timeout)

    def fetch(self, entry: dict) -> list[Job]:
        raise NotImplementedError
