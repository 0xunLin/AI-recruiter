import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import get_ingestion_dispatcher
from app.models import Application, Candidate, Company, Job, ResumeClaim
from app.resume_parser import classify_github_url, extract_text_from_pdf
from app.schemas import (
    ApplicantApplicationResponse,
    ApplicantClaimStatusResponse,
    ApplicationEvidenceOptionsResponse,
    ClaimEvidenceOptionsResponse,
    CommitOptionResponse,
    ConfirmEvidenceRequest,
    PublicJobResponse,
)
from app.security import get_current_applicant
from app.tasks import inspect_github_repo_metadata

router = APIRouter(prefix="/api/v1/applicant", tags=["Applicant Portal"])


class ApplicantSubmitRequest(BaseModel):
    job_id: uuid.UUID
    resume_text: str = Field(..., min_length=30, max_length=80000)
    interactive_evidence: bool = Field(default=False)


@router.get("/jobs", response_model=list[PublicJobResponse])
def list_public_jobs(db: Annotated[Session, Depends(get_db)]) -> list[PublicJobResponse]:
    """Public job board for signed-in applicants (exposes zero internal rubrics or scores)."""
    rows = db.execute(
        select(Job, Company.name.label("company_name"))
        .join(Company, Job.company_id == Company.id)
        .where(Job.is_public.is_(True), Job.status == "active")
        .order_by(Job.created_at.desc())
    ).all()
    return [
        PublicJobResponse(
            id=job.id,
            company_name=company_name,
            title=job.title,
            description=job.description,
            created_at=job.created_at,
        )
        for job, company_name in rows
    ]


