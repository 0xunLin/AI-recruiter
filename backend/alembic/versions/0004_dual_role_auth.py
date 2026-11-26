"""Add separate recruiters, magic_link_tokens, company_invites, and GitHub OAuth candidate columns.

Revision ID: 0004_dual_role_auth
Revises: 0003_resume_claims_and_scoring
Create Date: 2026-11-25 21:45:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_dual_role_auth"
down_revision: Union[str, Sequence[str], None] = "0003_resume_claims_and_scoring"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recruiters",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "company_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("google_sub", sa.String(length=255), nullable=True),
        sa.Column("auth_provider", sa.String(length=32), nullable=False, server_default="magic_link"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("google_sub"),
    )
    op.create_index("ix_recruiters_company_id", "recruiters", ["company_id"])
    op.create_index("ix_recruiters_email", "recruiters", ["email"])
    op.create_index("ix_recruiters_google_sub", "recruiters", ["google_sub"])

    op.create_table(
        "magic_link_tokens",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=True),
        sa.Column("invite_token_hash", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_magic_link_tokens_email", "magic_link_tokens", ["email"])
    op.create_index("ix_magic_link_tokens_token_hash", "magic_link_tokens", ["token_hash"])

    op.create_table(
        "company_invites",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "company_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "invited_by_recruiter_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("recruiters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("invited_email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_company_invites_company_id", "company_invites", ["company_id"])
    op.create_index("ix_company_invites_invited_email", "company_invites", ["invited_email"])
    op.create_index("ix_company_invites_token_hash", "company_invites", ["token_hash"])

    op.add_column(
        "jobs",
        sa.Column(
            "created_by_recruiter_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("recruiters.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "jobs",
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_jobs_created_by_recruiter_id", "jobs", ["created_by_recruiter_id"])
    op.create_index("ix_jobs_is_public", "jobs", ["is_public"])

    op.add_column("candidates", sa.Column("github_id", sa.String(length=64), nullable=True))
    op.add_column("candidates", sa.Column("github_handle", sa.String(length=120), nullable=True))
    op.add_column("candidates", sa.Column("verified_emails", sa.JSON(), nullable=True))
    op.create_unique_constraint("uq_candidates_github_id", "candidates", ["github_id"])
    op.create_index("ix_candidates_github_id", "candidates", ["github_id"])
    op.create_index("ix_candidates_github_handle", "candidates", ["github_handle"])


def downgrade() -> None:
    op.drop_index("ix_candidates_github_handle", table_name="candidates")
    op.drop_index("ix_candidates_github_id", table_name="candidates")
    op.drop_constraint("uq_candidates_github_id", "candidates", type_="unique")
    op.drop_column("candidates", "verified_emails")
    op.drop_column("candidates", "github_handle")
    op.drop_column("candidates", "github_id")

    op.drop_index("ix_jobs_is_public", table_name="jobs")
    op.drop_index("ix_jobs_created_by_recruiter_id", table_name="jobs")
    op.drop_column("jobs", "is_public")
    op.drop_column("jobs", "created_by_recruiter_id")

    op.drop_index("ix_company_invites_token_hash", table_name="company_invites")
    op.drop_index("ix_company_invites_invited_email", table_name="company_invites")
    op.drop_index("ix_company_invites_company_id", table_name="company_invites")
    op.drop_table("company_invites")

    op.drop_index("ix_magic_link_tokens_token_hash", table_name="magic_link_tokens")
    op.drop_index("ix_magic_link_tokens_email", table_name="magic_link_tokens")
    op.drop_table("magic_link_tokens")

    op.drop_index("ix_recruiters_google_sub", table_name="recruiters")
    op.drop_index("ix_recruiters_email", table_name="recruiters")
    op.drop_index("ix_recruiters_company_id", table_name="recruiters")
    op.drop_table("recruiters")
