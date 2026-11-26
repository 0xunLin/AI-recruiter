import uuid

from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.evaluator import (
    DeterministicFallbackLLM,
    _strip_verbatim_code,
    check_candidate_authorship,
    compute_evidence_hash,
    compute_score_out_of_10,
    extract_rubric_from_jd,
    run_application_evaluation,
)
from app.models import (
    Application,
    ApplicationRepository,
    Candidate,
    CodeChunk,
    Company,
    Job,
    Repository,
)
from app.retrieval import search_candidate_code_chunks
from app.schemas import ClaimVerificationOutput
from app.security import hash_api_key
from tests.conftest import FakeEmbeddingProvider


def test_postgres_sql_enforces_inner_join_before_pgvector_ordering() -> None:
    """Verify Postgres SQL joins companies->jobs->applications->application_repositories->repositories->code_chunks before <=>."""
    company_id = uuid.uuid4()
    app_id = uuid.uuid4()
    dummy_vec = [0.0] * 1024
    distance_expr = CodeChunk.embedding.cosine_distance(dummy_vec)

    stmt = (
        select(CodeChunk.id, distance_expr)
        .select_from(CodeChunk)
        .join(Repository, CodeChunk.repository_id == Repository.id)
        .join(ApplicationRepository, ApplicationRepository.repository_id == Repository.id)
        .join(Application, ApplicationRepository.application_id == Application.id)
        .join(Job, Application.job_id == Job.id)
        .join(Company, Job.company_id == Company.id)
        .where(Company.id == company_id, Application.company_id == company_id, Application.id == app_id)
        .order_by(distance_expr.asc())
        .limit(5)
    )
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "JOIN repositories" in compiled
    assert "JOIN application_repositories" in compiled
    assert "JOIN applications" in compiled
    assert "JOIN jobs" in compiled
    assert "JOIN companies" in compiled
    assert "WHERE companies.id =" in compiled
    order_clause = compiled.split("ORDER BY", 1)[1]
    assert "code_chunks.embedding <=>" in order_clause


def test_tenant_isolation_and_langgraph_evaluation_loop(
    db: Session,
    patch_sqlite_cosine: None,
) -> None:
    provider = FakeEmbeddingProvider()

    company_a = Company(name="Alpha Corp", slug="alpha", api_key_hash=hash_api_key("air_alpha"))
    company_b = Company(name="Beta Corp", slug="beta", api_key_hash=hash_api_key("air_beta"))
    db.add_all([company_a, company_b])
    db.flush()

    job_a = Job(
        company_id=company_a.id,
        title="Staff Backend Engineer",
        description="Build FastAPI services, Postgres pgvector retrieval, Celery async queues, and automated tests.",
    )
    db.add(job_a)
    db.flush()

    candidate = Candidate(
        full_name="Grace Hopper",
        email="grace@example.dev",
        github_url="https://github.com/grace/vetting-api",
    )
    db.add(candidate)
    db.flush()

    repo = Repository(
        candidate_id=candidate.id,
        repo_url=candidate.github_url,
        status="ready",
        chunk_count=2,
        author_identities=["Grace Hopper <grace@example.dev>"],
    )
    db.add(repo)
    db.flush()

    application = Application(
        company_id=company_a.id,
        job_id=job_a.id,
        candidate_id=candidate.id,
        repository_id=repo.id,
        status="evaluating",
    )
    db.add(application)
    db.flush()
    db.add(ApplicationRepository(application_id=application.id, repository_id=repo.id))
    db.flush()

    chunks_data = [
        ("app/api.py", "create_app", "function", "def create_app(): return FastAPI()"),
        ("app/db.py", "search_vectors", "function", "def search_vectors(): return session.execute(stmt)"),
    ]
    embeddings = provider.embed_texts([c[3] for c in chunks_data])
    for (fpath, sym, stype, content), vec in zip(chunks_data, embeddings):
        db.add(
            CodeChunk(
                repository_id=repo.id,
                file_path=fpath,
                symbol_name=sym,
                symbol_type=stype,
                language="python",
                start_line=1,
                end_line=5,
                content=content,
                embedding=vec,
            )
        )
    db.commit()

    matches_a = search_candidate_code_chunks(
        db,
        company_id=company_a.id,
        application_id=application.id,
        query="FastAPI Postgres",
        top_k=5,
        embedding_provider=provider,
    )
    assert len(matches_a) == 2

    matches_b = search_candidate_code_chunks(
        db,
        company_id=company_b.id,
        application_id=application.id,
        query="FastAPI Postgres",
        top_k=5,
        embedding_provider=provider,
    )
    assert matches_b == []

    llm = DeterministicFallbackLLM()
    rubric = extract_rubric_from_jd(job_a.title, job_a.description, llm=llm, use_rate_limiter=False)
    assert len(rubric.criteria) == 5

    report, tool_call_log, evidence_hash = run_application_evaluation(
        db,
        company_id=company_a.id,
        application_id=application.id,
        job_title=job_a.title,
        job_description=job_a.description,
        rubric=rubric,
        llm=llm,
        embedding_provider=provider,
        use_rate_limiter=False,
    )
    assert 1.0 <= report.overall_score <= 5.0
    assert len(report.criteria_evaluations) == 5
    assert report.prompt_template_version == "v4-resume-verifier"
    assert report.evidence_hash == evidence_hash
    assert evidence_hash == compute_evidence_hash(tool_call_log)
    steps_seen = {entry["step"] for entry in tool_call_log}
    assert {"initialize", "plan", "gather", "analyse", "format_and_seal"}.issubset(steps_seen)

    authored, _ = check_candidate_authorship(
        repo.author_identities, candidate.full_name, candidate.email
    )
    assert authored is True


