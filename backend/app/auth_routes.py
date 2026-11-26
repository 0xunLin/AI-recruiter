import base64
import hashlib
import logging
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Annotated
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Candidate, Company, CompanyInvite, MagicLinkToken, Recruiter
from app.schemas import (
    ApplicantProfileResponse,
    AuthProvidersResponse,
    CompanyResponse,
    DevGitHubLoginRequest,
    MagicLinkRequest,
    MagicLinkResponse,
    RecruiterInviteRequest,
    RecruiterInviteResponse,
    RecruiterProfileResponse,
)
from app.security import (
    APPLICANT_COOKIE_NAME,
    OAUTH_STATE_COOKIE_NAME,
    RECRUITER_COOKIE_NAME,
    RecruiterContext,
    clear_role_cookie,
    create_session_token,
    generate_api_key,
    get_current_applicant,
    get_current_recruiter_context,
    hash_api_key,
    set_role_cookie,
    slugify_company_name,
    verify_session_token,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_tz(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _send_magic_link_email(to_email: str, verify_url: str) -> None:
    settings = get_settings()
    if not settings.smtp_host:
        logger.info("Magic link for %s (SMTP not configured): %s", to_email, verify_url)
        return

    msg = EmailMessage()
    msg["Subject"] = "Sign in to AI Recruiter (Recruiter Portal)"
    msg["From"] = settings.smtp_from_email
    msg["To"] = to_email
    msg.set_content(
        f"Click the single-use link below to sign in to your Recruiter workspace (expires in 15 minutes):\n\n{verify_url}\n"
    )

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        server.starttls()
        if settings.smtp_username and settings.smtp_password:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)


def _provision_or_get_recruiter(
    db: Session,
    *,
    email: str,
    full_name: str,
    auth_provider: str,
    google_sub: str | None = None,
    company_name: str | None = None,
    invite_token: str | None = None,
) -> Recruiter:
    """
    Load an existing Recruiter or create a new one in an isolated Company workspace.
    Never auto-merges public @gmail.com recruiters into the same Company without an explicit invite.
    """
    recruiter = None
    if google_sub:
        recruiter = db.execute(select(Recruiter).where(Recruiter.google_sub == google_sub)).scalar_one_or_none()
    if recruiter is None:
        recruiter = db.execute(select(Recruiter).where(Recruiter.email == email)).scalar_one_or_none()

    if recruiter is not None:
        if google_sub and not recruiter.google_sub:
            recruiter.google_sub = google_sub
        if full_name and not recruiter.full_name:
            recruiter.full_name = full_name
        db.commit()
        db.refresh(recruiter)
        return recruiter

    target_company: Company | None = None
    if invite_token:
        invite_hash = hash_api_key(invite_token)
        invite = db.execute(
            select(CompanyInvite).where(
                CompanyInvite.token_hash == invite_hash,
                CompanyInvite.invited_email == email,
                CompanyInvite.accepted_at.is_(None),
            )
        ).scalar_one_or_none()
        if invite is None:
            raise HTTPException(status_code=400, detail="Invalid or already-used company invite token.")
        target_company = db.get(Company, invite.company_id)
        invite.accepted_at = _utcnow()

    if target_company is None:
        ws_name = (company_name or "").strip() or f"{email.split('@')[0].title()} Workspace"
        raw_key = generate_api_key()
        target_company = Company(
            name=ws_name[:200],
            slug=slugify_company_name(ws_name),
            api_key_hash=hash_api_key(raw_key),
        )
        db.add(target_company)
        db.flush()

    recruiter = Recruiter(
        company_id=target_company.id,
        email=email,
        full_name=full_name or email.split("@")[0],
        google_sub=google_sub,
        auth_provider=auth_provider,
    )
    db.add(recruiter)
    db.commit()
    db.refresh(recruiter)
    return recruiter


@router.get("/providers", response_model=AuthProvidersResponse)
def get_auth_providers() -> AuthProvidersResponse:
    settings = get_settings()
    return AuthProvidersResponse(
        magic_link_enabled=True,
        google_oauth_enabled=bool(settings.google_client_id and settings.google_client_secret),
        github_oauth_enabled=bool(settings.github_client_id and settings.github_client_secret),
        dev_mode=settings.app_env == "development",
    )


@router.post("/logout-all")
def logout_all(response: Response) -> dict[str, str]:
    clear_role_cookie(response, RECRUITER_COOKIE_NAME)
    clear_role_cookie(response, APPLICANT_COOKIE_NAME)
    clear_role_cookie(response, OAUTH_STATE_COOKIE_NAME)
    return {"status": "signed_out"}


# ---------------------------------------------------------------------------
# Recruiter Auth: Magic Link + Google OAuth (Gmail)
# ---------------------------------------------------------------------------


@router.post("/recruiter/magic-link/request", response_model=MagicLinkResponse)
def request_recruiter_magic_link(
    payload: MagicLinkRequest,
    db: Annotated[Session, Depends(get_db)],
) -> MagicLinkResponse:
    settings = get_settings()
    raw_token = secrets.token_urlsafe(32)
    token_row = MagicLinkToken(
        email=payload.email,
        token_hash=hash_api_key(raw_token),
        company_name=payload.company_name.strip() if payload.company_name else None,
        invite_token_hash=hash_api_key(payload.invite_token) if payload.invite_token else None,
        expires_at=_utcnow() + timedelta(seconds=settings.magic_link_ttl_seconds),
    )
    db.add(token_row)
    db.commit()

    verify_url = f"{settings.app_base_url.rstrip('/')}/api/v1/auth/recruiter/magic-link/verify?token={raw_token}"
    _send_magic_link_email(payload.email, verify_url)

    return MagicLinkResponse(
        message="Magic link generated. Check your email inbox to sign in.",
        dev_magic_link=verify_url if settings.app_env == "development" and not settings.smtp_host else None,
    )


def _consume_magic_link_token(db: Session, raw_token: str) -> Recruiter:
    token_hash = hash_api_key(raw_token.strip())
    token_row = db.execute(
        select(MagicLinkToken).where(MagicLinkToken.token_hash == token_hash)
    ).scalar_one_or_none()

    if token_row is None or token_row.used_at is not None:
        raise HTTPException(status_code=400, detail="Invalid or already-used magic link.")
    if _ensure_tz(token_row.expires_at) < _utcnow():
        raise HTTPException(status_code=400, detail="Magic link has expired.")

    token_row.used_at = _utcnow()

    # Check if an invite hash was attached
    invite_raw: str | None = None
    if token_row.invite_token_hash:
        invite = db.execute(
            select(CompanyInvite).where(
                CompanyInvite.token_hash == token_row.invite_token_hash,
                CompanyInvite.invited_email == token_row.email,
                CompanyInvite.accepted_at.is_(None),
            )
        ).scalar_one_or_none()
        if invite is not None:
            recruiter = db.execute(select(Recruiter).where(Recruiter.email == token_row.email)).scalar_one_or_none()
            if recruiter is None:
                invite.accepted_at = _utcnow()
                recruiter = Recruiter(
                    company_id=invite.company_id,
                    email=token_row.email,
                    full_name=token_row.email.split("@")[0],
                    auth_provider="magic_link",
                )
                db.add(recruiter)
                db.commit()
                db.refresh(recruiter)
                return recruiter

    return _provision_or_get_recruiter(
        db,
        email=token_row.email,
        full_name=token_row.email.split("@")[0],
        auth_provider="magic_link",
        company_name=token_row.company_name,
        invite_token=invite_raw,
    )


@router.get("/recruiter/magic-link/verify")
def verify_recruiter_magic_link_get(
    token: Annotated[str, Query(...)],
    db: Annotated[Session, Depends(get_db)],
) -> RedirectResponse:
    settings = get_settings()
    recruiter = _consume_magic_link_token(db, token)
    session_token = create_session_token(subject_id=str(recruiter.id), audience="recruiter")
    resp = RedirectResponse(url=settings.frontend_base_url, status_code=status.HTTP_302_FOUND)
    clear_role_cookie(resp, APPLICANT_COOKIE_NAME)
    set_role_cookie(resp, RECRUITER_COOKIE_NAME, session_token, settings.session_ttl_seconds)
    return resp


@router.post("/recruiter/magic-link/verify", response_model=RecruiterProfileResponse)
def verify_recruiter_magic_link_post(
    token: Annotated[str, Query(...)],
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RecruiterProfileResponse:
    settings = get_settings()
    recruiter = _consume_magic_link_token(db, token)
    session_token = create_session_token(subject_id=str(recruiter.id), audience="recruiter")
    clear_role_cookie(response, APPLICANT_COOKIE_NAME)
    set_role_cookie(response, RECRUITER_COOKIE_NAME, session_token, settings.session_ttl_seconds)
    company = db.get(Company, recruiter.company_id)
    assert company is not None
    return RecruiterProfileResponse(
        id=recruiter.id,
        email=recruiter.email,
        full_name=recruiter.full_name,
        auth_provider=recruiter.auth_provider,
        company=CompanyResponse.model_validate(company),
    )


@router.get("/recruiter/google/login")
def recruiter_google_login() -> RedirectResponse:
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env.",
        )

    state = secrets.token_urlsafe(24)
    code_verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")

    params = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": f"{settings.app_base_url.rstrip('/')}/api/v1/auth/recruiter/google/callback",
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    oauth_cookie = create_session_token(
        subject_id=state,
        audience="oauth_state",
        ttl_seconds=600,
        extra={"cv": code_verifier, "role": "recruiter"},
    )
    resp = RedirectResponse(url=f"https://accounts.google.com/o/oauth2/v2/auth?{params}", status_code=302)
    set_role_cookie(resp, OAUTH_STATE_COOKIE_NAME, oauth_cookie, 600)
    return resp


@router.get("/recruiter/google/callback")
def recruiter_google_callback(
    request: Request,
    code: str,
    state: str,
    db: Annotated[Session, Depends(get_db)],
) -> RedirectResponse:
    settings = get_settings()
    state_cookie = request.cookies.get(OAUTH_STATE_COOKIE_NAME)
    payload = verify_session_token(state_cookie or "", expected_audience="oauth_state")
    if not payload or payload.get("sub") != state or payload.get("role") != "recruiter":
        raise HTTPException(status_code=400, detail="Invalid OAuth CSRF state.")

    with httpx.Client(timeout=20.0) as client:
        token_res = client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": f"{settings.app_base_url.rstrip('/')}/api/v1/auth/recruiter/google/callback",
                "grant_type": "authorization_code",
                "code_verifier": payload.get("cv", ""),
            },
        )
        token_res.raise_for_status()
        access_token = token_res.json()["access_token"]

        user_res = client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_res.raise_for_status()
        userinfo = user_res.json()

    if not userinfo.get("email_verified"):
        raise HTTPException(status_code=403, detail="Google account email must be verified.")

    recruiter = _provision_or_get_recruiter(
        db,
        email=userinfo["email"].lower(),
        full_name=userinfo.get("name", ""),
        auth_provider="google",
        google_sub=str(userinfo["sub"]),
    )
    session_token = create_session_token(subject_id=str(recruiter.id), audience="recruiter")
    resp = RedirectResponse(url=settings.frontend_base_url, status_code=302)
    clear_role_cookie(resp, OAUTH_STATE_COOKIE_NAME)
    clear_role_cookie(resp, APPLICANT_COOKIE_NAME)
    set_role_cookie(resp, RECRUITER_COOKIE_NAME, session_token, settings.session_ttl_seconds)
    return resp


