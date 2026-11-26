"""Add provenance_tier, commit_count, selected_commits, selected_files, and ownership defense columns.

Revision ID: 0005_provenance_probes_evidence
Revises: 0004_dual_role_auth
Create Date: 2026-11-26 05:06:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_provenance_probes_evidence"
down_revision: Union[str, Sequence[str], None] = "0004_dual_role_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "repositories",
        sa.Column("provenance_tier", sa.String(length=32), nullable=False, server_default="unknown"),
    )
    op.add_column("repositories", sa.Column("commit_count", sa.Integer(), nullable=True))

    op.add_column(
        "resume_claims",
        sa.Column("provenance_tier", sa.String(length=32), nullable=False, server_default="unknown"),
    )
    op.add_column("resume_claims", sa.Column("selected_commits", sa.JSON(), nullable=True))
    op.add_column("resume_claims", sa.Column("selected_files", sa.JSON(), nullable=True))
    op.add_column("resume_claims", sa.Column("ownership_question", sa.Text(), nullable=True))
    op.add_column("resume_claims", sa.Column("ownership_answer", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("resume_claims", "ownership_answer")
    op.drop_column("resume_claims", "ownership_question")
    op.drop_column("resume_claims", "selected_files")
    op.drop_column("resume_claims", "selected_commits")
    op.drop_column("resume_claims", "provenance_tier")
    op.drop_column("repositories", "commit_count")
    op.drop_column("repositories", "provenance_tier")
