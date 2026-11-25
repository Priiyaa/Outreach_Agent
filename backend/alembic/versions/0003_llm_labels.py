"""cache for LLM verdicts, and a role family on each job

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_labels",
        sa.Column("hash", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("is_tech", sa.Integer(), nullable=False),
        sa.Column("role_family", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("hash", "model"),
    )
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("role_family", sa.Text(), server_default="", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("role_family")
    op.drop_table("llm_labels")
