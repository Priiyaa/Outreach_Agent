"""Request and response shapes. These are the API contract the React app is typed against."""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class Job(BaseModel):
    id: str
    company: str
    title: str
    location: str
    cs_role_evidence: str
    role_family: str
    experience: str
    sponsorship: str
    sponsorship_note: str
    status: str
    url: str
    first_seen: str  # when this tracker first saw the posting
    posted_at: Optional[str] = None  # when the company posted it, as the source reports it
    match_score: Optional[int] = None  # 0-100 fit with the profile; None = not a fit (or no profile yet)
    match_reasons: str = ""


class JobStats(BaseModel):
    total: int
    new_grad: int
    sponsor_yes: int
    not_applied: int


class JobsPage(BaseModel):
    stats: JobStats
    limit: int
    offset: int
    rows: List[Job]


class JobEdit(BaseModel):
    status: Optional[str] = None
    sponsorship: Optional[str] = None
    sponsorship_note: Optional[str] = None


class BulkSponsorship(BaseModel):
    value: str


class Saved(BaseModel):
    saved: int


class Meta(BaseModel):
    experience: List[str]
    sponsorship: List[str]
    status: Dict[str, str]
    writes_locked: bool
    fetch_enabled: bool


class FetchStatus(BaseModel):
    running: bool
    output: str
    error: Optional[str]
    stage: str = ""  # what the running fetch is doing now
    results_ready: bool = False  # new jobs are classified and ranked; the board can refresh before the run ends


ROLE_FAMILIES = ["ai", "software", "ml", "research", "data", "other"]


class Profile(BaseModel):
    """The match profile. Skills are weighted 1 (nice to have) to 3 (core); role weights are 0 to 1."""

    years_experience: int = Field(0, ge=0, le=40)
    max_years_required: int = Field(2, ge=0, le=40)
    needs_sponsorship: bool = True
    has_phd: bool = False
    preferred_locations: List[str] = Field(default_factory=list, max_length=20)
    role_weights: Dict[str, float] = Field(default_factory=dict)
    skills: Dict[str, int] = Field(default_factory=dict)


class ProfileState(BaseModel):
    profile: Optional[Profile]
    source: str  # "board" (saved here), "file" (PROFILE_YAML or config/profile.yaml) or "none"
    known_skills: List[str]
    role_families: List[str]


class ProfileSaved(BaseModel):
    scored: int
    strong: int
    ineligible: int
