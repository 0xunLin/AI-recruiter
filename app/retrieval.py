from dataclasses import dataclass
from sqlalchemy.orm import Session
from app.models import Company, Job, Application, Candidate, Repository, CodeChunk
from app.embeddings import embed_texts


@dataclass
class RetrievedChunk:
    """Represents a code chunk returned from pgvector along with its similarity score."""
    chunk_id: int
    file_path: str
    content: str
    similarity: float


def search_candidate_code(
    db: Session,
    company_id: int,
    job_id: int,
    candidate_id: int,
    query_text: str,
    top_k: int = 5,
) -> list[RetrievedChunk]:
    """
    Executes a tenant-isolated vector similarity search in PostgreSQL.
    
    SECURITY BOUNDARY:
    Joins CodeChunk -> Repository -> Candidate -> Application -> Job -> Company.
    If the candidate did not apply to this specific job, or the job does not belong
    to this company, the SQL inner join returns 0 rows.
    """
    # 1. Embed the natural language search query using Jina's asymmetric query adapter
    query_vectors = embed_texts([query_text], task="retrieval.query")
    if not query_vectors:
        return []
    query_vector = query_vectors[0]

    # 2. Calculate Cosine Distance (<=> operator in pgvector).
    # Cosine distance ranges from 0.0 (identical) to 2.0 (opposite).
    # Cosine similarity is simply (1.0 - cosine_distance).
    distance_col = CodeChunk.embedding.cosine_distance(query_vector).label("distance")

    # 3. Execute the Relational Security Join + Vector Order By
    results = (
        db.query(CodeChunk, distance_col)
        .join(Repository, CodeChunk.repository_id == Repository.id)
        .join(Candidate, Repository.candidate_id == Candidate.id)
        .join(Application, Application.candidate_id == Candidate.id)
        .join(Job, Application.job_id == Job.id)
        .join(Company, Job.company_id == Company.id)
        .filter(
            Company.id == company_id,
            Job.id == job_id,
            Candidate.id == candidate_id,
        )
        .order_by(distance_col.asc())  # Closest geometric vectors first
        .limit(top_k)
        .all()
    )

    return [
        RetrievedChunk(
            chunk_id=chunk.id,
            file_path=chunk.file_path,
            content=chunk.content,
            similarity=round(1.0 - float(distance), 4),
        )
        for chunk, distance in results
    ]