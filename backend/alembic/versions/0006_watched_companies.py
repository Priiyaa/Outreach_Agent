"""companies to keep checking, added when a job there is marked applied

Revision ID: 0006
Revises: 0005
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "watched_companies",
        sa.Column("company_key", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), server_default="", nullable=False),
        sa.Column("board", sa.Text(), server_default="", nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), server_default="applied", nullable=False),
        sa.Column("added_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("company_key", "source", "board"),
    )


def downgrade() -> None:
    op.drop_table("watched_companies")