@router.post(
    "/applications",
    response_model=ApplicantApplicationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_applicant_application(
    payload: ApplicantSubmitRequest,
    current_applicant: Annotated[Candidate, Depends(get_current_applicant)],
    db: Annotated[Session, Depends(get_db)],
    enqueue_ingestion: Annotated[Callable[[uuid.UUID], None], Depends(get_ingestion_dispatcher)],
) -> ApplicantApplicationResponse:
    from app.main import _create_application_from_resume

    job = db.execute(
        select(Job).where(Job.id == payload.job_id, Job.is_public.is_(True), Job.status == "active")
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Public job not found.")

    created = _create_application_from_resume(
        db,
        company_id=job.company_id,
        job_id=job.id,
        full_name=current_applicant.full_name,
        email=current_applicant.email,
        resume_text=payload.resume_text,
        filename="resume.txt",
        fallback_repo_url=None,
        enqueue_ingestion=(lambda _id: None) if payload.interactive_evidence else enqueue_ingestion,
        candidate_override=current_applicant,
    )
    if payload.interactive_evidence:
        app_row = db.get(Application, created.id)
        if app_row is not None:
            app_row.status = "awaiting_evidence"
            db.commit()
        created.status = "awaiting_evidence"

    company = db.get(Company, job.company_id)
    return ApplicantApplicationResponse(
        id=created.id,
        job_id=created.job_id,
        job_title=job.title,
        company_name=company.name if company else "Company",
        status=created.status,
        created_at=created.created_at,
        claims=[
            ApplicantClaimStatusResponse(
                project_title=c.project_title,
                target_url=c.target_url,
                link_kind=c.link_kind,
                link_status="missing_link" if not c.target_url else "pending",
            )
            for c in created.claims
        ],
    )


@router.post(
    "/applications/upload",
    response_model=ApplicantApplicationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_applicant_resume(
    job_id: Annotated[uuid.UUID, Form(...)],
    current_applicant: Annotated[Candidate, Depends(get_current_applicant)],
    db: Annotated[Session, Depends(get_db)],
    enqueue_ingestion: Annotated[Callable[[uuid.UUID], None], Depends(get_ingestion_dispatcher)],
    resume_file: Annotated[UploadFile | None, File()] = None,
    resume_text: Annotated[str | None, Form()] = None,
    interactive_evidence: Annotated[bool, Form()] = False,
) -> ApplicantApplicationResponse:
    from app.main import _create_application_from_resume

    job = db.execute(
        select(Job).where(Job.id == job_id, Job.is_public.is_(True), Job.status == "active")
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Public job not found.")

    extracted_text = (resume_text or "").strip()
    filename = "resume.txt"
    if resume_file is not None:
        filename = resume_file.filename or "resume.pdf"
        raw_bytes = await resume_file.read()
        if len(raw_bytes) > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Resume file exceeds 5 MB limit.")
        if filename.lower().endswith(".pdf") or raw_bytes.startswith(b"%PDF"):
            extracted_text = extract_text_from_pdf(raw_bytes)
        else:
            extracted_text = raw_bytes.decode("utf-8", errors="replace")

    if len(extracted_text.strip()) < 30:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Resume content is empty or too short (minimum 30 characters).",
        )

    created = _create_application_from_resume(
        db,
        company_id=job.company_id,
        job_id=job.id,
        full_name=current_applicant.full_name,
        email=current_applicant.email,
        resume_text=extracted_text,
        filename=filename,
        fallback_repo_url=None,
        enqueue_ingestion=(lambda _id: None) if interactive_evidence else enqueue_ingestion,
        candidate_override=current_applicant,
    )
    if interactive_evidence:
        app_row = db.get(Application, created.id)
        if app_row is not None:
            app_row.status = "awaiting_evidence"
            db.commit()
        created.status = "awaiting_evidence"

    company = db.get(Company, job.company_id)
    return ApplicantApplicationResponse(
        id=created.id,
        job_id=created.job_id,
        job_title=job.title,
        company_name=company.name if company else "Company",
        status=created.status,
        created_at=created.created_at,
        claims=[
            ApplicantClaimStatusResponse(
                project_title=c.project_title,
                target_url=c.target_url,
                link_kind=c.link_kind,
                link_status="missing_link" if not c.target_url else "pending",
            )
            for c in created.claims
        ],
    )


@router.get("/applications", response_model=list[ApplicantApplicationResponse])
def list_my_applications(
    current_applicant: Annotated[Candidate, Depends(get_current_applicant)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ApplicantApplicationResponse]:
    """Return ONLY the authenticated applicant's own submissions without exposing internal /10 scores or shortlist flags."""
    apps = (
        db.execute(
            select(Application)
            .options(
                joinedload(Application.job),
                joinedload(Application.company),
                joinedload(Application.claims),
            )
            .where(Application.candidate_id == current_applicant.id)
            .order_by(Application.created_at.desc())
        )
        .scalars()
        .unique()
        .all()
    )

    results: list[ApplicantApplicationResponse] = []
    for a in apps:
        claim_views: list[ApplicantClaimStatusResponse] = []
        for c in a.claims:
            if not c.target_url:
                l_status = "missing_link"
            elif c.verification_status == "dead_link":
                l_status = "dead_link"
            elif c.verification_status in {"verified", "partial", "unverified"}:
                l_status = "accessible"
            else:
                l_status = "pending"
            claim_views.append(
                ApplicantClaimStatusResponse(
                    project_title=c.project_title,
                    target_url=c.target_url,
                    link_kind=c.link_kind,
                    link_status=l_status,  # type: ignore[arg-type]
                )
            )
        results.append(
            ApplicantApplicationResponse(
                id=a.id,
                job_id=a.job_id,
                job_title=a.job.title if a.job else "Role",
                company_name=a.company.name if a.company else "Company",
                status=a.status,  # type: ignore[arg-type]
                created_at=a.created_at,
                claims=claim_views,
            )
        )
    return results


def _build_ownership_question(project_title: str, file_tree: list[str], link_kind: str) -> str:
    anchor = file_tree[0] if file_tree else None
    if link_kind in {"pull_request", "commit"}:
        return (
            f"For '{project_title}', describe the exact bug or feature change in your PR/commit "
            "and one edge case you handled or verified."
        )
    if anchor:
        return (
            f"For '{project_title}', explain how core logic in '{anchor}' works end-to-end "
            "and one failure mode or architectural tradeoff you made."
        )
    return (
        f"For '{project_title}', describe the main engineering tradeoff and one failure mode "
        "your implementation handles."
    )


@router.get(
    "/applications/{application_id}/evidence-options",
    response_model=ApplicationEvidenceOptionsResponse,
)
def get_application_evidence_options(
    application_id: uuid.UUID,
    current_applicant: Annotated[Candidate, Depends(get_current_applicant)],
    db: Annotated[Session, Depends(get_db)],
) -> ApplicationEvidenceOptionsResponse:
    """
    Lightweight GitHub API lookup (0 cloning): return recent commits, filtered file tree,
    provenance tier ([SINGLE-COMMIT DUMP] detection), and a 1-question Ownership Defense prompt per claim.
    """
    app_obj = (
        db.execute(
            select(Application)
            .options(joinedload(Application.claims))
            .where(
                Application.id == application_id,
                Application.candidate_id == current_applicant.id,
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if app_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")

    claim_options: list[ClaimEvidenceOptionsResponse] = []
    for claim in app_obj.claims:
        commits: list[CommitOptionResponse] = []
        file_tree: list[str] = []
        prov_tier = claim.provenance_tier or "unknown"
        is_dump = False

        if claim.target_url and claim.link_kind == "repo":
            try:
                classified = classify_github_url(claim.target_url)
                if classified.owner and classified.repo:
                    meta = inspect_github_repo_metadata(claim.target_url, timeout_seconds=12)
                    prov_tier = meta["provenance_tier"]
                    is_dump = prov_tier == "single_commit_dump"
                    commits = [CommitOptionResponse(**c) for c in meta["commits"][:20]]
                    file_tree = meta["file_tree"][:35]
            except Exception:
                pass
        elif claim.link_kind in {"pull_request", "commit"}:
            prov_tier = "external_pr"

        question = claim.ownership_question or _build_ownership_question(
            claim.project_title, file_tree, claim.link_kind
        )
        claim.ownership_question = question
        claim.provenance_tier = prov_tier

        claim_options.append(
            ClaimEvidenceOptionsResponse(
                claim_id=claim.id,
                project_title=claim.project_title,
                target_url=claim.target_url,
                link_kind=claim.link_kind,
                provenance_tier=prov_tier,
                is_single_commit_dump=is_dump,
                commits=commits,
                file_tree=file_tree,
                ownership_question=question,
            )
        )

    db.commit()
    return ApplicationEvidenceOptionsResponse(
        application_id=app_obj.id,
        status=app_obj.status,
        claims=claim_options,
    )


@router.post(
    "/applications/{application_id}/confirm-evidence",
    response_model=ApplicantApplicationResponse,
)
def confirm_application_evidence(
    application_id: uuid.UUID,
    payload: ConfirmEvidenceRequest,
    current_applicant: Annotated[Candidate, Depends(get_current_applicant)],
    db: Annotated[Session, Depends(get_db)],
    enqueue_ingestion: Annotated[Callable[[uuid.UUID], None], Depends(get_ingestion_dispatcher)],
) -> ApplicantApplicationResponse:
    """Persist applicant-selected commits/files + Ownership Defense answers and start verification."""
    app_obj = (
        db.execute(
            select(Application)
            .options(
                joinedload(Application.job),
                joinedload(Application.company),
                joinedload(Application.claims),
            )
            .where(
                Application.id == application_id,
                Application.candidate_id == current_applicant.id,
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if app_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")

    claims_by_id: dict[uuid.UUID, ResumeClaim] = {c.id: c for c in app_obj.claims}
    for item in payload.claims:
        target_claim = claims_by_id.get(item.claim_id)
        if target_claim is None:
            continue
        if item.selected_commits:
            target_claim.selected_commits = item.selected_commits[:10]
        if item.selected_files:
            target_claim.selected_files = item.selected_files[:15]
        if item.ownership_answer.strip():
            target_claim.ownership_answer = item.ownership_answer.strip()[:2500]

    app_obj.status = "pending"
    app_obj.error_message = None
    db.commit()
    enqueue_ingestion(app_obj.id)

    return ApplicantApplicationResponse(
        id=app_obj.id,
        job_id=app_obj.job_id,
        job_title=app_obj.job.title if app_obj.job else "Role",
        company_name=app_obj.company.name if app_obj.company else "Company",
        status="pending",
        created_at=app_obj.created_at,
        claims=[
            ApplicantClaimStatusResponse(
                project_title=c.project_title,
                target_url=c.target_url,
                link_kind=c.link_kind,
                link_status="missing_link" if not c.target_url else "pending",
            )
            for c in app_obj.claims
        ],
    )
