from sqlalchemy import Column, Integer, String, Text, ForeignKey, JSON, Index
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.database import Base

class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)

    # Relationships help us easily traverse the database in Python
    jobs = relationship("Job", back_populates="company")

class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)  # The raw Job Description
    rubric = Column(JSON, nullable=True)    # The AI-extracted 5-point evaluation criteria

    company = relationship("Company", back_populates='jobs')
    applications = relationship("Application", back_populates="job")

class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    github_handle = Column(String, nullable=False)

    applications = relationship("Application", back_populates="candidate")
    repositories = relationship("Repository", back_populates="candidate")

class Application(Base):
    """
    SECURITY GATEWAY: This table is the critical junction.
    It proves that a specific candidate explicitly applied for a specific job.
    """
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False)
    evaluation_score = Column(Integer, nullable=True)
    evaluation_report = Column(JSON, nullable=True)  # Stores the 5-point evidence breakdown

    job = relationship("Job", back_populates="applications")
    candidate = relationship("Candidate", back_populates="applications")

class Repository(Base):
    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False)
    name = Column(String, nullable=False)
    clone_url = Column(String, nullable=False)

    candidate = relationship("Candidate", back_populates="repositories")
    chunks = relationship("CodeChunk", back_populates="repository")

class CodeChunk(Base):
    """
    THE AI MEMORY: Stores the actual chunks of code and their vector embeddings.
    """
    __tablename__ = "code_chunks"

    id = Column(Integer, primary_key=True, index=True)
    repository_id = Column(Integer, ForeignKey("repositories.id"), nullable=False)
    file_path = Column(String, nullable=False)
    content = Column(Text, nullable=False)  # The actual raw text of the function/class

    # Jina v3 outputs 1024 dimensions by default.
    embedding = Column(Vector(1024))

    repository = relationship("Repository", back_populates="chunks")

    # HNSW Index using Cosine Distance (vector_cosine_ops) for fast similarity search
    __table_args__ = (
        Index(
            "ix_code_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )