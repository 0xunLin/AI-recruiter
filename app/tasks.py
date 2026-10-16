import os
import subprocess
import tempfile
import logging
import httpx
from app.celery_app import celery_app
from app.database import SessionLocal
from app.models import Repository, CodeChunk
from app.chunker import chunk_repository
from app.embeddings import embed_texts
# Configure logging so we can see clear output in the Celery terminal
logger = logging.getLogger(__name__)

@celery_app.task(
    bind=True,
    # Catch git non-zero exits, git 120s timeouts, and Jina HTTP/Rate-Limit errors
    autoretry_for=(
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        httpx.HTTPError,
    ),
    retry_backoff=True,       # Exponential backoff (waits 2s, 4s, 8s...)
    retry_backoff_max=600,    # Caps the maximum wait time at 10 minutes
    retry_jitter=True,        # Adds randomness to prevent "thundering herd" retries
    max_retries=3
)

def ingest_repository_task(self, repo_id: int):
    """
    1. Shallow-clones a candidate repository into an ephemeral directory.
    2. Chunks source files by AST functions/classes using Tree-sitter.
    3. Generates 1024-d embeddings in batches via Jina AI (retrieval.passage).
    4. Bulk-inserts chunks + vectors into PostgreSQL pgvector.
    5. Automatically wipes the cloned repository from disk.
    """
    db = SessionLocal()
    try:
        # Fetch the repository metadata from PostgreSQL
        repo = db.query(Repository).filter(Repository.id == repo_id).first()
        if not repo:
            logger.error(f"Repository ID {repo_id} not found in database.")
            return {"status": "error", "message": "Repository not found"}

        logger.info(f"Starting ingestion for {repo.name} ({repo.clone_url})")

        # Step 1: Ephemeral shallow clone
        # Create an isolated, self-destructing temporary directory
        with tempfile.TemporaryDirectory(prefix=f"repo_{repo_id}_") as temp_dir:
            # Run shallow git clone (--depth 1) for speed and minimal disk usage
            clone_cmd = [
                "git", "clone",
                "--depth", "1",
                "--single-branch",
                repo.clone_url,
                temp_dir
            ]
            
            # Disable git interactive terminal prompts (so workers never hang waiting for a password)
            env = os.environ.copy()
            env["GIT_TERMINAL_PROMPT"] = "0"

            subprocess.run(
                clone_cmd,
                env=env,
                check=True,           # Raises CalledProcessError if git returns a non-zero exit code
                capture_output=True,
                text=True,
                timeout=120           # Hard 2-minute timeout so massive repos don't hang the worker
            )

            # Step 2: AST Chunking via Tree-sitter
            extracted_chunks = chunk_repository(temp_dir)
            logger.info(f"Extracted {len(extracted_chunks)} semantic AST chunks from {repo.name}.")

            # The 'with tempfile' block has exited: the cloned repo is now wiped from disk.

        # Notice: We are now OUTSIDE the 'with tempfile' block!

        # Step 3: Idempotent cleanup FIRST (ensures stale chunks are removed even if repo is now empty)
        deleted_count = db.query(CodeChunk).filter(CodeChunk.repository_id == repo.id).delete()
        if deleted_count:
            logger.info(f"Removed {deleted_count} stale chunks for {repo.name}.")

        if not extracted_chunks:
            db.commit()
            logger.warning(f"No supported code chunks found in {repo.name}.")
            return {"status": "success", "repo_id": repo_id, "chunks_ingested": 0}
        
        # Step 4: Batch-generate embeddings using Jina AI's 'retrieval.passage' adapter
        chunk_texts = [c.content for c in extracted_chunks]
        logger.info(f"Requesting Jina v3 embeddings for {len(chunk_texts)} chunks...")
        vectors = embed_texts(chunk_texts, task="retrieval.passage")

        # Step 5: Fail-fast validation (strict=True raises ValueError if counts ever mismatch)
        if len(extracted_chunks) != len(vectors):
            raise ValueError(
                f"Embedding count mismatch: {len(extracted_chunks)} chunks vs {len(vectors)} vectors"
            )

        db_objects = [
            CodeChunk(
                repository_id=repo.id,
                file_path=chunk.file_path,
                content=chunk.content,
                embedding=vector
            )
            for chunk, vector in zip(extracted_chunks, vectors, strict=True)
        ]

        # Bulk-insert all rows in a single database round-trip
        db.bulk_save_objects(db_objects)
        db.commit()
        logger.info(f"Successfully bulk-inserted {len(db_objects)} vectorized chunks for {repo.name}!")

        return {
            "status": "success",
            "repo_id": repo_id,
            "chunks_ingested": len(db_objects),
            "stale_chunks_removed": deleted_count
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed ingesting repo {repo_id}: {e}")
        raise
    finally:
        # Always close the SQLAlchemy session inside background tasks
        db.close()

from app.evaluator import run_candidate_evaluation

@celery_app.task(
    bind=True,
    # Layer 2 Rate-Limit Defense: Exponential backoff + jitter if Groq/Jina returns 429
    autoretry_for=(httpx.HTTPError, Exception),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3
)
def evaluate_candidate_task(self, application_id: int):
    """
    Runs the stateful LangGraph 5-point rubric evaluation on `queue_evaluation`.
    """
    logger.info(f"Starting LangGraph evaluation for Application ID: {application_id}")
    report = run_candidate_evaluation(application_id)
    logger.info(
        f"Completed evaluation for Application ID {application_id}. "
        f"Final Score: {report['final_score']}/100"
    )
    return report