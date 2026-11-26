from sqlalchemy.orm import Session

from app.models import Application, Candidate, Company, Job
from app.resume_parser import classify_github_url, extract_resume_claims
from app.security import hash_api_key
from app.shortlist import recompute_job_shortlist


def test_resume_url_classifier_and_claim_extractor() -> None:
    resume_text = """
    Jane Doe
    GitHub: https://github.com/janedoe

    Projects:
    1. Distributed Lock Manager
    Implemented Raft-based lock server in Python. https://github.com/janedoe/raft-locks
    2. FastAPI PR Contribution
    Added OAuth scope validation middleware. https://github.com/fastapi/fastapi/pull/9999
    3. Internal Analytics Dashboard
    Built an analytics dashboard with zero public code links.
    """
    extracted = extract_resume_claims(resume_text)
    assert extracted.github_profile_url == "https://github.com/janedoe"
    urls = {p.github_url for p in extracted.projects if p.github_url}
    assert "https://github.com/janedoe/raft-locks" in urls
    assert "https://github.com/fastapi/fastapi/pull/9999" in urls

    assert classify_github_url("https://github.com/fastapi/fastapi/pull/9999").link_kind == "pull_request"
    assert classify_github_url("https://github.com/org/repo/commit/deadbeef12").link_kind == "commit"
    assert classify_github_url("https://github.com/org/repo").link_kind == "repo"


def test_top_30_percent_shortlist_respects_quality_floor(db: Session) -> None:
    company = Company(name="TopCo", slug="topco", api_key_hash=hash_api_key("air_topco"))
    db.add(company)
    db.flush()

    job = Job(
        company_id=company.id,
        title="Backend Engineer",
        description="Build reliable distributed systems in Python and PostgreSQL.",
    )
    db.add(job)
    db.flush()

    scores = [9.2, 8.1, 7.0, 5.5, 4.0, 3.0, 2.5, 2.0, 1.5, 1.0]
    apps = []
    for idx, sc in enumerate(scores):
        cand = Candidate(full_name=f"Cand {idx}", email=f"cand{idx}@example.dev", github_url="")
        db.add(cand)
        db.flush()
        app_obj = Application(
            company_id=company.id,
            job_id=job.id,
            candidate_id=cand.id,
            status="completed",
            score_out_of_10=sc,
        )
        db.add(app_obj)
        apps.append(app_obj)
    db.commit()

    shortlisted_count = recompute_job_shortlist(db, job.id)
    assert shortlisted_count == 3  # Top 30% of 10 candidates
    for app_obj in apps:
        db.refresh(app_obj)
    assert [a.is_shortlisted for a in apps] == [True, True, True, False, False, False, False, False, False, False]

    # If top candidate is below the 6.0 floor, nobody is shortlisted
    for a in apps:
        a.score_out_of_10 = 4.5
    db.commit()
    assert recompute_job_shortlist(db, job.id) == 0
