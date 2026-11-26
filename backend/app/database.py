from collections.abc import Generator
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def normalize_database_url(url: str) -> str:
    """Normalize plain postgres URLs to use psycopg3 driver."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def build_engine(url: str | None = None, *, for_migrations: bool = False) -> Engine:
    settings = get_settings()
    raw_url = url or (settings.direct_database_url if for_migrations else settings.database_url)
    db_url = normalize_database_url(raw_url)

    kwargs: dict[str, Any] = {"pool_pre_ping": True}

    if db_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    elif not for_migrations and (settings.use_pgbouncer or ":6432" in db_url):
        # PgBouncer transaction-pooling disables server-side prepared statements
        kwargs["poolclass"] = NullPool
        kwargs["connect_args"] = {"prepare_threshold": None}

    return create_engine(db_url, **kwargs)


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a scoped SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_db_connection(db: Session) -> bool:
    """Quick connectivity check used by /health."""
    db.execute(text("SELECT 1"))
    return True
