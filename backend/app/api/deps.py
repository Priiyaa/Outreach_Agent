import hmac
from functools import lru_cache
from typing import List, Literal, Optional

from fastapi import Depends, Header, HTTPException, Query

from .. import cli
from ..core.config import settings
from ..db.repository import DB
from ..db.session import open_db
from ..services.match import load_active_profile


@lru_cache(maxsize=1)
def get_db() -> DB:
    """One engine (and connection pool) for the whole process."""
    return open_db(cli.load_yaml("config.yaml")["db_path"], cli.ROOT)


def active_profile_id(db: DB = Depends(get_db)) -> str:
    """Whose match scores the board shows. One profile for now; per-user accounts would pick it from the login."""
    profile = load_active_profile(db, cli.ROOT)
    return profile.id if profile else ""


class JobFilters:
    """Query-string filters for the jobs list; names match the arguments of services.views.query_jobs."""

    def __init__(
        self,
        experience: Optional[List[str]] = Query(None),
        sponsorship: Optional[List[str]] = Query(None),
        status: Optional[List[str]] = Query(None),
        cs_only: bool = True,
        us_only: bool = True,
        internships: bool = False,
        closed: bool = False,
        search: str = "",
        location: str = "",
        since_days: int = Query(0, ge=0),
        sort: Literal["newest", "match"] = "newest",
        min_score: int = Query(0, ge=0, le=100),
        watched: bool = False,
        yc: bool = False,
        profile_id: str = Depends(active_profile_id),
    ) -> None:
        self.sort = sort
        self.kwargs = dict(
            experience=experience, sponsorship=sponsorship, status=status,
            cs_related_only=cs_only, us_only=us_only, include_internships=internships,
            include_closed=closed, search=search, location=location, since_days=since_days or None,
            profile=profile_id, matches_only=sort == "match", min_score=min_score,
            watched_only=watched, yc_only=yc,
        )


def require_write_access(authorization: Optional[str] = Header(None)) -> None:
    """Lock writes behind WRITE_TOKEN when one is configured. Compared in constant time."""
    token = settings.write_token
    if token and not (authorization and hmac.compare_digest(authorization, f"Bearer {token}")):
        raise HTTPException(status_code=401, detail="Editing is locked. Enter the access code.")


def require_fetch_enabled() -> None:
    if not settings.allow_fetch:
        raise HTTPException(status_code=403, detail="Fetching is done by the scheduled job on this deployment.")
