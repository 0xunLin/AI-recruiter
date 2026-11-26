from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import tasks
from app.evaluator import DeterministicFallbackLLM
from app.models import (
    Application,
    ApplicationRepository,
    Candidate,
    CodeChunk,
    Company,
    Job,
    Repository,
    Resume,
    ResumeClaim,
)
from app.security import hash_api_key
from tests.conftest import FakeEmbeddingProvider


def test_portfolio_ingestion_and_claim_evaluation_end_to_end(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    patch_sqlite_cosine: None,
) -> None:
    monkeypatch.setattr(tasks, "SessionLocal", db_session_factory)
    provider = FakeEmbeddingProvider()

    with db_session_factory() as db:
        company = Company(name="Orbit Labs", slug="orbit", api_key_hash=hash_api_key("air_orbit"))
        db.add(company)
        db.flush()

        job = Job(
            company_id=company.id,
            title="Python Systems Engineer",
            description="Write modular Python APIs, SQLAlchemy schemas, async queues, and unit tests.",
        )
        db.add(job)
        db.flush()

        candidate = Candidate(
            full_name="Linus Torvalds",
            email="linus@example.dev",
            github_url="https://github.com/linus",
        )
        db.add(candidate)
        db.flush()

        resume = Resume(
            candidate_id=candidate.id,
            filename="resume.txt",
            raw_text="Built kernel queue tools at https://github.com/example/kernel-tools and dead link https://github.com/example/missing",
            extracted_links=["https://github.com/example/kernel-tools", "https://github.com/example/missing"],
        )
        db.add(resume)
        db.flush()

        repo_ok = Repository(candidate_id=candidate.id, repo_url="https://github.com/example/kernel-tools", status="pending")
        repo_dead = Repository(candidate_id=candidate.id, repo_url="https://github.com/example/missing", status="pending")
        db.add_all([repo_ok, repo_dead])
        db.flush()

        application = Application(
            company_id=company.id,
            job_id=job.id,
            candidate_id=candidate.id,
            repository_id=repo_ok.id,
            resume_id=resume.id,
            status="pending",
        )
        db.add(application)
        db.flush()

        db.add_all(
            [
                ApplicationRepository(application_id=application.id, repository_id=repo_ok.id),
                ApplicationRepository(application_id=application.id, repository_id=repo_dead.id),
                ResumeClaim(
                    application_id=application.id,
                    repository_id=repo_ok.id,
                    project_title="Kernel Queue Tools",
                    claimed_contribution="Implemented process queue worker and unit tests.",
                    target_url="https://github.com/example/kernel-tools",
                    link_kind="repo",
                ),
                ResumeClaim(
                    application_id=application.id,
                    repository_id=repo_dead.id,
                    project_title="Broken Repo",
                    claimed_contribution="Built distributed cache.",
                    target_url="https://github.com/example/missing",
                    link_kind="repo",
                ),
            ]
        )
        db.commit()
        repo_ok_id = repo_ok.id
        app_id = application.id

    cloned_paths: list[Path] = []

    def fake_clone(url: str, target_dir: Path, _timeout: int) -> tuple[str, str, list[str]]:
        if "missing" in url:
            raise RuntimeError("Repository not found")
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "main.py").write_text(
            "def process_queue(items: list[str]) -> int:\n    return len(items)\n"
        )
        (target_dir / "test_main.py").write_text(
            "def test_process_queue():\n    assert True\n"
        )
        cloned_paths.append(target_dir)
        return ("abc123def456", "main", ["Linus Torvalds <linus@example.dev>"])

    summary = tasks.execute_portfolio_ingestion(
        app_id,
        clone_fn=fake_clone,
        embedding_provider=provider,
    )
    assert summary == {"ready": 1, "failed": 1}
    assert len(cloned_paths) == 1
    assert not cloned_paths[0].exists()

    score_10 = tasks.execute_evaluation(
        app_id,
        llm=DeterministicFallbackLLM(),
        embedding_provider=provider,
    )
    assert 0.0 <= score_10 <= 10.0

    with db_session_factory() as db:
        refreshed_repo = db.get(Repository, repo_ok_id)
        refreshed_app = db.get(Application, app_id)
        claims = db.execute(select(ResumeClaim).where(ResumeClaim.application_id == app_id)).scalars().all()
        chunks = db.execute(select(CodeChunk).where(CodeChunk.repository_id == repo_ok_id)).scalars().all()

        assert refreshed_repo is not None and refreshed_repo.status == "ready"
        assert len(chunks) == 2
        assert refreshed_app is not None and refreshed_app.status == "completed"
        assert refreshed_app.score_out_of_10 is not None
        assert refreshed_app.score_breakdown is not None
        assert refreshed_app.evidence_hash is not None and len(refreshed_app.evidence_hash) == 64
        assert refreshed_app.tool_call_log is not None and len(refreshed_app.tool_call_log) >= 5
        statuses = {c.project_title: c.verification_status for c in claims}
        assert statuses["Kernel Queue Tools"] == "verified"
        assert statuses["Broken Repo"] == "dead_link"


def test_validate_public_github_url_rejects_ssrf_and_file_schemes() -> None:
    with pytest.raises(ValueError):
        tasks.validate_public_github_url("file:///etc/passwd")
    with pytest.raises(ValueError):
        tasks.validate_public_github_url("http://169.254.169.254/latest/meta-data")
    assert tasks.validate_public_github_url("https://github.com/octocat/Hello-World/") == (
        "https://github.com/octocat/Hello-World"
    )
    assert tasks.validate_public_github_url("https://github.com/org/repo/pull/42") == (
        "https://github.com/org/repo/pull/42"
    )


def test_tree_ingestion_and_idempotent_checkpointing(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "SessionLocal", db_session_factory)
    provider = FakeEmbeddingProvider()

    with db_session_factory() as db:
        cand = Candidate(full_name="Ada Lovelace", email="ada@example.dev")
        db.add(cand)
        db.flush()
        repo = Repository(
            candidate_id=cand.id,
            repo_url="https://github.com/ada/engine",
            status="pending",
        )
        db.add(repo)
        db.commit()
        repo_id = repo.id

    tree_calls = 0

    def fake_tree(repo_url: str, **_kwargs):
        nonlocal tree_calls
        tree_calls += 1
        return (
            "deadbeef1234",
            "main",
            ["Ada Lovelace <ada@example.dev>"],
            tasks.chunk_source_text("app/core.py", "def compute(x: int) -> int:\n    return x * 2\n"),
        )

    count1 = tasks.execute_ingestion(repo_id, tree_fn=fake_tree, embedding_provider=provider)
    assert count1 == 1
    assert tree_calls == 1

    # Second run skips cloning/tree-fetching because repo is already ready with chunks
    count2 = tasks.execute_ingestion(repo_id, tree_fn=fake_tree, embedding_provider=provider)
    assert count2 == 1
    assert tree_calls == 1
