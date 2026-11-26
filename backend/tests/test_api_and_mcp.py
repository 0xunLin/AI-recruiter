import uuid

import pytest
from fastapi.testclient import TestClient
from fastmcp.exceptions import ToolError
from sqlalchemy.orm import Session, sessionmaker

from app import mcp_server
from app.models import ApplicationRepository, CodeChunk
from tests.conftest import FakeEmbeddingProvider


def test_rest_api_resume_submission_and_tenant_isolation(
    api_client: tuple[TestClient, list, list],
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, dispatched_ingestions, _ = api_client
    monkeypatch.setattr(
        "app.retrieval.get_embedding_provider",
        lambda use_rate_limiter=False: FakeEmbeddingProvider(),
    )

    res_a = client.post("/api/v1/companies", json={"name": "Acme Corp", "slug": "acme"})
    key_a = res_a.json()["api_key"]

    res_b = client.post("/api/v1/companies", json={"name": "Rival Corp", "slug": "rival"})
    key_b = res_b.json()["api_key"]

    assert client.get("/api/v1/jobs").status_code == 401

    job_res = client.post(
        "/api/v1/jobs",
        headers={"X-API-Key": key_a},
        json={
            "title": "AI Platform Engineer",
            "description": "Design FastAPI endpoints, LangGraph agents, pgvector HNSW queries, and Celery tasks.",
        },
    )
    assert job_res.status_code == 201
    job_data = job_res.json()

    resume_text = (
        "Margaret Hamilton\n"
        "Projects:\n"
        "Apollo Guidance Scheduler\n"
        "Built asynchronous priority task scheduler in Python. https://github.com/apollo/guidance-computer\n"
        "Open Source PR Fix\n"
        "Fixed race condition in interrupt handler. https://github.com/nasa/flight-os/pull/19\n"
    )
    app_res = client.post(
        "/api/v1/applications",
        headers={"X-API-Key": key_a},
        json={
            "job_id": job_data["id"],
            "full_name": "Margaret Hamilton",
            "email": "margaret@apollo.dev",
            "resume_text": resume_text,
        },
    )
    assert app_res.status_code == 202
    app_data = app_res.json()
    assert len(dispatched_ingestions) == 1
    assert len(app_data["claims"]) >= 2
    assert len(app_data["repositories"]) == 2

    with db_session_factory() as db:
        repo_id = app_data["repository"]["id"]
        vec = FakeEmbeddingProvider().embed_texts(["priority scheduling"])[0]
        db.add(
            CodeChunk(
                repository_id=uuid.UUID(repo_id),
                file_path="executive/scheduler.py",
                symbol_name="schedule_priority_task",
                symbol_type="function",
                language="python",
                start_line=10,
                end_line=25,
                content="def schedule_priority_task(task): return task.priority",
                embedding=vec,
            )
        )
        db.commit()

    search_a = client.post(
        f"/api/v1/applications/{app_data['id']}/search",
        headers={"X-API-Key": key_a},
        json={"query": "priority scheduling", "top_k": 5},
    )
    assert search_a.status_code == 200
    assert len(search_a.json()["matches"]) == 1
    assert search_a.json()["matches"][0]["file_path"] == "executive/scheduler.py"

    # Tenant B is blocked
    assert client.get(f"/api/v1/jobs/{job_data['id']}", headers={"X-API-Key": key_b}).status_code == 404
    assert client.get(f"/api/v1/applications/{app_data['id']}", headers={"X-API-Key": key_b}).status_code == 404


@pytest.mark.asyncio
async def test_fastmcp_tools_resume_shortlist_and_tenant_isolation(
    api_client: tuple[TestClient, list, list],
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, _ = api_client
    monkeypatch.setattr(mcp_server, "SessionLocal", db_session_factory)
    monkeypatch.setattr(
        "app.retrieval.get_embedding_provider",
        lambda use_rate_limiter=False: FakeEmbeddingProvider(),
    )

    res_a = client.post("/api/v1/companies", json={"name": "Tenant A", "slug": "tenant-a"})
    key_a = res_a.json()["api_key"]
    res_b = client.post("/api/v1/companies", json={"name": "Tenant B", "slug": "tenant-b"})
    key_b = res_b.json()["api_key"]

    job_res = client.post(
        "/api/v1/jobs",
        headers={"X-API-Key": key_a},
        json={"title": "Backend Engineer", "description": "Python FastAPI Postgres pgvector engineering role."},
    )
    job_id = job_res.json()["id"]

    app_res = client.post(
        "/api/v1/applications",
        headers={"X-API-Key": key_a},
        json={
            "job_id": job_id,
            "full_name": "Alan Turing",
            "email": "alan@bletchley.dev",
            "resume_text": "Enigma Solver\nBuilt rotor cipher simulation. https://github.com/turing/enigma-solver\n",
        },
    )
    app_data = app_res.json()

    with db_session_factory() as db:
        from app.models import Application

        vec = FakeEmbeddingProvider().embed_texts(["cipher rotor"])[0]
        db.add(
            CodeChunk(
                repository_id=uuid.UUID(app_data["repository"]["id"]),
                file_path="bombe/rotor.py",
                symbol_name="step_rotor",
                symbol_type="function",
                language="python",
                start_line=1,
                end_line=8,
                content="def step_rotor(pos: int) -> int: return (pos + 1) % 26",
                embedding=vec,
            )
        )
        app_row = db.get(Application, uuid.UUID(app_data["id"]))
        assert app_row is not None
        app_row.status = "completed"
        app_row.score_out_of_10 = 8.75
        app_row.percentile_rank = 1.0
        app_row.is_shortlisted = True
        db.commit()

    monkeypatch.setattr(mcp_server, "get_http_headers", lambda include=None: {"x-api-key": key_a})

    shortlist_res = await mcp_server.mcp.call_tool("list_shortlisted_candidates", {"job_id": job_id})
    assert "Alan Turing" in shortlist_res.content[0].text
    assert "8.75" in shortlist_res.content[0].text

    resume_res = await mcp_server.mcp.call_tool("get_candidate_resume", {"application_id": app_data["id"]})
    assert "Enigma Solver" in resume_res.content[0].text

    search_res = await mcp_server.mcp.call_tool(
        "search_candidate_code",
        {"application_id": app_data["id"], "query": "cipher rotor", "top_k": 5},
    )
    assert "bombe/rotor.py" in search_res.content[0].text

    # Tenant B denied on resume & code search
    monkeypatch.setattr(mcp_server, "get_http_headers", lambda include=None: {"x-api-key": key_b})
    with pytest.raises(ToolError, match="access denied"):
        await mcp_server.mcp.call_tool("get_candidate_resume", {"application_id": app_data["id"]})

    with pytest.raises(ToolError, match="access denied"):
        await mcp_server.mcp.call_tool(
            "search_candidate_code",
            {"application_id": app_data["id"], "query": "cipher rotor", "top_k": 5},
        )
