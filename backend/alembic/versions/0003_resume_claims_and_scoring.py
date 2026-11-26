"""Add resume, resume_claims, multi-repo join, authorship, and 0-10 shortlist scoring.

Revision ID: 0003_resume_claims_and_scoring
Revises: 0002_evaluator_evidence_trails
Create Date: 2026-11-25 20:35:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_resume_claims_and_scoring"
down_revision: Union[str, Sequence[str], None] = "0002_evaluator_evidence_trails"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "resumes",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "candidate_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(length=255), nullable=False, server_default="resume.txt"),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("parsed_projects", sa.JSON(), nullable=True),
        sa.Column("extracted_links", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_resumes_candidate_id", "resumes", ["candidate_id"])

    op.add_column(
        "repositories",
        sa.Column("link_kind", sa.String(length=32), nullable=False, server_default="repo"),
    )
    op.add_column("repositories", sa.Column("author_identities", sa.JSON(), nullable=True))

    op.add_column(
        "applications",
        sa.Column(
            "resume_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("resumes.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("applications", sa.Column("score_out_of_10", sa.Float(), nullable=True))
    op.add_column("applications", sa.Column("score_breakdown", sa.JSON(), nullable=True))
    op.add_column("applications", sa.Column("percentile_rank", sa.Float(), nullable=True))
    op.add_column(
        "applications",
        sa.Column("is_shortlisted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_applications_resume_id", "applications", ["resume_id"])
    op.create_index("ix_applications_score_out_of_10", "applications", ["score_out_of_10"])
    op.create_index("ix_applications_is_shortlisted", "applications", ["is_shortlisted"])

    op.create_table(
        "application_repositories",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "application_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "repository_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("application_id", "repository_id", name="uq_app_repo"),
    )
    op.create_index("ix_application_repositories_application_id", "application_repositories", ["application_id"])
    op.create_index("ix_application_repositories_repository_id", "application_repositories", ["repository_id"])

    op.create_table(
        "resume_claims",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "application_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "repository_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("project_title", sa.String(length=255), nullable=False),
        sa.Column("claimed_contribution", sa.Text(), nullable=False),
        sa.Column("target_url", sa.String(length=500), nullable=True),
        sa.Column("link_kind", sa.String(length=32), nullable=False, server_default="none"),
        sa.Column("verification_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("claim_score", sa.Float(), nullable=True),
        sa.Column("authorship_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("authorship_note", sa.String(length=300), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("referenced_files", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_resume_claims_application_id", "resume_claims", ["application_id"])
    op.create_index("ix_resume_claims_repository_id", "resume_claims", ["repository_id"])


def downgrade() -> None:
    op.drop_index("ix_resume_claims_repository_id", table_name="resume_claims")
    op.drop_index("ix_resume_claims_application_id", table_name="resume_claims")
    op.drop_table("resume_claims")

    op.drop_index("ix_application_repositories_repository_id", table_name="application_repositories")
    op.drop_index("ix_application_repositories_application_id", table_name="application_repositories")
    op.drop_table("application_repositories")

    op.drop_index("ix_applications_is_shortlisted", table_name="applications")
    op.drop_index("ix_applications_score_out_of_10", table_name="applications")
    op.drop_index("ix_applications_resume_id", table_name="applications")
    op.drop_column("applications", "is_shortlisted")
    op.drop_column("applications", "percentile_rank")
    op.drop_column("applications", "score_breakdown")
    op.drop_column("applications", "score_out_of_10")
    op.drop_column("applications", "resume_id")

    op.drop_column("repositories", "author_identities")
    op.drop_column("repositories", "link_kind")

    op.drop_index("ix_resumes_candidate_id", table_name="resumes")
    op.drop_table("resumes")
