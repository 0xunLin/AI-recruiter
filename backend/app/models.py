import uuid
from datetime import datetime, timezone
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import get_settings
from app.database import Base

EMBEDDING_DIM = get_settings().embedding_dim


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Company(Base):
    """Multi-tenant organization owning jobs, recruiters, and applications."""

    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    recruiters: Mapped[list["Recruiter"]] = relationship(
        "Recruiter", back_populates="company", cascade="all, delete-orphan"
    )
    jobs: Mapped[list["Job"]] = relationship("Job", back_populates="company", cascade="all, delete-orphan")
    applications: Mapped[list["Application"]] = relationship(
        "Application", back_populates="company", cascade="all, delete-orphan"
    )


class Recruiter(Base):
    """
    Physically separate Recruiter identity table (Gmail OAuth or Magic Link only).
    Dual-layer RBAC: applicant UUIDs do not exist in this table and are rejected by FKs.
    """

    __tablename__ = "recruiters"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    auth_provider: Mapped[str] = mapped_column(String(32), default="magic_link", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    company: Mapped["Company"] = relationship("Company", back_populates="recruiters")
    jobs: Mapped[list["Job"]] = relationship("Job", back_populates="created_by_recruiter")


class MagicLinkToken(Base):
    """Single-use SHA-256 hashed magic-link token for Recruiter passwordless login."""

    __tablename__ = "magic_link_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    company_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    invite_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CompanyInvite(Base):
    """Explicit teammate invite preventing automatic @gmail.com tenant merging."""

    __tablename__ = "company_invites"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invited_by_recruiter_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("recruiters.id", ondelete="CASCADE"), nullable=False
    )
    invited_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Job(Base):
    """Job description with an extracted 5-point technical evaluation rubric."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_recruiter_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("recruiters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    rubric: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    company: Mapped["Company"] = relationship("Company", back_populates="jobs")
    created_by_recruiter: Mapped["Recruiter | None"] = relationship("Recruiter", back_populates="jobs")
    applications: Mapped[list["Application"]] = relationship(
        "Application", back_populates="job", cascade="all, delete-orphan"
    )


class Candidate(Base):
    """
    Physically separate Applicant identity table (GitHub OAuth only).
    Dual-layer RBAC: recruiter UUIDs do not exist here and applicants cannot access recruiter rows.
    """

    __tablename__ = "candidates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    github_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    github_handle: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    github_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    verified_emails: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    applications: Mapped[list["Application"]] = relationship(
        "Application", back_populates="candidate", cascade="all, delete-orphan"
    )
    repositories: Mapped[list["Repository"]] = relationship(
        "Repository", back_populates="candidate", cascade="all, delete-orphan"
    )
    resumes: Mapped[list["Resume"]] = relationship(
        "Resume", back_populates="candidate", cascade="all, delete-orphan"
    )


class Resume(Base):
    """Parsed candidate resume text, extracted projects, and GitHub links."""

    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), default="resume.txt", nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_projects: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    extracted_links: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    candidate: Mapped["Candidate"] = relationship("Candidate", back_populates="resumes")
    applications: Mapped[list["Application"]] = relationship("Application", back_populates="resume")


class Repository(Base):
    """Candidate Git repository or PR/commit metadata (source deleted ephemerally after chunking)."""

    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint("candidate_id", "repo_url", name="uq_candidate_repo_url"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    repo_url: Mapped[str] = mapped_column(String(500), nullable=False)
    link_kind: Mapped[str] = mapped_column(String(32), default="repo", nullable=False)
    default_branch: Mapped[str | None] = mapped_column(String(120), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    author_identities: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    provenance_tier: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    commit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    candidate: Mapped["Candidate"] = relationship("Candidate", back_populates="repositories")
    applications: Mapped[list["Application"]] = relationship("Application", back_populates="repository")
    application_links: Mapped[list["ApplicationRepository"]] = relationship(
        "ApplicationRepository", back_populates="repository", cascade="all, delete-orphan"
    )
    chunks: Mapped[list["CodeChunk"]] = relationship(
        "CodeChunk", back_populates="repository", cascade="all, delete-orphan"
    )


class Application(Base):
    """Security gateway linking a candidate, resume, and verified repositories to a company's job."""

    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("job_id", "candidate_id", name="uq_application_job_candidate"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    repository_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_out_of_10: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    score_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    percentile_rank: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_shortlisted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    evaluation_report: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    tool_call_log: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    company: Mapped["Company"] = relationship("Company", back_populates="applications")
    job: Mapped["Job"] = relationship("Job", back_populates="applications")
    candidate: Mapped["Candidate"] = relationship("Candidate", back_populates="applications")
    repository: Mapped["Repository | None"] = relationship("Repository", back_populates="applications")
    resume: Mapped["Resume | None"] = relationship("Resume", back_populates="applications")
    repository_links: Mapped[list["ApplicationRepository"]] = relationship(
        "ApplicationRepository", back_populates="application", cascade="all, delete-orphan"
    )
    claims: Mapped[list["ResumeClaim"]] = relationship(
        "ResumeClaim", back_populates="application", cascade="all, delete-orphan"
    )


class ApplicationRepository(Base):
    """Join table authorizing multiple extracted GitHub repositories/PRs per Application."""

    __tablename__ = "application_repositories"
    __table_args__ = (
        UniqueConstraint("application_id", "repository_id", name="uq_app_repo"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )

    application: Mapped["Application"] = relationship("Application", back_populates="repository_links")
    repository: Mapped["Repository"] = relationship("Repository", back_populates="application_links")


class ResumeClaim(Base):
    """Individual project/contribution claim extracted from a resume and verified against GitHub code."""

    __tablename__ = "resume_claims"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    repository_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_title: Mapped[str] = mapped_column(String(255), nullable=False)
    claimed_contribution: Mapped[str] = mapped_column(Text, nullable=False)
    target_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    link_kind: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    verification_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    claim_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    authorship_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    authorship_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    referenced_files: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    provenance_tier: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    selected_commits: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    selected_files: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    ownership_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    ownership_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    application: Mapped["Application"] = relationship("Application", back_populates="claims")
    repository: Mapped["Repository | None"] = relationship("Repository")


class CodeChunk(Base):
    """AST-parsed code chunk and its pgvector embedding, indexed with HNSW."""

    __tablename__ = "code_chunks"
    __table_args__ = (
        Index(
            "ix_code_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_code_chunks_repo_file", "repository_id", "file_path"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_path: Mapped[str] = mapped_column(String(600), nullable=False)
    symbol_name: Mapped[str] = mapped_column(String(255), nullable=False, default="<module>")
    symbol_type: Mapped[str] = mapped_column(String(64), nullable=False, default="block")
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    repository: Mapped["Repository"] = relationship("Repository", back_populates="chunks")
