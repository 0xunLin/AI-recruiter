import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastmcp import FastMCP
from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.database import SessionLocal
from app.models import Application, Candidate, Company, Job, Resume, ResumeClaim
from app.retrieval import get_authorized_file_chunks, search_candidate_code_chunks
from app.security import resolve_company_by_key

mcp = FastMCP(
    name="AI Recruiter Evidence MCP",
    instructions=(
        "Tenant-isolated Model Context Protocol server for Recruiting & Engineering Managers. "
        "Query top-30% shortlisted candidates, inspect parsed resumes & verified contribution claims, "
        "and search candidate code chunks protected by relational tenant boundaries."
    ),
)


@contextmanager
def get_mcp_db() -> Iterator[Session]:
    """Scoped SQLAlchemy session dependency for FastMCP tools."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_mcp_company(db: Session = Depends(get_mcp_db)) -> Company:
    """Resolve and verify the authenticated Company tenant from HTTP request headers."""
    headers = get_http_headers(include={"authorization", "x-api-key"})
    raw_key = headers.get("x-api-key", "").strip()
    if not raw_key:
        auth_header = headers.get("authorization", "")
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() == "bearer":
            raw_key = token.strip()

    if not raw_key:
        raise ToolError("Unauthorized: provide X-API-Key or Authorization: Bearer <company_api_key>.")

    company = resolve_company_by_key(db, raw_key)
    if company is None:
        raise ToolError("Unauthorized: invalid tenant API key.")
    return company


@mcp.tool()
def list_job_candidates(
    job_id: str,
    shortlisted_only: bool = False,
    db: Session = Depends(get_mcp_db),
    company: Company = Depends(get_mcp_company),
) -> list[dict[str, Any]]:
    """List candidates for a job owned by the authenticated company, optionally filtered to the top-30% shortlist."""
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError as exc:
        raise ToolError("Invalid job_id UUID format.") from exc

    stmt = (
        select(Application)
        .options(joinedload(Application.candidate), joinedload(Application.claims))
        .join(Job, Application.job_id == Job.id)
        .where(
            Job.company_id == company.id,
            Application.company_id == company.id,
            Job.id == job_uuid,
        )
        .order_by(Application.score_out_of_10.desc().nulls_last(), Application.created_at.desc())
    )
    if shortlisted_only:
        stmt = stmt.where(Application.is_shortlisted.is_(True))

    apps = db.execute(stmt).scalars().unique().all()
    return [
        {
            "application_id": str(a.id),
            "candidate_name": a.candidate.full_name if a.candidate else "Candidate",
            "candidate_email": a.candidate.email if a.candidate else "",
            "status": a.status,
            "score_out_of_10": a.score_out_of_10,
            "percentile_rank": a.percentile_rank,
            "is_shortlisted": a.is_shortlisted,
            "score_breakdown": a.score_breakdown,
            "verified_claims": sum(1 for c in a.claims if c.verification_status == "verified"),
            "total_claims": len(a.claims),
            "evidence_hash": a.evidence_hash,
        }
        for a in apps
    ]


@mcp.tool()
def list_shortlisted_candidates(
    job_id: str,
    db: Session = Depends(get_mcp_db),
    company: Company = Depends(get_mcp_company),
) -> list[dict[str, Any]]:
    """Return only top-30% shortlisted candidates (who also meet the minimum quality floor) for MCP deep-dive questioning."""
    return list_job_candidates(job_id=job_id, shortlisted_only=True, db=db, company=company)


@mcp.tool()
def get_candidate_resume(
    application_id: str,
    db: Session = Depends(get_mcp_db),
    company: Company = Depends(get_mcp_company),
) -> dict[str, Any]:
    """
    Retrieve the candidate's parsed resume text, extracted GitHub links, and per-claim verification results
    for an authorized application so recruiters can assess role adaptability and suitability.
    """
    try:
        app_uuid = uuid.UUID(application_id)
    except ValueError as exc:
        raise ToolError("Invalid application_id UUID format.") from exc

    app_obj = db.execute(
        select(Application)
        .options(
            joinedload(Application.candidate),
            joinedload(Application.job),
            joinedload(Application.resume),
            joinedload(Application.claims),
        )
        .join(Job, Application.job_id == Job.id)
        .where(
            Application.id == app_uuid,
            Application.company_id == company.id,
            Job.company_id == company.id,
        )
    ).unique().scalar_one_or_none()

    if app_obj is None:
        raise ToolError("Application not found or access denied for this tenant.")

    resume: Resume | None = app_obj.resume
    claims: list[ResumeClaim] = list(app_obj.claims)
    return {
        "application_id": str(app_obj.id),
        "job_title": app_obj.job.title if app_obj.job else None,
        "candidate_name": app_obj.candidate.full_name if app_obj.candidate else None,
        "score_out_of_10": app_obj.score_out_of_10,
        "is_shortlisted": app_obj.is_shortlisted,
        "percentile_rank": app_obj.percentile_rank,
        "resume_filename": resume.filename if resume else None,
        "resume_text": resume.raw_text if resume else None,
        "extracted_links": resume.extracted_links if resume else [],
        "claims": [
            {
                "project_title": c.project_title,
                "claimed_contribution": c.claimed_contribution,
                "target_url": c.target_url,
                "link_kind": c.link_kind,
                "verification_status": c.verification_status,
                "claim_score": c.claim_score,
                "authorship_verified": c.authorship_verified,
                "authorship_note": c.authorship_note,
                "rationale": c.rationale,
                "referenced_files": c.referenced_files or [],
            }
            for c in claims
        ],
    }


@mcp.tool()
def search_candidate_code(
    application_id: str,
    query: str,
    top_k: int = 5,
    db: Session = Depends(get_mcp_db),
    company: Company = Depends(get_mcp_company),
) -> list[dict[str, Any]]:
    """
    Semantically search across all repositories/PRs linked to an authorized candidate application.
    Executes relational INNER JOINs BEFORE pgvector cosine similarity search.
    """
    try:
        app_uuid = uuid.UUID(application_id)
    except ValueError as exc:
        raise ToolError("Invalid application_id UUID format.") from exc

    auth_check = db.execute(
        select(Application.id)
        .join(Job, Application.job_id == Job.id)
        .where(
            Application.id == app_uuid,
            Application.company_id == company.id,
            Job.company_id == company.id,
        )
    ).scalar_one_or_none()
    if auth_check is None:
        raise ToolError("Application not found or access denied for this tenant.")

    bounded_k = max(1, min(int(top_k), 20))
    matches = search_candidate_code_chunks(
        db,
        company_id=company.id,
        application_id=app_uuid,
        query=query,
        top_k=bounded_k,
    )
    return [
        {
            "file_path": m.file_path,
            "symbol_name": m.symbol_name,
            "symbol_type": m.symbol_type,
            "language": m.language,
            "start_line": m.start_line,
            "end_line": m.end_line,
            "similarity": round(m.similarity, 4),
            "content": m.content,
        }
        for m in matches
    ]


@mcp.tool()
def get_candidate_evaluation(
    application_id: str,
    db: Session = Depends(get_mcp_db),
    company: Company = Depends(get_mcp_company),
) -> dict[str, Any]:
    """Retrieve the 0-10 score breakdown, LangGraph rubric verdict, and sealed evidence hash for an application."""
    try:
        app_uuid = uuid.UUID(application_id)
    except ValueError as exc:
        raise ToolError("Invalid application_id UUID format.") from exc

    row = db.execute(
        select(Application, Candidate, Job)
        .join(Job, Application.job_id == Job.id)
        .join(Candidate, Application.candidate_id == Candidate.id)
        .where(
            Application.id == app_uuid,
            Application.company_id == company.id,
            Job.company_id == company.id,
        )
    ).first()

    if row is None:
        raise ToolError("Application not found or access denied for this tenant.")

    app_obj, candidate_obj, job_obj = row
    return {
        "application_id": str(app_obj.id),
        "job_title": job_obj.title,
        "candidate_name": candidate_obj.full_name,
        "candidate_email": candidate_obj.email,
        "status": app_obj.status,
        "score_out_of_10": app_obj.score_out_of_10,
        "score_breakdown": app_obj.score_breakdown,
        "percentile_rank": app_obj.percentile_rank,
        "is_shortlisted": app_obj.is_shortlisted,
        "overall_score_out_of_5": app_obj.overall_score,
        "evidence_hash": app_obj.evidence_hash,
        "audit_trail_count": len(app_obj.tool_call_log or []),
        "evaluation_report": app_obj.evaluation_report,
        "error_message": app_obj.error_message,
    }


@mcp.tool()
def get_file_chunks(
    application_id: str,
    file_path: str,
    db: Session = Depends(get_mcp_db),
    company: Company = Depends(get_mcp_company),
) -> list[dict[str, Any]]:
    """Retrieve all AST-parsed code chunks for a specific file_path in an authorized candidate application."""
    try:
        app_uuid = uuid.UUID(application_id)
    except ValueError as exc:
        raise ToolError("Invalid application_id UUID format.") from exc

    auth_check = db.execute(
        select(Application.id)
        .join(Job, Application.job_id == Job.id)
        .where(
            Application.id == app_uuid,
            Application.company_id == company.id,
            Job.company_id == company.id,
        )
    ).scalar_one_or_none()
    if auth_check is None:
        raise ToolError("Application not found or access denied for this tenant.")

    chunks = get_authorized_file_chunks(
        db,
        company_id=company.id,
        application_id=app_uuid,
        file_path=file_path,
    )
    return [
        {
            "file_path": c.file_path,
            "symbol_name": c.symbol_name,
            "symbol_type": c.symbol_type,
            "language": c.language,
            "start_line": c.start_line,
            "end_line": c.end_line,
            "content": c.content,
        }
        for c in chunks
    ]


@mcp.tool()
def get_candidate_interview_probes(
    application_id: str,
    db: Session = Depends(get_mcp_db),
    company: Company = Depends(get_mcp_company),
) -> dict[str, Any]:
    """
    Retrieve code-grounded anti-vibe-coding interview probes, per-claim provenance tiers
    ([SINGLE-COMMIT DUMP] vs iterative/external PR), and candidate Ownership Defense answers.
    """
    try:
        app_uuid = uuid.UUID(application_id)
    except ValueError as exc:
        raise ToolError("Invalid application_id UUID format.") from exc

    app_obj = db.execute(
        select(Application)
        .options(
            joinedload(Application.candidate),
            joinedload(Application.job),
            joinedload(Application.claims),
        )
        .join(Job, Application.job_id == Job.id)
        .where(
            Application.id == app_uuid,
            Application.company_id == company.id,
            Job.company_id == company.id,
        )
    ).unique().scalar_one_or_none()

    if app_obj is None:
        raise ToolError("Application not found or access denied for this tenant.")

    report = app_obj.evaluation_report or {}
    return {
        "application_id": str(app_obj.id),
        "job_title": app_obj.job.title if app_obj.job else None,
        "candidate_name": app_obj.candidate.full_name if app_obj.candidate else None,
        "score_out_of_10": app_obj.score_out_of_10,
        "claims_provenance": [
            {
                "project_title": c.project_title,
                "target_url": c.target_url,
                "provenance_tier": c.provenance_tier,
                "verification_status": c.verification_status,
                "authorship_verified": c.authorship_verified,
                "ownership_question": c.ownership_question,
                "ownership_answer": c.ownership_answer,
            }
            for c in app_obj.claims
        ],
        "interview_probes": report.get("interview_probes", []),
    }


mcp_http_app = mcp.http_app(path="/", transport="streamable-http")
mcp_sse_app = mcp.http_app(path="/", transport="sse")
