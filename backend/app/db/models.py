"""Table definitions. Alembic reads these to build migrations; edit here, then run `alembic revision --autogenerate`."""
from typing import Optional

from sqlalchemy import Index, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("idx_jobs_board", "source", "board"),
        Index("idx_jobs_first_seen", "first_seen"),
        Index("idx_jobs_ats_ref", "ats_ref"),
        Index("idx_jobs_company_key", "company_key"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    board: Mapped[str] = mapped_column(Text)
    company: Mapped[str] = mapped_column(Text)
    ext_id: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(Text, default="", server_default="")
    department: Mapped[str] = mapped_column(Text, default="", server_default="")
    remote: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    posted_at: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    ats_ref: Mapped[Optional[str]] = mapped_column(Text)
    experience: Mapped[str] = mapped_column(Text, default="Unclear", server_default="Unclear")
    exp_reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    is_us: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    is_internship: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    company_key: Mapped[Optional[str]] = mapped_column(Text)
    sponsorship: Mapped[str] = mapped_column(Text, default="Unknown", server_default="Unknown")
    sponsorship_source: Mapped[str] = mapped_column(Text, default="auto", server_default="auto")
    sponsorship_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    # NULL = not evaluated yet. Set by the classifier so queries never have to read descriptions.
    is_cs_role: Mapped[Optional[int]] = mapped_column(Integer)
    cs_evidence: Mapped[str] = mapped_column(Text, default="", server_default="")
    role_family: Mapped[str] = mapped_column(Text, default="", server_default="")
    classified_at: Mapped[Optional[str]] = mapped_column(Text)
    first_seen: Mapped[str] = mapped_column(Text)
    last_seen: Mapped[str] = mapped_column(Text)
    closed_at: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="new", server_default="new")


class FetchLogRow(Base):
    __tablename__ = "fetch_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_ts: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    board: Mapped[str] = mapped_column(Text)
    ok: Mapped[int] = mapped_column(Integer)
    n_jobs: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[Optional[str]] = mapped_column(Text)


class CompanyRow(Base):
    """One row per company (keyed by normalized name). size_source says where the size came from:
    seed | text | openings | claude | unknown | default | manual"""

    __tablename__ = "companies"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    size: Mapped[str] = mapped_column(Text)
    employees: Mapped[Optional[int]] = mapped_column(Integer)
    size_source: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text)


class LlmLabelRow(Base):
    """Cached LLM verdicts, keyed by a hash of the posting text so identical descriptions are paid for once."""

    __tablename__ = "llm_labels"

    hash: Mapped[str] = mapped_column(Text, primary_key=True)
    model: Mapped[str] = mapped_column(Text, primary_key=True)
    is_tech: Mapped[int] = mapped_column(Integer)
    role_family: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[str] = mapped_column(Text)


class JobMatchRow(Base):
    """How well each open job fits a candidate profile (services.match). Replaced whole on every scoring run."""

    __tablename__ = "job_matches"
    __table_args__ = (Index("idx_job_matches_score", "profile", "score"),)

    profile: Mapped[str] = mapped_column(Text, primary_key=True)
    job_id: Mapped[str] = mapped_column(Text, primary_key=True)
    score: Mapped[int] = mapped_column(Integer)
    reasons: Mapped[str] = mapped_column(Text, default="", server_default="")
    scored_at: Mapped[str] = mapped_column(Text)


class ProfileRow(Base):
    """The match profile saved from the board (resume upload + edits). Wins over PROFILE_YAML and config/profile.yaml."""

    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    data: Mapped[str] = mapped_column(Text)  # JSON of services.match.Profile
    updated_at: Mapped[str] = mapped_column(Text)


class WatchedCompanyRow(Base):
    """Companies whose boards the fetch keeps checking, added when a job there is marked applied (services.watch).
    board is "" when the company's career site isn't one the app can read (only its name is kept)."""

    __tablename__ = "watched_companies"

    company_key: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text, primary_key=True, default="", server_default="")
    board: Mapped[str] = mapped_column(Text, primary_key=True, default="", server_default="")
    name: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, default="applied", server_default="applied")
    added_at: Mapped[str] = mapped_column(Text)


class CompanyTagRow(Base):
    """Labels on a company, e.g. tag "yc" with detail "W24" (filled from config/companies.yc.yaml on every fetch)."""

    __tablename__ = "company_tags"

    company_key: Mapped[str] = mapped_column(Text, primary_key=True)
    tag: Mapped[str] = mapped_column(Text, primary_key=True)
    detail: Mapped[str] = mapped_column(Text, default="", server_default="")


class MatchLabelRow(Base):
    """Your verdict on a ranked job ("good" or "bad"), used to check and tune the match weights (services.tune)."""

    __tablename__ = "match_labels"

    profile: Mapped[str] = mapped_column(Text, primary_key=True)
    job_id: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text)
