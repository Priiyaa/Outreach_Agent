"""Which database to open: DATABASE_URL if set (production), else the SQLite file named in config.yaml."""
from __future__ import annotations

from pathlib import Path

from ..core.config import BACKEND_DIR, settings
from .repository import DB


def database_url(db_path: str, root: Path = BACKEND_DIR) -> str:
    return settings.database_url or f"sqlite:///{root / db_path}"


def open_db(db_path: str, root: Path = BACKEND_DIR) -> DB:
    return DB(database_url(db_path, root))
