import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Set up database engines and session makers for reader and writer connections
engine_writer = create_engine(os.getenv("DATABASE_URL_WRITER"), pool_pre_ping=True)
engine_reader = create_engine( os.getenv("DATABASE_URL_READER"), pool_pre_ping=True)

# Create session makers for both reader and writer engines
SessionLocalWriter = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine_writer
)

# Session maker for reader engine
SessionLocalReader = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine_reader
)

# Base class for declarative models
Base = declarative_base()

def get_write_db():
    """
    Dependency function to get a database session for writing operations. 
    This function is used in FastAPI routes to provide a database session that is properly closed after the request is processed.
    Yields: Session: A SQLAlchemy session for database operations.
    """
    db = SessionLocalWriter()
    try:
        yield db
    finally:
        db.close()


def get_read_db():
    """
    Dependency function to get a database session for reading operations. 
    This function is used in FastAPI routes to provide a database session that is properly closed after the request is processed.
    Yields: Session: A SQLAlchemy session for database operations.
    """
    db = SessionLocalReader()
    try:
        yield db
    finally:
        db.close()