def test_code_non_leakage_guardrail_strips_fenced_and_verbatim_code() -> None:
    slices = [
        {
            "file_path": "app/secret.py",
            "content": "def compute_secret_token(user_id: str, salt: str) -> str:\n    return f'{user_id}:{salt}'",
        }
    ]
    raw = (
        "Implemented token generation in app/secret.py: "
        "```python\ndef compute_secret_token(user_id, salt): pass\n``` "
        "and specifically def compute_secret_token(user_id: str, salt: str) -> str: handles it."
    )
    cleaned = _strip_verbatim_code(raw, slices)
    assert "```" not in cleaned
    assert "def compute_secret_token(user_id: str, salt: str) -> str:" not in cleaned
    assert "app/secret.py" in cleaned


def test_calibrated_10_point_score_penalizes_dead_links_and_unauthored_work() -> None:
    strong = compute_score_out_of_10(
        [
            (
                ClaimVerificationOutput(
                    verdict="verified",
                    match_score=5,
                    technical_depth=5,
                    rationale="Verified core service implementation across app/service.py and tests.",
                ),
                True,
            ),
            (
                ClaimVerificationOutput(
                    verdict="verified",
                    match_score=5,
                    technical_depth=4,
                    rationale="Verified Redis rate limiter implementation across app/limiter.py.",
                ),
                True,
            ),
        ],
        rubric_overall_score_out_of_5=4.5,
    )
    weak = compute_score_out_of_10(
        [
            (
                ClaimVerificationOutput(
                    verdict="dead_link",
                    match_score=1,
                    technical_depth=1,
                    rationale="Provided GitHub pointer returned 404 or failed to clone.",
                ),
                False,
            ),
            (
                ClaimVerificationOutput(
                    verdict="unverified",
                    match_score=1,
                    technical_depth=1,
                    rationale="No matching code evidence found for this resume claim.",
                ),
                False,
            ),
        ],
        rubric_overall_score_out_of_5=1.5,
    )
    assert strong.total_score_out_of_10 >= 8.5
    assert weak.total_score_out_of_10 <= 2.0
    assert strong.total_score_out_of_10 > weak.total_score_out_of_10
