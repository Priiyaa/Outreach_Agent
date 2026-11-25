from __future__ import annotations

import hashlib
from dataclasses import dataclass

# Sources that fetch a company's own job board (full descriptions, authoritative).
# Everything else (simplify, jobright) is a curated list that points at postings.
DIRECT_SOURCES = ("greenhouse", "lever", "ashby", "workday")


@dataclass
class Job:
    source: str  # greenhouse | lever | ashby | workday | simplify | jobright
    board: str  # the company's slug on that ATS, or the list's id for curated lists
    company: str  # display name
    ext_id: str  # the posting's id at that source
    title: str
    url: str
    location: str = ""
    department: str = ""
    remote: bool = False
    posted_at: str | None = None  # YYYY-MM-DD, best effort (some sources only expose updated time)
    description: str = ""  # plain text; empty for curated lists, which don't carry descriptions
    notes: str = ""  # extra facts from curated lists (sponsorship, degrees, work model)
    ats_ref: str | None = None  # "source:slug:id" of the underlying ATS posting, used to hide duplicates

    def __post_init__(self) -> None:
        if self.ats_ref is None and self.source in DIRECT_SOURCES:
            self.ats_ref = f"{self.source}:{self.board}:{self.ext_id}".lower()

    @property
    def id(self) -> str:
        """Stable id so re-fetching the same posting never creates a duplicate."""
        key = f"{self.source}:{self.board}:{self.ext_id}"
        return hashlib.sha1(key.encode()).hexdigest()[:16]
