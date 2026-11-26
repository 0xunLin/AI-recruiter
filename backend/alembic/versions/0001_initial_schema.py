"""Initial relational and pgvector HNSW schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-25 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa

from app.config import get_settings

revision: str = "0001_initial_schema"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = get_settings().embedding_dim


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("api_key_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("slug"),
        sa.UniqueConstraint("api_key_hash"),
    )
    op.create_index("ix_companies_slug", "companies", ["slug"])
    op.create_index("ix_companies_api_key_hash", "companies", ["api_key_hash"])

    op.create_table(
        "candidates",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("github_url", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_candidates_email", "candidates", ["email"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "company_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("rubric", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_jobs_company_id", "jobs", ["company_id"])

    op.create_table(
        "repositories",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "candidate_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("repo_url", sa.String(length=500), nullable=False),
        sa.Column("default_branch", sa.String(length=120), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("candidate_id", "repo_url", name="uq_candidate_repo_url"),
    )
    op.create_index("ix_repositories_candidate_id", "repositories", ["candidate_id"])

    op.create_table(
        "applications",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "company_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "repository_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("evaluation_report", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "candidate_id", name="uq_application_job_candidate"),
    )
    op.create_index("ix_applications_company_id", "applications", ["company_id"])
    op.create_index("ix_applications_job_id", "applications", ["job_id"])
    op.create_index("ix_applications_candidate_id", "applications", ["candidate_id"])
    op.create_index("ix_applications_repository_id", "applications", ["repository_id"])
    op.create_index("ix_applications_status", "applications", ["status"])

    op.create_table(
        "code_chunks",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "repository_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_path", sa.String(length=600), nullable=False),
        sa.Column("symbol_name", sa.String(length=255), nullable=False, server_default="<module>"),
        sa.Column("symbol_type", sa.String(length=64), nullable=False, server_default="block"),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(EMBEDDING_DIM), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_code_chunks_repository_id", "code_chunks", ["repository_id"])
    op.create_index("ix_code_chunks_repo_file", "code_chunks", ["repository_id", "file_path"])
    op.execute(
        "CREATE INDEX ix_code_chunks_embedding_hnsw ON code_chunks "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.drop_index("ix_code_chunks_embedding_hnsw", table_name="code_chunks")
    op.drop_index("ix_code_chunks_repo_file", table_name="code_chunks")
    op.drop_index("ix_code_chunks_repository_id", table_name="code_chunks")
    op.drop_table("code_chunks")
    op.drop_index("ix_applications_status", table_name="applications")
    op.drop_index("ix_applications_repository_id", table_name="applications")
    op.drop_index("ix_applications_candidate_id", table_name="applications")
    op.drop_index("ix_applications_job_id", table_name="applications")
    op.drop_index("ix_applications_company_id", table_name="applications")
    op.drop_table("applications")
    op.drop_index("ix_repositories_candidate_id", table_name="repositories")
    op.drop_table("repositories")
    op.drop_index("ix_jobs_company_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_candidates_email", table_name="candidates")
    op.drop_table("candidates")
    op.drop_index("ix_companies_api_key_hash", table_name="companies")
    op.drop_index("ix_companies_slug", table_name="companies")
    op.drop_table("companies")
