from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from .. import cli
from ..core.config import settings
from ..db.repository import DB, SPONSORSHIP_VALUES
from ..services.classify import EXPERIENCE_VALUES
from ..services.fetch_runner import fetch_runner
from ..services.match import SKILL_NAMES, load_active_profile, profile_from_dict, profile_to_dict, score_all
from ..services.resume import MAX_RESUME_BYTES, ResumeError, draft_profile, pdf_text
from ..services.views import (
    STATUS_LABELS,
    apply_job_edits,
    job_ids,
    job_stats,
    jobs_to_csv,
    query_jobs,
)
from . import schemas
from .deps import JobFilters, get_db, require_fetch_enabled, require_write_access

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/meta", response_model=schemas.Meta)
def meta():
    """The allowed values for every dropdown, so the frontend never hard-codes them."""
    return schemas.Meta(experience=EXPERIENCE_VALUES, sponsorship=list(SPONSORSHIP_VALUES),
                        status=STATUS_LABELS, writes_locked=bool(settings.write_token),
                        fetch_enabled=settings.allow_fetch)


@router.get("/auth/check", dependencies=[Depends(require_write_access)])
def check_access():
    """200 if the access code in the Authorization header is right (or none is needed), 401 otherwise."""
    return {"ok": True}


# ---- jobs ------------------------------------------------------------------------------------------------

@router.get("/jobs", response_model=schemas.JobsPage)
def list_jobs(filters: JobFilters = Depends(), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
              db: DB = Depends(get_db)):
    stats = schemas.JobStats(**job_stats(db, **filters.kwargs))
    rows = query_jobs(db, limit=limit, offset=offset, sort=filters.sort, **filters.kwargs)
    return schemas.JobsPage(stats=stats, limit=limit, offset=offset, rows=rows)


@router.get("/jobs.csv")
def export_jobs(filters: JobFilters = Depends(), db: DB = Depends(get_db)):
    return Response(jobs_to_csv(query_jobs(db, sort=filters.sort, **filters.kwargs)), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=jobs_filtered.csv"})


@router.patch("/jobs", response_model=schemas.Saved, dependencies=[Depends(require_write_access)])
def edit_jobs(edits: Dict[str, schemas.JobEdit], db: DB = Depends(get_db)):
    """Body: {job_id: {status?, sponsorship?, sponsorship_note?}}. All-or-nothing: bad values reject the lot."""
    try:
        saved = apply_job_edits(db, {k: v.model_dump(exclude_none=True) for k, v in edits.items()})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return schemas.Saved(saved=saved)


@router.post("/jobs/bulk-sponsorship", response_model=schemas.Saved, dependencies=[Depends(require_write_access)])
def bulk_sponsorship(body: schemas.BulkSponsorship, filters: JobFilters = Depends(), db: DB = Depends(get_db)):
    """Set Sponsors? on every job matching the filters (not just the page on screen)."""
    if body.value not in SPONSORSHIP_VALUES:
        raise HTTPException(status_code=422, detail=f"invalid sponsorship: {body.value!r}")
    return schemas.Saved(saved=db.bulk_set_sponsorship(job_ids(db, **filters.kwargs), body.value))


# ---- profile (what "Best match" ranks against) -----------------------------------------------------------

def _profile_state(db: DB) -> schemas.ProfileState:
    saved = db.saved_profile()
    profile = profile_from_dict(saved) if saved else load_active_profile(db, cli.ROOT)
    return schemas.ProfileState(
        profile=schemas.Profile(**profile_to_dict(profile)) if profile else None,
        source="board" if saved else "file" if profile else "none",
        known_skills=SKILL_NAMES, role_families=schemas.ROLE_FAMILIES,
    )


@router.get("/profile", response_model=schemas.ProfileState)
def get_profile(db: DB = Depends(get_db)):
    return _profile_state(db)


@router.post("/profile/resume", response_model=schemas.Profile, dependencies=[Depends(require_write_access)])
async def read_resume(request: Request, db: DB = Depends(get_db)):
    """Body: the resume PDF (raw bytes). Returns a draft profile to review; nothing is saved and the file is dropped."""
    data = await request.body()
    if len(data) > MAX_RESUME_BYTES:
        raise HTTPException(status_code=413, detail="The file is larger than 5 MB.")
    try:
        text = pdf_text(data)
    except ResumeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return schemas.Profile(**draft_profile(text, load_active_profile(db, cli.ROOT)))


@router.put("/profile", response_model=schemas.ProfileSaved, dependencies=[Depends(require_write_access)])
def save_profile(body: schemas.Profile, db: DB = Depends(get_db)):
    """Save the profile and re-rank every job against it."""
    current = load_active_profile(db, cli.ROOT)
    data = {"id": current.id if current else "me", **body.model_dump()}
    try:
        profile = profile_from_dict(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    bad = {k for k, v in body.role_weights.items() if k not in schemas.ROLE_FAMILIES or not 0 <= v <= 1}
    bad |= {k for k, v in body.skills.items() if not 1 <= v <= 3}
    if bad:
        raise HTTPException(status_code=422, detail=f"invalid weight for: {', '.join(sorted(bad))}")
    now = datetime.now(timezone.utc)
    db.save_profile(profile.id, profile_to_dict(profile), now.isoformat())
    return schemas.ProfileSaved(**score_all(db, profile, now))


# ---- fetching --------------------------------------------------------------------------------------------

@router.post("/fetch", response_model=schemas.FetchStatus, status_code=202,
             dependencies=[Depends(require_write_access), Depends(require_fetch_enabled)])
def start_fetch():
    if not fetch_runner.start():
        raise HTTPException(status_code=409, detail="A fetch is already running")
    return fetch_status()


@router.get("/fetch", response_model=schemas.FetchStatus)
def fetch_status():
    return schemas.FetchStatus(running=fetch_runner.running, output=fetch_runner.output, error=fetch_runner.error,
                               stage=fetch_runner.stage, results_ready=fetch_runner.results_ready)
