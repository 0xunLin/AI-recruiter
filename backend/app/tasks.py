import logging
import os
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from celery import chord
from sqlalchemy import delete, select

from app.celery_app import celery_app
from app.chunker import (
    ParsedChunk,
    chunk_repository_directory,
    chunk_source_text,
    is_supported_source_path,
    source_path_priority,
)
from app.config import get_settings
from app.database import SessionLocal
from app.embeddings import EmbeddingRateLimitError, get_embedding_provider
from app.evaluator import (
    LLMRateLimitError,
    check_candidate_authorship,
    compute_evidence_hash,
    compute_score_out_of_10,
    extract_rubric_from_jd,
    generate_interview_probes,
    run_application_evaluation,
    verify_single_resume_claim,
)
from app.models import (
    Application,
    ApplicationRepository,
    Candidate,
    CodeChunk,
    Job,
    Repository,
    Resume,
    ResumeClaim,
)
from app.resume_parser import classify_github_url
from app.schemas import ClaimVerificationOutput, RubricOutput
from app.shortlist import recompute_job_shortlist

logger = logging.getLogger(__name__)

_GITHUB_URL_PATTERN = re.compile(
    r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/(?:pull/\d+|commit/[0-9a-fA-F]{7,40}))?(?:\.git)?$"
)
EMBED_BATCH_SIZE = 32


def validate_public_github_url(repo_url: str) -> str:
    cleaned = repo_url.strip().rstrip("/")
    if not _GITHUB_URL_PATTERN.match(cleaned):
        raise ValueError(f"Unsafe or invalid GitHub repository URL: {repo_url}")
    return cleaned


