import os
import httpx
from dotenv import load_dotenv
from app.rate_limiter import acquire_rate_limit

# Load variables from the .env file into os.environ
load_dotenv()

JINA_API_KEY = os.getenv("JINA_API_KEY")
JINA_API_URL = "https://api.jina.ai/v1/embeddings"
JINA_MODEL = "jina-embeddings-v3"

# We batch chunks in groups of 32 so we don't send massive payloads in a single HTTP request
BATCH_SIZE = 32

def embed_texts(texts: list[str], task: str = "retrieval.passage") -> list[list[float]]:
    """
    Sends a list of strings to the Jina AI Embeddings API and returns their 1024-d vectors.
    
    :param texts: List of code chunks or search queries.
    :param task: 'retrieval.passage' when indexing code chunks;
                 'retrieval.query' when searching with a job criterion.
    """
    if not JINA_API_KEY or JINA_API_KEY == "jina_your_actual_copied_key_here":
        raise ValueError("JINA_API_KEY is missing or invalid. Check your .env file!")

    if not texts:
        return []

    all_embeddings: list[list[float]] = []

    headers = {
        "Authorization": f"Bearer {JINA_API_KEY}",
        "Content-Type": "application/json",
    }

    # Use a persistent HTTP client for connection pooling across batches
    with httpx.Client(timeout=60.0) as client:
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]
            payload = {
                "model": JINA_MODEL,
                "task": task,
                "dimensions": 1024,
                "truncate": True,  # Safely truncate if any single chunk exceeds 8,192 tokens
                "input": batch,
            }

            # Estimate ~1 token per 4 characters; Jina free tier allows 100 RPM / 100,000 TPM
            est_tokens = max(100, sum(len(t) for t in batch) // 4)
            acquire_rate_limit("jina", rpm_limit=90, tpm_limit=90_000, estimated_tokens=est_tokens)
            
            response = client.post(JINA_API_URL, headers=headers, json=payload)
            response.raise_for_status()  # Raises httpx.HTTPStatusError on 4xx/5xx (like 429 Rate Limit)

            data = response.json()
            # Ensure embeddings are sorted in the exact order of our input batch
            sorted_items = sorted(data["data"], key=lambda item: item["index"])
            batch_vectors = [item["embedding"] for item in sorted_items]
            all_embeddings.extend(batch_vectors)

    return all_embeddings