# AI Recruiter — Evidence-Based Technical Vetting Platform & MCP Server

An end-to-end, multi-tenant technical vetting platform that clones candidate GitHub repositories ephemerally, parses code via Tree-sitter ASTs, indexes embeddings in PostgreSQL + `pgvector` (HNSW), evaluates candidates against a 5-point JD rubric with a stateful LangGraph agent, and exposes tenant-isolated FastMCP tools for Claude Desktop and Cursor.

## Architecture Overview

- **Backend & MCP (`backend/app/`)**: FastAPI + FastMCP 4.x + Uvicorn (`main.py`, `mcp_server.py`), SQLAlchemy 2.x + Alembic (`models.py`, `database.py`), tenant API-key authentication via `Depends()` (`security.py`).
- **Ingestion Pipeline (`tasks.py`, `chunker.py`, `embeddings.py`)**: Celery worker on `queue_ingestion` runs `git clone --depth 1` into `tempfile.TemporaryDirectory()`, parses Python/JS/TS/TSX ASTs with Tree-sitter, batches embeddings (Jina v3), bulk-inserts into `code_chunks`, and deletes the cloned repo automatically.
- **Rate Limiting (`rate_limiter.py`)**: Dual-layer defense combining a global atomic Redis Lua Token Bucket (RPM + TPM) across all Celery workers with Celery `autoretry_for` exponential backoff and jitter.
- **LangGraph Evaluator (`evaluator.py`, `retrieval.py`)**: Celery worker on `queue_evaluation` extracts a 5-point rubric (`RubricOutput`), loops through each criterion retrieving tenant-isolated `pgvector` chunks (`companies -> jobs -> applications -> candidates -> repositories -> code_chunks` inner join *before* vector distance ordering), and enforces strict Pydantic structured outputs (`CriterionEvaluation`: 1–5 score, 2-sentence justification, grounded `referenced_files`).
- **Frontend (`frontend/`)**: React + TypeScript + Vite + Tailwind CSS v4 dashboard with accessible native `<dialog>` modals, responsive container-queried candidate table, live status polling, semantic code explorer, and MCP client config generator.
- **Deployment (`docker-compose.yml`, `deploy/`)**: PostgreSQL (`pgvector/pgvector:pg16`), PgBouncer transaction pooling, Redis, Alembic migration job, horizontally scalable FastAPI/FastMCP API, segregated Celery workers (`queue_ingestion`, `queue_evaluation`), and Nginx configured for long-lived SSE MCP connections.

## Quick Start (Docker Compose)

1. Configure `.env` from `.env.example` (set `GROQ_API_KEY` and `JINA_API_KEY`; without them, deterministic offline fallbacks are used for local testing).
2. Start the full stack:
   ```bash
   docker compose up --build
   ```
3. Open the dashboard at `http://localhost:3000` (API & MCP docs at `http://localhost:8000/docs`).

## Local Development & Tests

```bash
# Backend tests
cd backend
../venv/bin/pytest

# Frontend build check
cd ../frontend
npm run build
```
