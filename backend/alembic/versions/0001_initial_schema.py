"""initial schema (the tables as they were before CS-role labels were stored)

Revision ID: 0001
Revises: 
Create Date: 2026-10-20 15:44:41.953242

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('companies',
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('size', sa.Text(), nullable=False),
    sa.Column('employees', sa.Integer(), nullable=True),
    sa.Column('size_source', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('fetch_log',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('run_ts', sa.Text(), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('board', sa.Text(), nullable=False),
    sa.Column('ok', sa.Integer(), nullable=False),
    sa.Column('n_jobs', sa.Integer(), server_default='0', nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('jobs',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('board', sa.Text(), nullable=False),
    sa.Column('company', sa.Text(), nullable=False),
    sa.Column('ext_id', sa.Text(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('location', sa.Text(), server_default='', nullable=False),
    sa.Column('department', sa.Text(), server_default='', nullable=False),
    sa.Column('remote', sa.Integer(), server_default='0', nullable=False),
    sa.Column('posted_at', sa.Text(), nullable=True),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('notes', sa.Text(), server_default='', nullable=False),
    sa.Column('ats_ref', sa.Text(), nullable=True),
    sa.Column('experience', sa.Text(), server_default='Unclear', nullable=False),
    sa.Column('exp_reason', sa.Text(), server_default='', nullable=False),
    sa.Column('is_us', sa.Integer(), server_default='1', nullable=False),
    sa.Column('is_internship', sa.Integer(), server_default='0', nullable=False),
    sa.Column('company_key', sa.Text(), nullable=True),
    sa.Column('sponsorship', sa.Text(), server_default='Unknown', nullable=False),
    sa.Column('sponsorship_source', sa.Text(), server_default='auto', nullable=False),
    sa.Column('sponsorship_note', sa.Text(), server_default='', nullable=False),
    sa.Column('classified_at', sa.Text(), nullable=True),
    sa.Column('first_seen', sa.Text(), nullable=False),
    sa.Column('last_seen', sa.Text(), nullable=False),
    sa.Column('closed_at', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), server_default='new', nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.create_index('idx_jobs_ats_ref', ['ats_ref'], unique=False)
        batch_op.create_index('idx_jobs_board', ['source', 'board'], unique=False)
        batch_op.create_index('idx_jobs_company_key', ['company_key'], unique=False)
        batch_op.create_index('idx_jobs_first_seen', ['first_seen'], unique=False)



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_index('idx_jobs_first_seen')
        batch_op.drop_index('idx_jobs_company_key')
        batch_op.drop_index('idx_jobs_board')
        batch_op.drop_index('idx_jobs_ats_ref')

    op.drop_table('jobs')
    op.drop_table('fetch_log')
    op.drop_table('companies')
