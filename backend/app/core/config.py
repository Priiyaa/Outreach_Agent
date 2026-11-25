"""Runtime settings, read from environment variables or backend/.env. The yaml files in config/ hold the
fetch targets and classifier tuning; this file holds only what changes between machines."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # Leave unset for the local SQLite file (db_path in config/config.yaml). In production set
    # DATABASE_URL=postgresql+psycopg2://user:pass@host/db
    database_url: Optional[str] = None
    # When set, every write (edits, bulk changes, fetch) needs `Authorization: Bearer <this>`. Reads stay open.
    # A shared access code, not real accounts: fine for a handful of people, replace with proper auth to scale.
    write_token: Optional[str] = None
    # Turn off the in-app fetch button on hosts that sleep (the scheduled GitHub Action does the fetching).
    allow_fetch: bool = True
    # Origins allowed to call the API from a browser (the React app). Comma-separated in the env var.
    cors_origins: list[str] = ["http://localhost:3000"]


settings = Settings()
