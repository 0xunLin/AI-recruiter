from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# In production, this URL will come from a secure environment variable.
# For now, we define a standard local PostgreSQL connection string.
DATABASE_URL = "postgresql://postgres:password@localhost:5432/recruiter_db"

# The Engine is the actual factory that maintains the connection pool to the database.
engine = create_engine(DATABASE_URL, echo=False)

# The SessionLocal is a temporary workspace for a specific transaction. 
# We create a new one for every HTTP request.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# All of our database models (Users, Jobs) will inherit from this Base class.
Base = declarative_base()

def get_db():
    """
    A dependency function that yields a database session for a single request,
    and guarantees it closes safely when request finishes.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close() # block strictly ensures the conversation ends. If we don't close sessions, the server eventually runs out of memory and crashes.