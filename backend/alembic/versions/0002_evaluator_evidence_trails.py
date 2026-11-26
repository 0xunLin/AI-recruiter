"""Add evidence_hash and tool_call_log audit trail columns to applications.

Revision ID: 0002_evaluator_evidence_trails
Revises: 0001_initial_schema
Create Date: 2026-11-25 05:15:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_evaluator_evidence_trails"
down_revision: Union[str, Sequence[str], None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("applications", sa.Column("tool_call_log", sa.JSON(), nullable=True))
    op.add_column("applications", sa.Column("evidence_hash", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("applications", "evidence_hash")
    op.drop_column("applications", "tool_call_log")
