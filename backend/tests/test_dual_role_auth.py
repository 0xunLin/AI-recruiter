from fastapi.testclient import TestClient

from app.evaluator import check_candidate_authorship


def test_recruiter_magic_link_and_dual_role_session_isolation(
    api_client: tuple[TestClient, list, list],
) -> None:
    client, dispatched_ingestions, _ = api_client

    # 1. Recruiter requests magic link
    req_res = client.post(
        "/api/v1/auth/recruiter/magic-link/request",
        json={"email": "alice@gmail.com", "company_name": "Alice Ventures"},
    )
    assert req_res.status_code == 200
    dev_link = req_res.json()["dev_magic_link"]
    assert dev_link is not None
    token = dev_link.split("token=")[1]

    # 2. Verify magic link sets recruiter cookie & single-use invalidates token
    verify_res = client.post(f"/api/v1/auth/recruiter/magic-link/verify?token={token}")
    assert verify_res.status_code == 200
    assert verify_res.json()["email"] == "alice@gmail.com"
    assert verify_res.json()["company"]["name"] == "Alice Ventures"

    # Replaying single-use token fails
    replay_res = client.post(f"/api/v1/auth/recruiter/magic-link/verify?token={token}")
    assert replay_res.status_code == 400

    # Recruiter can create a public job and mint an MCP API key
    job_res = client.post(
        "/api/v1/jobs",
        json={
            "title": "Distributed Systems Engineer",
            "description": "Build multi-tenant FastAPI services, Celery pipelines, and pgvector HNSW search.",
            "is_public": True,
        },
    )
    assert job_res.status_code == 201
    job_id = job_res.json()["id"]

    mcp_key_res = client.post("/api/v1/auth/recruiter/mcp-key")
    assert mcp_key_res.status_code == 200
    assert mcp_key_res.json()["api_key"].startswith("air_")

    # Recruiter session CANNOT access Applicant-only routes
    assert client.get("/api/v1/applicant/applications").status_code == 401

    # 3. Sign out and sign in as Applicant via GitHub OAuth (even with same email alice@gmail.com!)
    client.post("/api/v1/auth/logout-all")
    gh_res = client.post(
        "/api/v1/auth/applicant/dev-github",
        json={
            "github_handle": "alice-codes",
            "full_name": "Alice Dev",
            "email": "alice@gmail.com",
        },
    )
    assert gh_res.status_code == 200
    assert gh_res.json()["github_handle"] == "alice-codes"

    # Applicant session CANNOT access Recruiter routes
    assert client.get("/api/v1/applications").status_code == 401
    assert client.post("/api/v1/auth/recruiter/mcp-key").status_code == 401

    # Applicant sees public job board WITHOUT internal rubric
    pub_jobs = client.get("/api/v1/applicant/jobs")
    assert pub_jobs.status_code == 200
    assert len(pub_jobs.json()) == 1
    assert "rubric" not in pub_jobs.json()[0]

    # Applicant submits resume; internal /10 score & shortlist flags are withheld
    submit_res = client.post(
        "/api/v1/applicant/applications",
        json={
            "job_id": job_id,
            "resume_text": (
                "Alice Dev\n"
                "Distributed Cache\n"
                "Implemented Redis token-bucket rate limiter. https://github.com/alice-codes/rate-limiter\n"
            ),
        },
    )
    assert submit_res.status_code == 202
    assert len(dispatched_ingestions) == 1
    body = submit_res.json()
    assert "score_out_of_10" not in body
    assert "is_shortlisted" not in body

    my_apps = client.get("/api/v1/applicant/applications")
    assert my_apps.status_code == 200
    assert len(my_apps.json()) == 1


def test_gmail_recruiters_never_auto_merge_without_invite(
    api_client: tuple[TestClient, list, list],
) -> None:
    client, _, _ = api_client

    # First @gmail.com recruiter
    r1 = client.post(
        "/api/v1/auth/recruiter/magic-link/request",
        json={"email": "rec1@gmail.com"},
    )
    t1 = r1.json()["dev_magic_link"].split("token=")[1]
    p1 = client.post(f"/api/v1/auth/recruiter/magic-link/verify?token={t1}").json()

    # Invite a teammate explicitly
    inv = client.post("/api/v1/auth/recruiter/invites", json={"email": "teammate@gmail.com"})
    assert inv.status_code == 201
    invite_token = inv.json()["invite_token"]

    client.post("/api/v1/auth/logout-all")

    # Second @gmail.com recruiter WITHOUT invite gets their own isolated Company
    r2 = client.post(
        "/api/v1/auth/recruiter/magic-link/request",
        json={"email": "rec2@gmail.com"},
    )
    t2 = r2.json()["dev_magic_link"].split("token=")[1]
    p2 = client.post(f"/api/v1/auth/recruiter/magic-link/verify?token={t2}").json()
    assert p2["company"]["id"] != p1["company"]["id"]

    client.post("/api/v1/auth/logout-all")

    # Invited teammate WITH invite joins Company 1
    r3 = client.post(
        "/api/v1/auth/recruiter/magic-link/request",
        json={"email": "teammate@gmail.com", "invite_token": invite_token},
    )
    t3 = r3.json()["dev_magic_link"].split("token=")[1]
    p3 = client.post(f"/api/v1/auth/recruiter/magic-link/verify?token={t3}").json()
    assert p3["company"]["id"] == p1["company"]["id"]


def test_github_oauth_verified_emails_and_handle_prove_authorship() -> None:
    authored, note = check_candidate_authorship(
        ["Alice Dev <12345+alice-codes@users.noreply.github.com>"],
        "Alice Dev",
        "alice@personal.dev",
        github_handle="alice-codes",
        verified_emails=["alice@personal.dev", "12345+alice-codes@users.noreply.github.com"],
    )
    assert authored is True
    assert "alice-codes" in note or "noreply" in note