@router.get("/recruiter/me", response_model=RecruiterProfileResponse)
def get_recruiter_me(
    ctx: Annotated[RecruiterContext, Depends(get_current_recruiter_context)],
) -> RecruiterProfileResponse:
    if ctx.recruiter is None:
        return RecruiterProfileResponse(
            id=ctx.company.id,
            email=f"api-key@{ctx.company.slug}.local",
            full_name=ctx.company.name,
            auth_provider="api_key",
            company=CompanyResponse.model_validate(ctx.company),
        )
    return RecruiterProfileResponse(
        id=ctx.recruiter.id,
        email=ctx.recruiter.email,
        full_name=ctx.recruiter.full_name,
        auth_provider=ctx.recruiter.auth_provider,
        company=CompanyResponse.model_validate(ctx.company),
    )


@router.post("/recruiter/mcp-key")
def rotate_mcp_api_key(
    ctx: Annotated[RecruiterContext, Depends(get_current_recruiter_context)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    """Generate/rotate the workspace X-API-Key so a Gmail/Magic-Link recruiter can connect Cursor or Claude Desktop."""
    new_key = generate_api_key()
    ctx.company.api_key_hash = hash_api_key(new_key)
    db.add(ctx.company)
    db.commit()
    return {"api_key": new_key, "company_slug": ctx.company.slug}


@router.post("/recruiter/invites", response_model=RecruiterInviteResponse, status_code=status.HTTP_201_CREATED)
def invite_recruiter_teammate(
    payload: RecruiterInviteRequest,
    ctx: Annotated[RecruiterContext, Depends(get_current_recruiter_context)],
    db: Annotated[Session, Depends(get_db)],
) -> RecruiterInviteResponse:
    if ctx.recruiter is None:
        raise HTTPException(
            status_code=400,
            detail="Sign in as a Recruiter via Magic Link or Google OAuth to send teammate invites.",
        )

    raw_invite = secrets.token_urlsafe(24)
    invite = CompanyInvite(
        company_id=ctx.company.id,
        invited_by_recruiter_id=ctx.recruiter.id,
        invited_email=payload.email,
        token_hash=hash_api_key(raw_invite),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return RecruiterInviteResponse(
        invite_id=invite.id,
        invited_email=invite.invited_email,
        invite_token=raw_invite,
    )


@router.post("/recruiter/logout")
def recruiter_logout(response: Response) -> dict[str, str]:
    clear_role_cookie(response, RECRUITER_COOKIE_NAME)
    return {"status": "signed_out"}


# ---------------------------------------------------------------------------
# Applicant Auth: GitHub OAuth ONLY (No Gmail login for applicants)
# ---------------------------------------------------------------------------


def _upsert_github_applicant(
    db: Session,
    *,
    github_id: str,
    github_handle: str,
    full_name: str,
    primary_email: str,
    verified_emails: list[str],
) -> Candidate:
    candidate = db.execute(select(Candidate).where(Candidate.github_id == github_id)).scalar_one_or_none()
    if candidate is None:
        candidate = db.execute(select(Candidate).where(Candidate.email == primary_email)).scalar_one_or_none()

    if candidate is None:
        candidate = Candidate(
            full_name=full_name or github_handle,
            email=primary_email,
            github_id=github_id,
            github_handle=github_handle,
            github_url=f"https://github.com/{github_handle}",
            verified_emails=verified_emails,
        )
        db.add(candidate)
    else:
        candidate.github_id = github_id
        candidate.github_handle = github_handle
        candidate.github_url = f"https://github.com/{github_handle}"
        candidate.verified_emails = sorted(set((candidate.verified_emails or []) + verified_emails))
        if full_name:
            candidate.full_name = full_name

    db.commit()
    db.refresh(candidate)
    return candidate


@router.get("/applicant/github/login")
def applicant_github_login() -> RedirectResponse:
    settings = get_settings()
    if not settings.github_client_id or not settings.github_client_secret:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="GitHub OAuth is not configured. Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in .env.",
        )

    state = secrets.token_urlsafe(24)
    params = urlencode(
        {
            "client_id": settings.github_client_id,
            "redirect_uri": f"{settings.app_base_url.rstrip('/')}/api/v1/auth/applicant/github/callback",
            "scope": "read:user user:email",
            "state": state,
        }
    )
    oauth_cookie = create_session_token(
        subject_id=state,
        audience="oauth_state",
        ttl_seconds=600,
        extra={"role": "applicant"},
    )
    resp = RedirectResponse(url=f"https://github.com/login/oauth/authorize?{params}", status_code=302)
    set_role_cookie(resp, OAUTH_STATE_COOKIE_NAME, oauth_cookie, 600)
    return resp


@router.get("/applicant/github/callback")
def applicant_github_callback(
    request: Request,
    code: str,
    state: str,
    db: Annotated[Session, Depends(get_db)],
) -> RedirectResponse:
    settings = get_settings()
    state_cookie = request.cookies.get(OAUTH_STATE_COOKIE_NAME)
    payload = verify_session_token(state_cookie or "", expected_audience="oauth_state")
    if not payload or payload.get("sub") != state or payload.get("role") != "applicant":
        raise HTTPException(status_code=400, detail="Invalid GitHub OAuth CSRF state.")

    with httpx.Client(timeout=20.0) as client:
        token_res = client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": f"{settings.app_base_url.rstrip('/')}/api/v1/auth/applicant/github/callback",
            },
        )
        token_res.raise_for_status()
        access_token = token_res.json().get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="GitHub OAuth failed to return an access token.")

        gh_headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
        }
        user_res = client.get("https://api.github.com/user", headers=gh_headers)
        user_res.raise_for_status()
        user = user_res.json()

        emails_res = client.get("https://api.github.com/user/emails", headers=gh_headers)
        verified_emails: list[str] = []
        primary_email = ""
        if emails_res.status_code == 200:
            for item in emails_res.json():
                if item.get("verified") and item.get("email"):
                    em = item["email"].lower()
                    verified_emails.append(em)
                    if item.get("primary"):
                        primary_email = em

        if not primary_email:
            primary_email = (verified_emails[0] if verified_emails else None) or (
                user.get("email") or f"{user['login']}@users.noreply.github.com"
            ).lower()
        if primary_email not in verified_emails:
            verified_emails.append(primary_email)

    # GitHub access_token is discarded immediately after fetching verified identity (zero token custody)
    candidate = _upsert_github_applicant(
        db,
        github_id=str(user["id"]),
        github_handle=user["login"],
        full_name=user.get("name") or user["login"],
        primary_email=primary_email,
        verified_emails=verified_emails,
    )
    session_token = create_session_token(subject_id=str(candidate.id), audience="applicant")
    resp = RedirectResponse(url=settings.frontend_base_url, status_code=302)
    clear_role_cookie(resp, OAUTH_STATE_COOKIE_NAME)
    clear_role_cookie(resp, RECRUITER_COOKIE_NAME)
    set_role_cookie(resp, APPLICANT_COOKIE_NAME, session_token, settings.session_ttl_seconds)
    return resp


