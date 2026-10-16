# app/main.py
from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from contextlib import asynccontextmanager

from app.database import engine, Base, get_db
import app.models  # We must import models here so SQLAlchemy knows they exist before creating tables

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    The lifespan context manager handles startup and shutdown events.
    Code before the `yield` runs when the server starts.
    Code after the `yield` runs when the server stops.
    """
    print("Initializing Database...")
    # This command creates the tables in Postgres based on our classes in models.py.
    # We must explicitly create the pgvector extension first.
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully.")
    
    yield
    
    print("Shutting down server...")

# Initialize the FastAPI application
app = FastAPI(
    title="AI Recruiter API",
    description="Evidence-Based Technical Vetting Platform Backend",
    version="0.1.0",
    lifespan=lifespan
)

@app.get("/")
def read_root():
    return {"message": "AI Recruiter API is running. FastMCP endpoints pending."}

@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    """
    A simple endpoint to verify the API can talk to the Postgres database.
    """
    try:
        # We run a raw SQL query to verify the connection
        db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": str(e)}