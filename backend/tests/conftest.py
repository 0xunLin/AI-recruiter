import math
import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.dependencies import get_evaluation_dispatcher, get_ingestion_dispatcher
from app.main import app
from app.models import CodeChunk


class FakeEmbeddingProvider:
    """Deterministic small-vocabulary embedding provider for unit/integration tests."""

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def embed_texts(self, texts: list[str], *, task: str = "retrieval.passage") -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            for word in text.lower().replace("/", " ").replace("_", " ").split():
                idx = sum(ord(ch) for ch in word) % self.dim
                vec[idx] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors


@pytest.fixture()
def db_session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _conn_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    try:
        yield TestingSessionLocal
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def db(db_session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = db_session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def patch_sqlite_cosine(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    SQLite lacks pgvector's `<=>` operator. Replace CodeChunk.embedding.cosine_distance
    with a SQL-safe expression so the real SQLAlchemy INNER JOIN + WHERE tenant filters
    execute against SQLite during unit tests.
    """
    from sqlalchemy import literal

    class _CompatEmbeddingCol:
        def __init__(self, col: Any) -> None:
            self._col = col

        def __getattr__(self, name: str) -> Any:
            return getattr(self._col, name)

        def cosine_distance(self, _vec: list[float]) -> Any:
            return literal(0.05)

    monkeypatch.setattr(CodeChunk, "embedding", _CompatEmbeddingCol(CodeChunk.embedding))


@pytest.fixture()
def api_client(
    db_session_factory: sessionmaker[Session],
    patch_sqlite_cosine: None,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, list[uuid.UUID], list[uuid.UUID]], None, None]:
    from app.evaluator import DeterministicFallbackLLM

    dispatched_ingestions: list[uuid.UUID] = []
    dispatched_evaluations: list[uuid.UUID] = []

    def override_get_db() -> Generator[Session, None, None]:
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr("app.evaluator.get_llm_client", lambda: DeterministicFallbackLLM())
    monkeypatch.setattr("app.resume_parser.get_llm_client", lambda: DeterministicFallbackLLM())

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_ingestion_dispatcher] = lambda: (
        lambda app_id: dispatched_ingestions.append(app_id)
    )
    app.dependency_overrides[get_evaluation_dispatcher] = lambda: (
        lambda app_id: dispatched_evaluations.append(app_id)
    )

    with TestClient(app) as client:
        yield client, dispatched_ingestions, dispatched_evaluations

    app.dependency_overrides.clear()