@router.post("/applicant/dev-github", response_model=ApplicantProfileResponse)
def applicant_dev_github_login(
    payload: DevGitHubLoginRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> ApplicantProfileResponse:
    """
    Development-only simulated GitHub OAuth sign-in when GITHUB_CLIENT_ID is not configured.
    Blocked in production or when real GitHub OAuth is active.
    """
    settings = get_settings()
    if settings.app_env != "development" or (settings.github_client_id and settings.github_client_secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dev GitHub login is disabled when running outside development or when GitHub OAuth is configured.",
        )

    handle = payload.github_handle.strip().lstrip("@")
    email = payload.email.strip().lower()
    noreply = f"{handle.lower()}@users.noreply.github.com"
    candidate = _upsert_github_applicant(
        db,
        github_id=f"dev:{handle.lower()}",
        github_handle=handle,
        full_name=payload.full_name.strip(),
        primary_email=email,
        verified_emails=[email, noreply],
    )
    session_token = create_session_token(subject_id=str(candidate.id), audience="applicant")
    clear_role_cookie(response, RECRUITER_COOKIE_NAME)
    set_role_cookie(response, APPLICANT_COOKIE_NAME, session_token, settings.session_ttl_seconds)
    return ApplicantProfileResponse(
        id=candidate.id,
        full_name=candidate.full_name,
        email=candidate.email,
        github_handle=candidate.github_handle,
        github_url=candidate.github_url,
        verified_emails=candidate.verified_emails or [],
    )


@router.get("/applicant/me", response_model=ApplicantProfileResponse)
def get_applicant_me(
    current_applicant: Annotated[Candidate, Depends(get_current_applicant)],
) -> ApplicantProfileResponse:
    return ApplicantProfileResponse(
        id=current_applicant.id,
        full_name=current_applicant.full_name,
        email=current_applicant.email,
        github_handle=current_applicant.github_handle,
        github_url=current_applicant.github_url,
        verified_emails=current_applicant.verified_emails or [],
    )


@router.post("/applicant/logout")
def applicant_logout(response: Response) -> dict[str, str]:
    clear_role_cookie(response, APPLICANT_COOKIE_NAME)
    return {"status": "signed_out"}
