import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.database import get_db
from app.models import Candidate, Company, Recruiter

RECRUITER_COOKIE_NAME = "air_recruiter_session"
APPLICANT_COOKIE_NAME = "air_applicant_session"
OAUTH_STATE_COOKIE_NAME = "air_oauth_state"


@dataclass(frozen=True)
class RecruiterContext:
    company: Company
    recruiter: Recruiter | None = None


def generate_api_key() -> str:
    """Generate a high-entropy tenant API key for FastMCP / headless API access."""
    return f"air_{secrets.token_urlsafe(32)}"


def hash_api_key(raw_key: str) -> str:
    """Hash API keys and magic-link tokens with SHA-256 so raw secrets are never persisted."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def slugify_company_name(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "company"
    suffix = secrets.token_hex(3)
    return f"{base[:100]}-{suffix}"


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(val: str) -> bytes:
    pad = "=" * ((4 - len(val) % 4) % 4)
    return base64.urlsafe_b64decode(val + pad)


def create_session_token(
    *,
    subject_id: str,
    audience: str,
    ttl_seconds: int | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    """Create an HMAC-SHA256 signed role-scoped session token."""
    settings = get_settings()
    ttl = ttl_seconds if ttl_seconds is not None else settings.session_ttl_seconds
    payload: dict[str, Any] = {
        "sub": subject_id,
        "aud": audience,
        "exp": int(time.time()) + ttl,
        "nonce": secrets.token_hex(8),
    }
    if extra:
        payload.update(extra)

    body_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = hmac.new(settings.auth_secret.encode("utf-8"), body_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{body_b64}.{_b64url_encode(sig)}"


def verify_session_token(token: str, *, expected_audience: str) -> dict[str, Any] | None:
    """Verify HMAC signature, expiration, and strict audience separation."""
    settings = get_settings()
    if "." not in token:
        return None
    body_b64, _, sig_b64 = token.partition(".")
    expected_sig = hmac.new(
        settings.auth_secret.encode("utf-8"), body_b64.encode("ascii"), hashlib.sha256
    ).digest()
    try:
        actual_sig = _b64url_decode(sig_b64)
    except Exception:
        return None
    if not hmac.compare_digest(expected_sig, actual_sig):
        return None

    try:
        payload = json.loads(_b64url_decode(body_b64).decode("utf-8"))
    except Exception:
        return None

    if payload.get("aud") != expected_audience:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


def set_role_cookie(response: Response, cookie_name: str, token: str, max_age: int) -> None:
    settings = get_settings()
    response.set_cookie(
        key=cookie_name,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_role_cookie(response: Response, cookie_name: str) -> None:
    response.delete_cookie(key=cookie_name, path="/")


def resolve_company_by_key(db: Session, raw_key: str) -> Company | None:
    key_hash = hash_api_key(raw_key)
    stmt = select(Company).where(Company.api_key_hash == key_hash)
    return db.execute(stmt).scalar_one_or_none()


def _extract_optional_api_key(
    x_api_key: str | None,
    authorization: str | None,
) -> str | None:
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            return token.strip()
    return None


def get_current_recruiter_context(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> RecruiterContext:
    """
    Recruiter-only FastAPI Depends() boundary.
    Accepts either:
      1. Tenant API Key (`X-API-Key` / `Authorization: Bearer air_...`) for headless/MCP use, OR
      2. Role-scoped `air_recruiter_session` HTTP-only cookie (`aud == "recruiter"`).
    Applicant sessions are strictly rejected.
    """
    raw_key = _extract_optional_api_key(x_api_key, authorization)
    if raw_key:
        company = resolve_company_by_key(db, raw_key)
        if company is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid tenant API key.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return RecruiterContext(company=company, recruiter=None)

    cookie_token = request.cookies.get(RECRUITER_COOKIE_NAME)
    if cookie_token:
        payload = verify_session_token(cookie_token, expected_audience="recruiter")
        if payload and payload.get("sub"):
            try:
                recruiter_id = uuid.UUID(str(payload["sub"]))
            except ValueError:
                recruiter_id = None
            if recruiter_id is not None:
                recruiter = db.execute(
                    select(Recruiter)
                    .options(joinedload(Recruiter.company))
                    .where(Recruiter.id == recruiter_id)
                ).scalar_one_or_none()
                if recruiter is not None and recruiter.company is not None:
                    return RecruiterContext(company=recruiter.company, recruiter=recruiter)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Recruiter authentication required (Magic Link, Google OAuth, or X-API-Key).",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_company(
    ctx: Annotated[RecruiterContext, Depends(get_current_recruiter_context)],
) -> Company:
    """Backward-compatible tenant Company dependency for recruiter & workspace routes."""
    return ctx.company


def get_current_applicant(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> Candidate:
    """
    Applicant-only FastAPI Depends() boundary.
    Accepts ONLY `air_applicant_session` HTTP-only cookie (`aud == "applicant"`).
    Recruiter cookies and API keys are strictly rejected.
    """
    cookie_token = request.cookies.get(APPLICANT_COOKIE_NAME)
    if not cookie_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Applicant GitHub authentication required.",
        )

    payload = verify_session_token(cookie_token, expected_audience="applicant")
    if not payload or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired applicant session.",
        )

    try:
        candidate_id = uuid.UUID(str(payload["sub"]))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid applicant session.") from exc

    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Applicant account not found.")
    return candidate
