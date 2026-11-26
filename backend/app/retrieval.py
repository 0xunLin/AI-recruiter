import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.embeddings import EmbeddingProvider, get_embedding_provider
from app.models import (
    Application,
    ApplicationRepository,
    CodeChunk,
    Company,
    Job,
    Repository,
)
from app.schemas import CodeChunkMatch


def search_candidate_code_chunks(
    db: Session,
    *,
    company_id: uuid.UUID,
    application_id: uuid.UUID,
    query: str,
    top_k: int = 5,
    repository_id: uuid.UUID | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> list[CodeChunkMatch]:
    """
    Execute a strict tenant-isolated vector similarity search across all
    GitHub repositories/PRs authorized for an Application.

    Security Guarantee:
    An explicit SQL INNER JOIN across companies -> jobs -> applications ->
    application_repositories -> repositories -> code_chunks with WHERE filters
    on company_id and application_id executes BEFORE any pgvector similarity
    ordering, making cross-tenant leakage mathematically impossible.
    """
    provider = embedding_provider or get_embedding_provider(use_rate_limiter=False)
    query_vec = provider.embed_texts([query], task="retrieval.query")[0]

    distance_expr = CodeChunk.embedding.cosine_distance(query_vec)

    stmt = (
        select(
            CodeChunk.id,
            CodeChunk.file_path,
            CodeChunk.symbol_name,
            CodeChunk.symbol_type,
            CodeChunk.language,
            CodeChunk.start_line,
            CodeChunk.end_line,
            CodeChunk.content,
            (1.0 - distance_expr).label("similarity"),
        )
        .select_from(CodeChunk)
        .join(Repository, CodeChunk.repository_id == Repository.id)
        .join(ApplicationRepository, ApplicationRepository.repository_id == Repository.id)
        .join(Application, ApplicationRepository.application_id == Application.id)
        .join(Job, Application.job_id == Job.id)
        .join(Company, Job.company_id == Company.id)
        .where(
            Company.id == company_id,
            Application.company_id == company_id,
            Application.id == application_id,
        )
    )

    if repository_id is not None:
        stmt = stmt.where(Repository.id == repository_id)

    stmt = stmt.order_by(distance_expr.asc()).limit(top_k)

    rows = db.execute(stmt).all()
    return [
        CodeChunkMatch(
            chunk_id=row.id,
            file_path=row.file_path,
            symbol_name=row.symbol_name,
            symbol_type=row.symbol_type,
            language=row.language,
            start_line=row.start_line,
            end_line=row.end_line,
            content=row.content,
            similarity=max(0.0, min(1.0, float(row.similarity))),
        )
        for row in rows
    ]


def get_authorized_file_chunks(
    db: Session,
    *,
    company_id: uuid.UUID,
    application_id: uuid.UUID,
    file_path: str,
    repository_id: uuid.UUID | None = None,
) -> list[CodeChunkMatch]:
    """Retrieve all chunks for a specific file_path within a tenant-verified application."""
    stmt = (
        select(
            CodeChunk.id,
            CodeChunk.file_path,
            CodeChunk.symbol_name,
            CodeChunk.symbol_type,
            CodeChunk.language,
            CodeChunk.start_line,
            CodeChunk.end_line,
            CodeChunk.content,
        )
        .select_from(CodeChunk)
        .join(Repository, CodeChunk.repository_id == Repository.id)
        .join(ApplicationRepository, ApplicationRepository.repository_id == Repository.id)
        .join(Application, ApplicationRepository.application_id == Application.id)
        .join(Job, Application.job_id == Job.id)
        .join(Company, Job.company_id == Company.id)
        .where(
            Company.id == company_id,
            Application.company_id == company_id,
            Application.id == application_id,
            CodeChunk.file_path == file_path,
        )
    )
    if repository_id is not None:
        stmt = stmt.where(Repository.id == repository_id)

    stmt = stmt.order_by(CodeChunk.start_line.asc())

    rows = db.execute(stmt).all()
    return [
        CodeChunkMatch(
            chunk_id=row.id,
            file_path=row.file_path,
            symbol_name=row.symbol_name,
            symbol_type=row.symbol_type,
            language=row.language,
            start_line=row.start_line,
            end_line=row.end_line,
            content=row.content,
            similarity=1.0,
        )
        for row in rows
    ]


def get_authorized_file_tree(
    db: Session,
    *,
    company_id: uuid.UUID,
    application_id: uuid.UUID,
    repository_id: uuid.UUID | None = None,
) -> list[str]:
    """List distinct file paths across all repositories authorized for an application."""
    stmt = (
        select(CodeChunk.file_path)
        .distinct()
        .select_from(CodeChunk)
        .join(Repository, CodeChunk.repository_id == Repository.id)
        .join(ApplicationRepository, ApplicationRepository.repository_id == Repository.id)
        .join(Application, ApplicationRepository.application_id == Application.id)
        .join(Job, Application.job_id == Job.id)
        .join(Company, Job.company_id == Company.id)
        .where(
            Company.id == company_id,
            Application.company_id == company_id,
            Application.id == application_id,
        )
    )
    if repository_id is not None:
        stmt = stmt.where(Repository.id == repository_id)

    stmt = stmt.order_by(CodeChunk.file_path.asc())
    return list(db.execute(stmt).scalars().all())