def clone_repository_ephemeral(
    repo_url: str, target_dir: Path, timeout_seconds: int = 120
) -> tuple[str, str, list[str]]:
    """Run shallow `git clone --depth 1` into an ephemeral temp directory and collect authors."""
    safe_url = validate_public_github_url(repo_url)
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
    }
    subprocess.run(
        ["git", "clone", "--depth", "1", "--single-branch", safe_url, str(target_dir)],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=env,
    )

    sha_proc = subprocess.run(
        ["git", "-C", str(target_dir), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    branch_proc = subprocess.run(
        ["git", "-C", str(target_dir), "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    authors_proc = subprocess.run(
        ["git", "-C", str(target_dir), "log", "-n", "20", "--format=%an <%ae>"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    authors = sorted({ln.strip() for ln in authors_proc.stdout.splitlines() if ln.strip()})
    return sha_proc.stdout.strip(), branch_proc.stdout.strip(), authors


def fetch_patch_chunks_and_authors(
    target_url: str, timeout_seconds: int = 30
) -> tuple[str, str, list[str], list[ParsedChunk]]:
    """
    Fetch only the .patch for a GitHub PR or commit URL without cloning the entire upstream repository.
    Returns (commit_sha, branch_label, authors, parsed_chunks).
    """
    classified = classify_github_url(target_url)
    if classified.link_kind not in {"pull_request", "commit"}:
        raise ValueError(f"Not a PR or commit URL: {target_url}")

    patch_url = f"{classified.canonical_url}.patch"
    with httpx.Client(timeout=float(timeout_seconds), follow_redirects=True) as client:
        resp = client.get(patch_url, headers={"User-Agent": "ai-recruiter-verifier/0.2"})
        resp.raise_for_status()
        patch_text = resp.text

    authors = sorted(
        {
            ln[len("From: ") :].strip()
            for ln in patch_text.splitlines()
            if ln.startswith("From: ")
        }
    )
    commit_sha = classified.ref or "patch"
    for ln in patch_text.splitlines():
        if ln.startswith("From ") and len(ln.split()) >= 2:
            commit_sha = ln.split()[1][:40]
            break

    # Split patch by `diff --git` sections into clean searchable chunks
    sections = patch_text.split("diff --git ")
    chunks: list[ParsedChunk] = []
    for sec in sections[1:]:
        lines = sec.splitlines()
        header = lines[0] if lines else ""
        file_path = "patch.diff"
        if " b/" in header:
            file_path = header.split(" b/", 1)[1].strip()
        body = "\n".join(lines[:180])
        chunks.extend(chunk_source_text(file_path if file_path.endswith(".py") else f"{file_path}.md", body))

    if not chunks and patch_text.strip():
        chunks = [
            ParsedChunk(
                file_path=f"{classified.link_kind}_{classified.ref}.patch",
                symbol_name=classified.canonical_url,
                symbol_type="patch",
                language="diff",
                start_line=1,
                end_line=min(200, len(patch_text.splitlines())),
                content=patch_text[:3500],
            )
        ]

    return commit_sha, classified.link_kind, authors, chunks


class GitHubApiRateLimitError(RuntimeError):
    """Raised when unauthenticated GitHub REST API hits 403/429 rate limits."""


def inspect_github_repo_metadata(
    repo_url: str,
    *,
    max_file_bytes: int = 262144,
    timeout_seconds: int = 20,
) -> dict:
    """
    Lightweight GitHub REST API inspection (zero git clone): returns default branch, head SHA,
    recent commits, authors, prioritized file_tree, and provenance_tier (`single_commit_dump` vs `iterative`).
    """
    safe_url = validate_public_github_url(repo_url)
    classified = classify_github_url(safe_url)
    if not classified.owner or not classified.repo:
        raise ValueError(f"Invalid GitHub repository URL: {repo_url}")

    owner, repo_name = classified.owner, classified.repo
    headers = {
        "User-Agent": "recruise-verifier/0.2",
        "Accept": "application/vnd.github+json",
    }

    with httpx.Client(timeout=float(timeout_seconds), follow_redirects=True) as client:
        meta_resp = client.get(f"https://api.github.com/repos/{owner}/{repo_name}", headers=headers)
        if meta_resp.status_code in {403, 429}:
            raise GitHubApiRateLimitError("GitHub REST API rate-limited repo metadata lookup.")
        if meta_resp.status_code in {404, 410}:
            raise ValueError(f"GitHub repository not found: {safe_url}")
        meta_resp.raise_for_status()
        meta = meta_resp.json()
        default_branch = meta.get("default_branch") or "main"

        commit_sha = default_branch
        authors_set: set[str] = set()
        commits_summary: list[dict[str, str]] = []
        commits_resp = client.get(
            f"https://api.github.com/repos/{owner}/{repo_name}/commits",
            params={"sha": default_branch, "per_page": 20},
            headers=headers,
        )
        if commits_resp.status_code == 200:
            commits_data = commits_resp.json()
            if isinstance(commits_data, list) and commits_data:
                commit_sha = commits_data[0].get("sha") or default_branch
                for item in commits_data:
                    commit_obj = item.get("commit") or {}
                    commit_author = commit_obj.get("author") or {}
                    name = (commit_author.get("name") or "").strip()
                    email = (commit_author.get("email") or "").strip()
                    gh_login = ((item.get("author") or {}).get("login") or "").strip()
                    if name and email:
                        authors_set.add(f"{name} <{email}>")
                    elif name:
                        authors_set.add(name)
                    if gh_login:
                        authors_set.add(f"@{gh_login}")
                    commits_summary.append(
                        {
                            "sha": str(item.get("sha") or "")[:12],
                            "message": (commit_obj.get("message") or "").splitlines()[0][:140],
                            "date": str(commit_author.get("date") or "")[:10],
                            "author": f"@{gh_login}" if gh_login else name,
                        }
                    )

        tree_resp = client.get(
            f"https://api.github.com/repos/{owner}/{repo_name}/git/trees/{commit_sha}",
            params={"recursive": "1"},
            headers=headers,
        )
        if tree_resp.status_code in {403, 429}:
            raise GitHubApiRateLimitError("GitHub REST API rate-limited tree lookup.")
        if tree_resp.status_code in {404, 410}:
            raise ValueError(f"GitHub tree not found for {safe_url}")
        tree_resp.raise_for_status()

        tree_items = tree_resp.json().get("tree") or []
        candidate_paths = [
            item["path"]
            for item in tree_items
            if item.get("type") == "blob"
            and item.get("path")
            and (item.get("size") or 0) <= max_file_bytes
            and is_supported_source_path(item["path"])
        ]
        candidate_paths.sort(key=source_path_priority)

    commit_count = len(commits_summary)
    if classified.link_kind in {"pull_request", "commit"}:
        provenance_tier = "external_pr"
    elif commit_count <= 2:
        provenance_tier = "single_commit_dump"
    else:
        provenance_tier = "iterative"

    return {
        "owner": owner,
        "repo": repo_name,
        "default_branch": default_branch,
        "commit_sha": commit_sha,
        "commits": commits_summary,
        "commit_count": commit_count,
        "authors": sorted(authors_set),
        "file_tree": candidate_paths,
        "provenance_tier": provenance_tier,
    }


def fetch_repo_tree_chunks_and_authors(
    repo_url: str,
    *,
    max_files: int = 50,
    max_chunks: int = 96,
    max_file_bytes: int = 262144,
    timeout_seconds: int = 30,
    preferred_files: list[str] | None = None,
    preferred_commits: list[str] | None = None,
) -> tuple[str, str, list[str], list[ParsedChunk]]:
    """
    Fetch repository metadata, commit authors, and prioritized source files via GitHub's
    lightweight Trees & Raw APIs without running a full `git clone`.
    """
    meta = inspect_github_repo_metadata(
        repo_url, max_file_bytes=max_file_bytes, timeout_seconds=timeout_seconds
    )
    owner, repo_name = meta["owner"], meta["repo"]
    commit_sha = meta["commit_sha"]
    default_branch = meta["default_branch"]
    candidate_paths: list[str] = meta["file_tree"]

    ordered_paths: list[str] = []
    if preferred_files:
        valid_set = set(candidate_paths)
        for p in preferred_files:
            if p in valid_set and p not in ordered_paths:
                ordered_paths.append(p)
    for p in candidate_paths:
        if p not in ordered_paths:
            ordered_paths.append(p)
    selected_paths = ordered_paths[:max_files]

    chunks: list[ParsedChunk] = []
    with httpx.Client(timeout=float(timeout_seconds), follow_redirects=True) as client:
        for commit_ref in (preferred_commits or [])[:4]:
            if len(chunks) >= max_chunks:
                break
            patch_url = f"https://github.com/{owner}/{repo_name}/commit/{commit_ref}.patch"
            patch_resp = client.get(patch_url, headers={"User-Agent": "recruise-verifier/0.2"})
            if patch_resp.status_code == 200 and patch_resp.text.strip():
                chunks.append(
                    ParsedChunk(
                        file_path=f"commits/{commit_ref[:12]}.patch",
                        symbol_name=f"commit:{commit_ref[:12]}",
                        symbol_type="patch",
                        language="diff",
                        start_line=1,
                        end_line=min(120, len(patch_resp.text.splitlines())),
                        content=patch_resp.text[:3500],
                    )
                )

        for rel_path in selected_paths:
            if len(chunks) >= max_chunks:
                break
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo_name}/{commit_sha}/{rel_path}"
            file_resp = client.get(raw_url, headers={"User-Agent": "recruise-verifier/0.2"})
            if file_resp.status_code != 200:
                continue
            raw_bytes = file_resp.content
            if len(raw_bytes) > max_file_bytes or b"\x00" in raw_bytes:
                continue
            text = raw_bytes.decode("utf-8", errors="replace")
            chunks.extend(chunk_source_text(rel_path, text))

    return commit_sha, default_branch, meta["authors"], chunks[:max_chunks]


def execute_ingestion(
    repository_id: uuid.UUID,
    *,
    application_id: uuid.UUID | None = None,
    clone_fn=None,
    patch_fn=fetch_patch_chunks_and_authors,
    tree_fn=fetch_repo_tree_chunks_and_authors,
    embedding_provider=None,
    force: bool = False,
) -> int:
    """Ingest a GitHub repository (surgical Trees API or shallow clone) or PR/commit (.patch) into CodeChunks."""
    settings = get_settings()
    provider = embedding_provider or get_embedding_provider(use_rate_limiter=True)

    with SessionLocal() as db:
        repo = db.get(Repository, repository_id)
        if repo is None:
            raise ValueError(f"Repository {repository_id} not found.")

        if not force and repo.status == "ready" and repo.chunk_count > 0:
            return repo.chunk_count

        preferred_files: list[str] = []
        preferred_commits: list[str] = []
        if application_id is not None:
            linked_claims = (
                db.execute(
                    select(ResumeClaim).where(
                        ResumeClaim.application_id == application_id,
                        ResumeClaim.repository_id == repository_id,
                    )
                )
                .scalars()
                .all()
            )
            for lc in linked_claims:
                preferred_files.extend(lc.selected_files or [])
                preferred_commits.extend(lc.selected_commits or [])

        repo.status = "ingesting"
        if application_id is not None:
            app_row = db.get(Application, application_id)
            if app_row is not None and app_row.status == "pending":
                app_row.status = "ingesting"
                app_row.error_message = None
        db.commit()

        provenance_tier = "unknown"
        commit_count: int | None = None
        try:
            classified = classify_github_url(repo.repo_url)
            if classified.link_kind in {"pull_request", "commit"}:
                commit_sha, default_branch, authors, parsed_chunks = patch_fn(
                    classified.canonical_url,
                    30,
                )
                provenance_tier = "external_pr"
                commit_count = 1
            elif clone_fn is not None:
                with tempfile.TemporaryDirectory(prefix="repo_ingest_") as tmp_dir:
                    repo_path = Path(tmp_dir) / "repo"
                    result = clone_fn(
                        repo.repo_url,
                        repo_path,
                        settings.clone_timeout_seconds,
                    )
                    if len(result) == 2:
                        commit_sha, default_branch = result  # backwards-compatible 2-tuple in tests
                        authors = []
                    else:
                        commit_sha, default_branch, authors = result
                    parsed_chunks = chunk_repository_directory(
                        repo_path,
                        max_files=settings.max_repo_files,
                        max_file_bytes=settings.max_file_bytes,
                    )
                provenance_tier = "iterative"
            else:
                try:
                    tree_kwargs: dict = {
                        "max_files": settings.max_repo_files,
                        "max_chunks": settings.max_chunks_per_repo,
                        "max_file_bytes": settings.max_file_bytes,
                        "timeout_seconds": 30,
                    }
                    if preferred_files:
                        tree_kwargs["preferred_files"] = preferred_files
                    if preferred_commits:
                        tree_kwargs["preferred_commits"] = preferred_commits
                    commit_sha, default_branch, authors, parsed_chunks = tree_fn(
                        repo.repo_url,
                        **tree_kwargs,
                    )
                    try:
                        meta = inspect_github_repo_metadata(repo.repo_url, timeout_seconds=15)
                        provenance_tier = meta["provenance_tier"]
                        commit_count = meta["commit_count"]
                    except Exception:
                        provenance_tier = "iterative"
                except GitHubApiRateLimitError:
                    with tempfile.TemporaryDirectory(prefix="repo_ingest_") as tmp_dir:
                        repo_path = Path(tmp_dir) / "repo"
                        commit_sha, default_branch, authors = clone_repository_ephemeral(
                            repo.repo_url,
                            repo_path,
                            settings.clone_timeout_seconds,
                        )
                        parsed_chunks = chunk_repository_directory(
                            repo_path,
                            max_files=settings.max_repo_files,
                            max_file_bytes=settings.max_file_bytes,
                        )

            parsed_chunks = parsed_chunks[: settings.max_chunks_per_repo]
            if not parsed_chunks:
                raise ValueError("No supported source files were found at the GitHub pointer.")

            chunk_rows: list[CodeChunk] = []
            for start in range(0, len(parsed_chunks), EMBED_BATCH_SIZE):
                batch = parsed_chunks[start : start + EMBED_BATCH_SIZE]
                texts = [
                    f"File: {c.file_path}\nSymbol: {c.symbol_name} ({c.symbol_type})\n\n{c.content}"
                    for c in batch
                ]
                vectors = provider.embed_texts(texts, task="retrieval.passage")
                for parsed, vector in zip(batch, vectors):
                    chunk_rows.append(
                        CodeChunk(
                            repository_id=repo.id,
                            file_path=parsed.file_path,
                            symbol_name=parsed.symbol_name,
                            symbol_type=parsed.symbol_type,
                            language=parsed.language,
                            start_line=parsed.start_line,
                            end_line=parsed.end_line,
                            content=parsed.content,
                            embedding=vector,
                        )
                    )

            db.execute(delete(CodeChunk).where(CodeChunk.repository_id == repo.id))
            db.add_all(chunk_rows)
            repo.commit_sha = commit_sha
            repo.default_branch = default_branch
            repo.author_identities = authors
            repo.provenance_tier = provenance_tier
            repo.commit_count = commit_count
            repo.status = "ready"
            repo.chunk_count = len(chunk_rows)
            repo.ingested_at = datetime.now(timezone.utc)
            db.commit()
            return len(chunk_rows)
        except Exception:
            db.rollback()
            repo = db.get(Repository, repository_id)
            if repo is not None:
                repo.status = "failed"
            db.commit()
            raise


def execute_portfolio_ingestion(
    application_id: uuid.UUID,
    *,
    clone_fn=None,
    patch_fn=fetch_patch_chunks_and_authors,
    tree_fn=fetch_repo_tree_chunks_and_authors,
    embedding_provider=None,
) -> dict[str, int]:
    """Ingest every repository/PR linked to an application, tolerating dead links."""
    ready = 0
    failed = 0

    with SessionLocal() as db:
        app_row = db.get(Application, application_id)
        if app_row is None:
            raise ValueError(f"Application {application_id} not found.")
        app_row.status = "ingesting"
        app_row.error_message = None
        db.commit()

        repo_ids = list(
            db.execute(
                select(ApplicationRepository.repository_id).where(
                    ApplicationRepository.application_id == application_id
                )
            )
            .scalars()
            .all()
        )
        if not repo_ids and app_row.repository_id is not None:
            repo_ids = [app_row.repository_id]

    for repo_id in repo_ids:
        try:
            execute_ingestion(
                repo_id,
                application_id=application_id,
                clone_fn=clone_fn,
                patch_fn=patch_fn,
                tree_fn=tree_fn,
                embedding_provider=embedding_provider,
            )
            ready += 1
        except (EmbeddingRateLimitError, httpx.TransportError):
            raise
        except Exception as exc:
            logger.warning("Repo %s ingestion failed (recorded as dead/failed pointer): %s", repo_id, exc)
            failed += 1

    return {"ready": ready, "failed": failed}


def execute_evaluation(
    application_id: uuid.UUID,
    *,
    llm=None,
    embedding_provider=None,
) -> float:
    """
    Execute the 5-node cyclic LangGraph evaluation + per-claim verification +
    calibrated 0-10 scoring + top-30% shortlisting.
    """
    with SessionLocal() as db:
        app_row = db.get(Application, application_id)
        if app_row is None:
            raise ValueError(f"Application {application_id} not found.")

        job = db.get(Job, app_row.job_id)
        candidate = db.get(Candidate, app_row.candidate_id)
        if job is None or candidate is None:
            raise ValueError(f"Missing job or candidate for application {application_id}.")

        app_row.status = "evaluating"
        app_row.error_message = None
        db.commit()

        try:
            if job.rubric:
                rubric = RubricOutput(**job.rubric)
            else:
                rubric = extract_rubric_from_jd(job.title, job.description, llm=llm)
                job.rubric = rubric.model_dump()
                db.commit()

            report, tool_call_log, _ = run_application_evaluation(
                db,
                company_id=app_row.company_id,
                application_id=app_row.id,
                job_title=job.title,
                job_description=job.description,
                rubric=rubric,
                llm=llm,
                embedding_provider=embedding_provider,
            )

            # Verify each extracted resume claim + authorship
            claims = (
                db.execute(
                    select(ResumeClaim)
                    .where(ResumeClaim.application_id == app_row.id)
                    .order_by(ResumeClaim.created_at.asc())
                )
                .scalars()
                .all()
            )
            resume_obj = db.get(Resume, app_row.resume_id) if app_row.resume_id else None
            gh_profile = candidate.github_url if candidate.github_url else None

            claim_results: list[tuple[ClaimVerificationOutput, bool]] = []
            claim_cards: list[dict] = []

            for claim in claims:
                repo = db.get(Repository, claim.repository_id) if claim.repository_id else None
                prov_tier = repo.provenance_tier if repo else "unknown"
                ver_out, card = verify_single_resume_claim(
                    db,
                    company_id=app_row.company_id,
                    application_id=app_row.id,
                    project_title=claim.project_title,
                    claimed_contribution=claim.claimed_contribution,
                    target_url=claim.target_url,
                    link_kind=claim.link_kind,
                    repository_id=claim.repository_id,
                    repo_status=repo.status if repo else None,
                    provenance_tier=prov_tier,
                    ownership_question=claim.ownership_question,
                    ownership_answer=claim.ownership_answer,
                    llm=llm,
                    embedding_provider=embedding_provider,
                )
                authored, auth_note = check_candidate_authorship(
                    repo.author_identities if repo else None,
                    candidate.full_name,
                    candidate.email,
                    gh_profile,
                    github_handle=candidate.github_handle,
                    verified_emails=candidate.verified_emails,
                )

                claim.verification_status = ver_out.verdict
                claim.claim_score = round((ver_out.match_score + ver_out.technical_depth) / 2.0, 2)
                claim.authorship_verified = authored
                claim.authorship_note = auth_note
                claim.rationale = ver_out.rationale
                claim.referenced_files = ver_out.referenced_files
                claim.provenance_tier = prov_tier

                claim_results.append((ver_out, authored))
                claim_cards.append(card)

            claims_summary = [
                {
                    "project_title": c.project_title,
                    "provenance_tier": c.provenance_tier,
                    "verification_status": c.verification_status,
                }
                for c in claims
            ]
            report.interview_probes = generate_interview_probes(
                db,
                company_id=app_row.company_id,
                application_id=app_row.id,
                job_title=job.title,
                claims_summary=claims_summary,
                llm=llm,
            )

            breakdown = compute_score_out_of_10(claim_results, report.overall_score)
            combined_log = tool_call_log + claim_cards
            final_hash = compute_evidence_hash(combined_log)

            report.score_out_of_10 = breakdown.total_score_out_of_10
            report.score_breakdown = breakdown
            report.evidence_hash = final_hash
            if resume_obj is not None:
                report.summary = (
                    f"Score {breakdown.total_score_out_of_10:.2f}/10.00 — "
                    f"{breakdown.verified_claims}/{breakdown.total_claims} resume claims verified "
                    f"({breakdown.failed_or_dead_claims} unverified/dead). {report.summary}"
                )

            app_row.overall_score = report.overall_score
            app_row.score_out_of_10 = breakdown.total_score_out_of_10
            app_row.score_breakdown = breakdown.model_dump()
            app_row.evaluation_report = report.model_dump()
            app_row.tool_call_log = combined_log
            app_row.evidence_hash = final_hash
            app_row.status = "completed"
            db.commit()

            recompute_job_shortlist(db, app_row.job_id)
            return breakdown.total_score_out_of_10
        except Exception as exc:
            db.rollback()
            if not isinstance(exc, (LLMRateLimitError, httpx.HTTPStatusError, httpx.TransportError)):
                app_row = db.get(Application, application_id)
                if app_row is not None:
                    app_row.status = "failed"
                    app_row.error_message = str(exc)[:1000]
                    db.commit()
            raise


@celery_app.task(
    name="app.tasks.ingest_repository_task",
    bind=True,
    queue="queue_ingestion",
    autoretry_for=(EmbeddingRateLimitError, httpx.HTTPStatusError, httpx.TransportError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def ingest_repository_task(self, repository_id: str, application_id: str | None = None) -> dict[str, str | int]:
    """Legacy single-repo ingestion task (kept compatible for re-evaluation flows)."""
    app_uuid = uuid.UUID(application_id) if application_id else None
    chunk_count = execute_ingestion(uuid.UUID(repository_id), application_id=app_uuid)
    if application_id:
        evaluate_application_task.delay(application_id)
    return {"repository_id": repository_id, "chunk_count": chunk_count}


@celery_app.task(
    name="app.tasks.ingest_single_portfolio_repo_task",
    bind=True,
    queue="queue_ingestion",
    max_retries=5,
)
def ingest_single_portfolio_repo_task(self, repository_id: str, application_id: str) -> dict[str, str | int]:
    """Ingest one linked repository/PR in isolation; never blocks sibling repos or chord completion."""
    try:
        chunk_count = execute_ingestion(
            uuid.UUID(repository_id),
            application_id=uuid.UUID(application_id),
        )
        return {"repository_id": repository_id, "status": "ready", "chunk_count": chunk_count}
    except (EmbeddingRateLimitError, httpx.TransportError) as exc:
        if self.request.retries < self.max_retries:
            countdown = min(120, 10 * (2 ** self.request.retries))
            raise self.retry(exc=exc, countdown=countdown)
        logger.warning(
            "Repo %s exhausted retries (%s); marking failed so evaluation proceeds.",
            repository_id,
            exc,
        )
        with SessionLocal() as db:
            repo = db.get(Repository, uuid.UUID(repository_id))
            if repo is not None:
                repo.status = "failed"
                db.commit()
        return {"repository_id": repository_id, "status": "failed", "chunk_count": 0}
    except Exception as exc:
        logger.warning("Repo %s ingestion failed (recorded as dead/failed pointer): %s", repository_id, exc)
        return {"repository_id": repository_id, "status": "failed", "chunk_count": 0}


@celery_app.task(
    name="app.tasks.finalize_portfolio_evaluation_task",
    queue="queue_ingestion",
)
def finalize_portfolio_evaluation_task(results: list[dict], application_id: str) -> dict[str, str | int]:
    """Chord callback: once all repo tasks settle, always launch 5-node LangGraph evaluation."""
    evaluate_application_task.delay(application_id)
    ready = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "ready")
    failed = sum(1 for r in results if isinstance(r, dict) and r.get("status") != "ready")
    return {"application_id": application_id, "ready": ready, "failed": failed}


@celery_app.task(
    name="app.tasks.ingest_application_portfolio_task",
    bind=True,
    queue="queue_ingestion",
    max_retries=2,
)
def ingest_application_portfolio_task(self, application_id: str) -> dict[str, str | int]:
    """Fan out independent per-repo ingestion tasks via a Celery chord and trigger evaluation."""
    app_uuid = uuid.UUID(application_id)
    with SessionLocal() as db:
        app_row = db.get(Application, app_uuid)
        if app_row is None:
            raise ValueError(f"Application {application_id} not found.")
        app_row.status = "ingesting"
        app_row.error_message = None
        db.commit()

        repo_ids = list(
            db.execute(
                select(ApplicationRepository.repository_id).where(
                    ApplicationRepository.application_id == app_uuid
                )
            )
            .scalars()
            .all()
        )
        if not repo_ids and app_row.repository_id is not None:
            repo_ids = [app_row.repository_id]

    if not repo_ids:
        evaluate_application_task.delay(application_id)
        return {"application_id": application_id, "dispatched": 0}

    chord(
        [ingest_single_portfolio_repo_task.s(str(rid), application_id) for rid in repo_ids],
        finalize_portfolio_evaluation_task.s(application_id),
    ).apply_async()
    return {"application_id": application_id, "dispatched": len(repo_ids)}


@celery_app.task(
    name="app.tasks.evaluate_application_task",
    bind=True,
    queue="queue_evaluation",
    autoretry_for=(LLMRateLimitError, httpx.HTTPStatusError, httpx.TransportError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def evaluate_application_task(self, application_id: str) -> dict[str, str | float]:
    """Queue `queue_evaluation`: run 5-node LangGraph evaluation, claim verification, and top-30% ranking."""
    score_10 = execute_evaluation(uuid.UUID(application_id))
    return {"application_id": application_id, "score_out_of_10": score_10}
