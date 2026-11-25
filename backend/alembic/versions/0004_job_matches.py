"""match score of each job against a candidate profile

Revision ID: 0004
Revises: 0003
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_matches",
        sa.Column("profile", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("reasons", sa.Text(), server_default="", nullable=False),
        sa.Column("scored_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("profile", "job_id"),
    )
    op.create_index("idx_job_matches_score", "job_matches", ["profile", "score"])


def downgrade() -> None:
    op.drop_index("idx_job_matches_score", table_name="job_matches")
    op.drop_table("job_matches")
