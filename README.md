# RECRUISE — Resume-to-Code Verification & Anti-Vibe-Coding Platform

An end-to-end, multi-tenant technical vetting platform that extracts project claims and embedded GitHub links from candidate resumes, verifies contributions surgically via GitHub Trees/Patch APIs + Tree-sitter ASTs + `pgvector` (HNSW), scores candidates out of 10 with a 5-node **LangGraph** agent, filters the **top 30%** shortlist, and exposes tenant-isolated **FastMCP** tools (including anti-vibe-coding interview probes) for **Cursor** and **Claude Desktop**.

---

## Architecture Overview

- **Dual-Role Auth (`backend/app/auth_routes.py`, `security.py`):** Separate identity tables and RBAC for **Recruiters** (Magic Link email or Gmail OAuth) and **Applicants** (GitHub OAuth).
- **Backend & MCP (`backend/app/`):** FastAPI + FastMCP + Uvicorn (`main.py`, `applicant_routes.py`, `mcp_server.py`), SQLAlchemy 2.x + Alembic (`models.py`, `database.py`), tenant-isolated API-key authentication (`X-API-Key`).
- **Surgical Ingestion Pipeline (`tasks.py`, `resume_parser.py`, `chunker.py`, `embeddings.py`):**
  - Extracts text and embedded PDF `/Annots` (`/URI`) hyperlinks from uploaded resumes.
  - Uses GitHub's lightweight **Trees & Patch REST APIs** (`0` full-repo cloning) to fetch prioritized source files or `.patch` diffs, parses Python/JS/TS/TSX ASTs with **Tree-sitter**, embeds chunks via **Jina v3** (`1024`-d) into PostgreSQL `pgvector` (HNSW), and fans out per-repo tasks in a fault-isolated Celery `chord`.
- **Rate Limiting (`rate_limiter.py`):** Global atomic Redis Lua Token Bucket (RPM + TPM) across workers, paired with `Retry-After` handling and exponential backoff.
- **5-Node LangGraph Evaluator & Anti-Vibe-Coding Guardrails (`evaluator.py`, `retrieval.py`, `shortlist.py`):**
  - Scores each application out of **10** (`Claim Integrity /4` + `Authorship /2` + `Tech Depth /4`) and automatically shortlists the **top 30%** (`>= 6.0`).
  - Excludes `README.md`/comments/TODO stubs as implementation proof, tags `[SINGLE-COMMIT DUMP]` repositories, evaluates candidate **Ownership Defense** answers, and generates code-grounded **Interview Probes** (`get_candidate_interview_probes`).
- **Frontend (`frontend/`):** React + TypeScript + Vite + Tailwind CSS v4 in a **Minimalist Brutalist / Utilitarian Wireframe** aesthetic (Dark Mode default with a header Light/Dark toggle).
- **Deployment (`docker-compose.yml`, `deploy/`):** PostgreSQL (`pgvector/pgvector:pg16`), PgBouncer transaction pooling, Redis, Alembic migrations, FastAPI/FastMCP API, segregated Celery workers (`queue_ingestion`, `queue_evaluation`), and Nginx.

---

## How to Launch

1. **Configure `.env`** from `.env.example` in the project root:
   ```env
   DATABASE_URL=postgresql://postgres:password@localhost:5432/recruiter_db
   GROQ_API_KEY=your_groq_api_key
   GROQ_MODEL=openai/gpt-oss-120b
   JINA_API_KEY=your_jina_api_key

   # Optional: Live GitHub OAuth (Applicants) & SMTP Magic Links (Recruiters)
   # Without these, built-in dev-mode fallbacks are used automatically.
   GITHUB_CLIENT_ID=
   GITHUB_CLIENT_SECRET=
   SMTP_HOST=
   SMTP_PORT=587
   SMTP_USERNAME=
   SMTP_PASSWORD=
   SMTP_FROM_EMAIL=
   ```
   *(For GitHub OAuth, set Homepage URL to `http://localhost:3000` and Authorization callback URL to `http://localhost:8000/api/v1/auth/applicant/github/callback`.)*

2. **Start the full stack:**
   ```bash
   docker compose up -d --build
   ```

3. **Open the app:**
   - **Web UI:** `http://localhost:3000`
   - **API & Swagger Docs:** `http://localhost:8000/docs`
   - **Health Check:** `http://localhost:3000/health`

---

## Step-by-Step Guide: Recruiter

1. **Sign In:** Open `http://localhost:3000`, select **Recruiter → Continue with email**, enter your email, and click the magic link (sent via SMTP if configured, or shown inline in dev mode).
2. **Create a Job & 5-Point Rubric:** Go to **Jobs → New Job**, enter a role title and technical job description, and click **Create Job**. The backend extracts a weighted 5-point evaluation rubric.
3. **Review Candidates & Shortlist:** Go to **Candidates** (or wait for applicants to apply, or click **Submit Resume** directly). Watch statuses move through `PENDING` → `CLONING` → `EVALUATING` → `VERIFIED`, and toggle **Top 30%** to filter shortlisted candidates (`>= 6.0 / 10`).
4. **Inspect Verification Dossier:** Click **Inspect** on any candidate to review:
   - **Claims:** `/4.0` claim integrity, authorship match, `[SINGLE-COMMIT DUMP]` provenance flags, and the candidate's Ownership Defense Q&A.
   - **Probes:** Auto-generated, file-anchored anti-vibe-coding interview questions and what to listen for.
   - **Rubric / Resume / Audit Trail:** Criterion scores (`/5`), extracted resume text, and SHA-256 sealed LangGraph logs.
5. **Semantic Code Search:** Open **Code Search**, select a candidate, and query their indexed repository chunks by behavior, symbol, or file path.
6. **Connect Cursor / Claude Desktop (MCP):** Click **MCP Config** in the top bar, click **Generate Key**, and copy the JSON config into `.cursor/mcp.json` or Claude Desktop to query `list_shortlisted_candidates`, `search_candidate_code`, and `get_candidate_interview_probes`.

---

## Step-by-Step Guide: Applicant

1. **Sign In with GitHub:** Open `http://localhost:3000` and select **Applicant → Continue with GitHub** (redirects to GitHub OAuth when configured, or uses the dev GitHub form locally).
2. **Browse & Apply:** Under **Open Roles**, click **Apply with Resume** on a role and upload a `.pdf`, `.txt`, or `.md` resume (embedded PDF hyperlinks are extracted automatically) or paste resume text.
3. **Select Commits / Key Files & Ownership Defense:**
   - For each extracted project claim, select the **commits** (for multi-commit/OSS repos) or **key source files** from the GitHub file tree (for single-commit solo repos) that fulfill that claim.
   - Answer the short **Ownership Check** question explaining your architecture, edge cases, or tradeoffs, then click **Confirm Evidence & Start Verification**.
4. **Track Status:** View your submitted applications and GitHub link accessibility statuses under **My Applications**.

---

## Local Tests & Frontend Build

```bash
# Frontend TypeScript & Vite build check
cd frontend
npm run build
```
