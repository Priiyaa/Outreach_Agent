"""Copy every table from one database to another (for example the local SQLite file to hosted Postgres)."""
from __future__ import annotations

from typing import Callable, Optional

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine

from .models import Base

CHUNK = 2000


def copy_database(source_url: str, target_url: str, progress: Optional[Callable[[str, int, int], None]] = None) -> dict:
    """Copy all rows into a target that already has the schema (run `alembic upgrade head` on it first).
    Refuses a target that already has data, so a re-run can never duplicate or overwrite rows."""
    source, target = create_engine(source_url), create_engine(target_url, pool_pre_ping=True)
    tables = list(Base.metadata.sorted_tables)  # parents before children
    with target.connect() as conn:
        for table in tables:
            if conn.execute(select(func.count()).select_from(table)).scalar():
                raise RuntimeError(f"target table {table.name} already has rows; refusing to copy over it")
    copied: dict[str, int] = {}
    for table in tables:
        total = _count(source, table)
        done = 0
        with source.connect() as src:
            result = src.execution_options(stream_results=True).execute(select(table))
            while rows := result.mappings().fetchmany(CHUNK):
                with target.begin() as dst:
                    dst.execute(table.insert(), [dict(r) for r in rows])
                done += len(rows)
                if progress:
                    progress(table.name, done, total)
        copied[table.name] = done
    _reset_sequences(target)
    for table in tables:  # verify, don't trust
        if _count(target, table) != copied[table.name]:
            raise RuntimeError(f"row count mismatch in {table.name} after copy")
    return copied


def _count(engine: Engine, table) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar() or 0


def _reset_sequences(engine: Engine) -> None:
    """Postgres only: after inserting explicit ids, move the id counters past them or the next insert collides."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text(
            "SELECT setval(pg_get_serial_sequence('fetch_log', 'id'), COALESCE((SELECT MAX(id) FROM fetch_log), 0) + 1, false)"
        ))
