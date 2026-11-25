"""store the CS-role label on each job

Revision ID: 0002
Revises: 0001

Computing it per query meant scanning every description (about 16 s for 43k jobs). The classifier now
writes it once. Existing rows stay NULL until `python -m app.cli classify` fills them in.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("is_cs_role", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("cs_evidence", sa.Text(), server_default="", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("cs_evidence")
        batch_op.drop_column("is_cs_role")
