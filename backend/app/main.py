from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
import uuid
from typing import Annotated

import redis
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.applicant_routes import router as applicant_router
from app.auth_routes import router as auth_router
from app.config import get_settings
from app.database import get_db, verify_db_connection
from app.dependencies import get_evaluation_dispatcher, get_ingestion_dispatcher
from app.evaluator import extract_rubric_from_jd
from app.mcp_server import mcp_http_app, mcp_sse_app
from app.models import (
    Application,
    ApplicationRepository,
    Candidate,
    Company,
    Job,
    Repository,
    Resume,
    ResumeClaim,
)
from app.resume_parser import classify_github_url, extract_resume_claims, extract_text_from_pdf
from app.retrieval import search_candidate_code_chunks
from app.schemas import (
    ApplicationCreateRequest,
    ApplicationResponse,
    CandidateSummary,
    CodeSearchRequest,
    CodeSearchResponse,
    CompanyCreateRequest,
    CompanyCreateResponse,
    CompanyResponse,
    EvaluationReport,
    HealthResponse,
    JobCreateRequest,
    JobResponse,
    RepositorySummary,
    ResumeClaimResponse,
    ResumeSummary,
    RubricOutput,
    ScoreBreakdown,
    ToolCallLogEntry,
)
from app.security import (
    RecruiterContext,
    generate_api_key,
    get_current_company,
    get_current_recruiter_context,
    hash_api_key,
    slugify_company_name,
)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Compose FastAPI lifespan with both FastMCP Streamable-HTTP and SSE lifespans."""
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(mcp_http_app.lifespan(app))
        await stack.enter_async_context(mcp_sse_app.lifespan(app))
        yield


app = FastAPI(
    title=settings.app_name,
    version="0.3.0",
    description="Resume-First Evidence Verification Platform & Tenant-Isolated MCP Server",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _serialize_application(app_obj: Application) -> ApplicationResponse:
    report = EvaluationReport(**app_obj.evaluation_report) if app_obj.evaluation_report else None
    breakdown = ScoreBreakdown(**app_obj.score_breakdown) if app_obj.score_breakdown else None
    trail = [ToolCallLogEntry(**item) for item in app_obj.tool_call_log] if app_obj.tool_call_log else None
    linked_repos = [RepositorySummary.model_validate(link.repository) for link in app_obj.repository_links if link.repository]
    if not linked_repos and app_obj.repository is not None:
        linked_repos = [RepositorySummary.model_validate(app_obj.repository)]

    return ApplicationResponse(
        id=app_obj.id,
        company_id=app_obj.company_id,
        job_id=app_obj.job_id,
        candidate_id=app_obj.candidate_id,
        status=app_obj.status,  # type: ignore[arg-type]
        overall_score=app_obj.overall_score,
        score_out_of_10=app_obj.score_out_of_10,
        score_breakdown=breakdown,
        percentile_rank=app_obj.percentile_rank,
        is_shortlisted=app_obj.is_shortlisted,
        evaluation_report=report,
        tool_call_log=trail,
        evidence_hash=app_obj.evidence_hash,
        error_message=app_obj.error_message,
        created_at=app_obj.created_at,
        updated_at=app_obj.updated_at,
        candidate=CandidateSummary.model_validate(app_obj.candidate) if app_obj.candidate else None,
        repository=RepositorySummary.model_validate(app_obj.repository) if app_obj.repository else None,
        repositories=linked_repos,
        resume=ResumeSummary.model_validate(app_obj.resume) if app_obj.resume else None,
        claims=[ResumeClaimResponse.model_validate(c) for c in app_obj.claims],
        job_title=app_obj.job.title if app_obj.job else None,
    )


def _load_full_application(db: Session, application_id: uuid.UUID, company_id: uuid.UUID) -> Application | None:
    return db.execute(
        select(Application)
        .options(
            joinedload(Application.candidate),
            joinedload(Application.repository),
            joinedload(Application.resume),
            joinedload(Application.job),
            joinedload(Application.claims),
            joinedload(Application.repository_links).joinedload(ApplicationRepository.repository),
        )
        .where(
            Application.id == application_id,
            Application.company_id == company_id,
        )
    ).unique().scalar_one_or_none()


def _create_application_from_resume(
    db: Session,
    *,
    company_id: uuid.UUID,
    job_id: uuid.UUID,
    full_name: str,
    email: str,
    resume_text: str,
    filename: str,
    fallback_repo_url: str | None,
    enqueue_ingestion: Callable[[uuid.UUID], None],
    candidate_override: Candidate | None = None,
) -> ApplicationResponse:
    job = db.execute(
        select(Job).where(Job.id == job_id, Job.company_id == company_id)
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found for tenant.")

    extraction = extract_resume_claims(resume_text)
    projects = list(extraction.projects)
    if fallback_repo_url and not any(p.github_url == fallback_repo_url for p in projects):
        projects.insert(
            0,
            type(projects[0])(
                project_title="Primary GitHub Repository",
                claimed_contribution="Submitted repository for full-codebase verification.",
                github_url=fallback_repo_url,
            )
            if projects
            else extract_resume_claims(f"Primary Project: {fallback_repo_url}").projects[0],
        )

    extracted_links = [p.github_url for p in projects if p.github_url]
    profile_url = extraction.github_profile_url or fallback_repo_url or ""

    if candidate_override is not None:
        candidate = candidate_override
    else:
        candidate = db.execute(select(Candidate).where(Candidate.email == email)).scalar_one_or_none()
        if candidate is None:
            candidate = Candidate(
                full_name=full_name.strip(),
                email=email,
                github_url=profile_url,
            )
            db.add(candidate)
            db.flush()
        elif profile_url and not candidate.github_url:
            candidate.github_url = profile_url

    existing_app = db.execute(
        select(Application).where(
            Application.job_id == job.id,
            Application.candidate_id == candidate.id,
        )
    ).scalar_one_or_none()
    if existing_app is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Candidate has already applied to this job.",
        )

    resume_row = Resume(
        candidate_id=candidate.id,
        filename=filename,
        raw_text=resume_text,
        parsed_projects=[p.model_dump() for p in projects],
        extracted_links=extracted_links,
    )
    db.add(resume_row)
    db.flush()

    app_obj = Application(
        company_id=company_id,
        job_id=job.id,
        candidate_id=candidate.id,
        resume_id=resume_row.id,
        status="pending",
    )
    db.add(app_obj)
    db.flush()

    # Deduplicate GitHub repos/PRs up to max_repos_per_resume
    repo_by_url: dict[str, Repository] = {}
    primary_repo_id: uuid.UUID | None = None

    for proj in projects:
        repo_row: Repository | None = None
        link_kind = "none"
        target_url = proj.github_url

        if target_url:
            classified = classify_github_url(target_url)
            link_kind = classified.link_kind
            target_url = classified.canonical_url

            if link_kind in {"repo", "pull_request", "commit"}:
                if target_url in repo_by_url:
                    repo_row = repo_by_url[target_url]
                elif len(repo_by_url) < settings.max_repos_per_resume:
                    repo_row = db.execute(
                        select(Repository).where(
                            Repository.candidate_id == candidate.id,
                            Repository.repo_url == target_url,
                        )
                    ).scalar_one_or_none()
                    if repo_row is None:
                        repo_row = Repository(
                            candidate_id=candidate.id,
                            repo_url=target_url,
                            link_kind=link_kind,
                            status="pending",
                        )
                        db.add(repo_row)
                        db.flush()
                    repo_by_url[target_url] = repo_row
                    if primary_repo_id is None:
                        primary_repo_id = repo_row.id

                    db.add(
                        ApplicationRepository(
                            application_id=app_obj.id,
                            repository_id=repo_row.id,
                        )
                    )

        db.add(
            ResumeClaim(
                application_id=app_obj.id,
                repository_id=repo_row.id if repo_row else None,
                project_title=proj.project_title,
                claimed_contribution=proj.claimed_contribution,
                target_url=target_url,
                link_kind=link_kind,
                verification_status="pending",
            )
        )

    app_obj.repository_id = primary_repo_id
    db.commit()

    enqueue_ingestion(app_obj.id)

    loaded = _load_full_application(db, app_obj.id, company_id)
    assert loaded is not None
    return _serialize_application(loaded)


@app.get("/health", response_model=HealthResponse, tags=["System"])
def health_check(db: Annotated[Session, Depends(get_db)]) -> HealthResponse:
    db_status = "ok"
    redis_status = "ok"

    try:
        verify_db_connection(db)
    except Exception:
        db_status = "unavailable"

    try:
        client = redis.Redis.from_url(settings.redis_broker_url, socket_connect_timeout=1.5)
        client.ping()
    except Exception:
        redis_status = "unavailable"

    overall = "ok" if db_status == "ok" and redis_status == "ok" else "degraded"
    return HealthResponse(status=overall, database=db_status, redis=redis_status)


@app.post(
    "/api/v1/companies",
    response_model=CompanyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Tenants"],
)
def create_company(
    payload: CompanyCreateRequest,
    db: Annotated[Session, Depends(get_db)],
) -> CompanyCreateResponse:
    slug = payload.slug or slugify_company_name(payload.name)
    existing = db.execute(select(Company).where(Company.slug == slug)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Company slug already exists.")

    raw_key = generate_api_key()
    company = Company(
        name=payload.name.strip(),
        slug=slug,
        api_key_hash=hash_api_key(raw_key),
    )
    db.add(company)
    db.commit()
    db.refresh(company)

    return CompanyCreateResponse(
        id=company.id,
        name=company.name,
        slug=company.slug,
        created_at=company.created_at,
        api_key=raw_key,
    )


@app.get("/api/v1/companies/me", response_model=CompanyResponse, tags=["Tenants"])
def get_my_company(
    current_company: Annotated[Company, Depends(get_current_company)],
) -> CompanyResponse:
    return CompanyResponse.model_validate(current_company)


@app.post(
    "/api/v1/jobs",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Jobs"],
)
def create_job(
    payload: JobCreateRequest,
    ctx: Annotated[RecruiterContext, Depends(get_current_recruiter_context)],
    db: Annotated[Session, Depends(get_db)],
) -> JobResponse:
    rubric_data = None
    if payload.extract_rubric_now:
        rubric = extract_rubric_from_jd(payload.title, payload.description, use_rate_limiter=False)
        rubric_data = rubric.model_dump()

    job = Job(
        company_id=ctx.company.id,
        created_by_recruiter_id=ctx.recruiter.id if ctx.recruiter else None,
        title=payload.title.strip(),
        description=payload.description.strip(),
        rubric=rubric_data,
        is_public=payload.is_public,
        status="active",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    return JobResponse(
        id=job.id,
        company_id=job.company_id,
        title=job.title,
        description=job.description,
        rubric=RubricOutput(**job.rubric) if job.rubric else None,
        is_public=job.is_public,
        status=job.status,
        created_at=job.created_at,
    )


@app.get("/api/v1/jobs", response_model=list[JobResponse], tags=["Jobs"])
def list_jobs(
    current_company: Annotated[Company, Depends(get_current_company)],
    db: Annotated[Session, Depends(get_db)],
) -> list[JobResponse]:
    jobs = (
        db.execute(
            select(Job).where(Job.company_id == current_company.id).order_by(Job.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [
        JobResponse(
            id=j.id,
            company_id=j.company_id,
            title=j.title,
            description=j.description,
            rubric=RubricOutput(**j.rubric) if j.rubric else None,
            status=j.status,
            created_at=j.created_at,
        )
        for j in jobs
    ]


@app.get("/api/v1/jobs/{job_id}", response_model=JobResponse, tags=["Jobs"])
def get_job(
    job_id: uuid.UUID,
    current_company: Annotated[Company, Depends(get_current_company)],
    db: Annotated[Session, Depends(get_db)],
) -> JobResponse:
    job = db.execute(
        select(Job).where(Job.id == job_id, Job.company_id == current_company.id)
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return JobResponse(
        id=job.id,
        company_id=job.company_id,
        title=job.title,
        description=job.description,
        rubric=RubricOutput(**job.rubric) if job.rubric else None,
        status=job.status,
        created_at=job.created_at,
    )


@app.post(
    "/api/v1/applications",
    response_model=ApplicationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Applications"],
)
def submit_application(
    payload: ApplicationCreateRequest,
    current_company: Annotated[Company, Depends(get_current_company)],
    db: Annotated[Session, Depends(get_db)],
    enqueue_ingestion: Annotated[Callable[[uuid.UUID], None], Depends(get_ingestion_dispatcher)],
) -> ApplicationResponse:
    return _create_application_from_resume(
        db,
        company_id=current_company.id,
        job_id=payload.job_id,
        full_name=payload.full_name,
        email=payload.email,
        resume_text=payload.resume_text,
        filename="resume.txt",
        fallback_repo_url=payload.repo_url,
        enqueue_ingestion=enqueue_ingestion,
    )


@app.post(
    "/api/v1/applications/upload",
    response_model=ApplicationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Applications"],
)
async def upload_resume_application(
    job_id: Annotated[uuid.UUID, Form(...)],
    full_name: Annotated[str, Form(...)],
    email: Annotated[str, Form(...)],
    current_company: Annotated[Company, Depends(get_current_company)],
    db: Annotated[Session, Depends(get_db)],
    enqueue_ingestion: Annotated[Callable[[uuid.UUID], None], Depends(get_ingestion_dispatcher)],
    resume_file: Annotated[UploadFile | None, File()] = None,
    resume_text: Annotated[str | None, Form()] = None,
) -> ApplicationResponse:
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

    cleaned_email = email.strip().lower()
    if "@" not in cleaned_email or "." not in cleaned_email.split("@")[-1]:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid email address.")

    return _create_application_from_resume(
        db,
        company_id=current_company.id,
        job_id=job_id,
        full_name=full_name,
        email=cleaned_email,
        resume_text=extracted_text,
        filename=filename,
        fallback_repo_url=None,
        enqueue_ingestion=enqueue_ingestion,
    )


@app.get("/api/v1/applications", response_model=list[ApplicationResponse], tags=["Applications"])
def list_applications(
    current_company: Annotated[Company, Depends(get_current_company)],
    db: Annotated[Session, Depends(get_db)],
    job_id: uuid.UUID | None = Query(default=None),
    shortlisted_only: bool = Query(default=False),
) -> list[ApplicationResponse]:
    stmt = (
        select(Application)
        .options(
            joinedload(Application.candidate),
            joinedload(Application.repository),
            joinedload(Application.resume),
            joinedload(Application.job),
            joinedload(Application.claims),
            joinedload(Application.repository_links).joinedload(ApplicationRepository.repository),
        )
        .where(Application.company_id == current_company.id)
        .order_by(Application.score_out_of_10.desc().nulls_last(), Application.created_at.desc())
    )
    if job_id is not None:
        stmt = stmt.where(Application.job_id == job_id)
    if shortlisted_only:
        stmt = stmt.where(Application.is_shortlisted.is_(True))

    apps = db.execute(stmt).scalars().unique().all()
    return [_serialize_application(a) for a in apps]


@app.get("/api/v1/applications/{application_id}", response_model=ApplicationResponse, tags=["Applications"])
def get_application(
    application_id: uuid.UUID,
    current_company: Annotated[Company, Depends(get_current_company)],
    db: Annotated[Session, Depends(get_db)],
) -> ApplicationResponse:
    app_obj = _load_full_application(db, application_id, current_company.id)
    if app_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    return _serialize_application(app_obj)


@app.post(
    "/api/v1/applications/{application_id}/re-evaluate",
    response_model=ApplicationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Applications"],
)
def re_evaluate_application(
    application_id: uuid.UUID,
    current_company: Annotated[Company, Depends(get_current_company)],
    db: Annotated[Session, Depends(get_db)],
    enqueue_ingestion: Annotated[Callable[[uuid.UUID], None], Depends(get_ingestion_dispatcher)],
    enqueue_evaluation: Annotated[Callable[[uuid.UUID], None], Depends(get_evaluation_dispatcher)],
) -> ApplicationResponse:
    app_obj = _load_full_application(db, application_id, current_company.id)
    if app_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")

    app_obj.error_message = None
    linked_repos = [link.repository for link in app_obj.repository_links if link.repository]
    all_ready = bool(linked_repos) and all(r.status == "ready" for r in linked_repos)

    if all_ready:
        app_obj.status = "evaluating"
        db.commit()
        enqueue_evaluation(app_obj.id)
    else:
        app_obj.status = "pending"
        db.commit()
        enqueue_ingestion(app_obj.id)

    db.refresh(app_obj)
    return _serialize_application(app_obj)


@app.post(
    "/api/v1/applications/{application_id}/search",
    response_model=CodeSearchResponse,
    tags=["Applications"],
)
def search_application_code(
    application_id: uuid.UUID,
    payload: CodeSearchRequest,
    current_company: Annotated[Company, Depends(get_current_company)],
    db: Annotated[Session, Depends(get_db)],
) -> CodeSearchResponse:
    app_obj = db.execute(
        select(Application).where(
            Application.id == application_id,
            Application.company_id == current_company.id,
        )
    ).scalar_one_or_none()
    if app_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")

    matches = search_candidate_code_chunks(
        db,
        company_id=current_company.id,
        application_id=app_obj.id,
        query=payload.query,
        top_k=payload.top_k,
    )
    return CodeSearchResponse(
        application_id=app_obj.id,
        query=payload.query,
        matches=matches,
    )


app.include_router(auth_router)
app.include_router(applicant_router)

# Mount FastMCP endpoints (Streamable HTTP at /mcp and SSE at /mcp-sse for Claude Desktop / Cursor)
app.mount("/mcp-sse", mcp_sse_app)
app.mount("/mcp", mcp_http_app)
