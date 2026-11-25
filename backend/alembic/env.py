"""Alembic environment. The database comes from DATABASE_URL, or the SQLite file named in config/config.yaml."""
import yaml
from sqlalchemy import create_engine

from alembic import context
from app.core.config import BACKEND_DIR
from app.db.models import Base
from app.db.session import database_url

config = context.config
target_metadata = Base.metadata


def get_url() -> str:
    cfg = yaml.safe_load((BACKEND_DIR / "config" / "config.yaml").read_text())
    return database_url(cfg["db_path"])


def run_migrations_offline() -> None:
    context.configure(url=get_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(get_url())
    with engine.connect() as connection:
        # batch mode lets SQLite apply ALTERs it cannot do natively; it is a no-op on Postgres
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
