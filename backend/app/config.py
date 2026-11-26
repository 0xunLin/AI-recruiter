from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings loaded from environment variables and root .env."""

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="development")
    app_name: str = Field(default="AI Recruiter Platform")
    app_base_url: str = Field(default="http://localhost:8000")
    frontend_base_url: str = Field(default="http://localhost:3000")

    # Database (PgBouncer in production/Docker, Postgres directly for migrations/local)
    database_url: str = Field(
        default="postgresql+psycopg://postgres:password@localhost:5432/recruiter_db"
    )
    direct_database_url: str = Field(
        default="postgresql+psycopg://postgres:password@localhost:5432/recruiter_db"
    )
    use_pgbouncer: bool = Field(default=False)

    # Redis
    redis_broker_url: str = Field(default="redis://localhost:6379/0")
    redis_backend_url: str = Field(default="redis://localhost:6379/1")
    redis_rate_limit_url: str = Field(default="redis://localhost:6379/2")

    # AI Providers
    groq_api_key: str = Field(default="")
    groq_model: str = Field(default="llama-3.3-70b-versatile")
    jina_api_key: str = Field(default="")
    jina_embedding_model: str = Field(default="jina-embeddings-v3")
    embedding_dim: int = Field(default=1024)

    # Rate Limiting (Global Token Bucket across workers)
    llm_rpm_limit: int = Field(default=30)
    llm_tpm_limit: int = Field(default=60000)
    embedding_rpm_limit: int = Field(default=20)
    embedding_tpm_limit: int = Field(default=80000)

    # Dual-Role Auth (Sessions, Magic Links, Google OAuth for Recruiters, GitHub OAuth for Applicants)
    auth_secret: str = Field(default="dev-insecure-change-me-in-production-32bytes")
    session_ttl_seconds: int = Field(default=60 * 60 * 24 * 7)
    magic_link_ttl_seconds: int = Field(default=900)
    cookie_secure: bool = Field(default=False)

    google_client_id: str = Field(default="")
    google_client_secret: str = Field(default="")
    github_client_id: str = Field(default="")
    github_client_secret: str = Field(default="")

    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_username: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_from_email: str = Field(default="noreply@ai-recruiter.local")

    # Security & Ingestion Limits
    cors_origins: str = Field(default="http://localhost:5173,http://localhost:3000")
    max_repo_files: int = Field(default=50)
    max_chunks_per_repo: int = Field(default=96)
    max_file_bytes: int = Field(default=262144)
    clone_timeout_seconds: int = Field(default=120)
    max_repos_per_resume: int = Field(default=6)

    # Top-30% Shortlisting Thresholds
    shortlist_top_percent: float = Field(default=0.30)
    shortlist_min_score: float = Field(default=6.0)

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
