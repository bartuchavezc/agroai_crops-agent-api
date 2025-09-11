from sqlalchemy.orm import declarative_base
from src.app.database import shared_metadata # Import shared_metadata

# Base for all Reports-related tables, using shared metadata
Base = declarative_base(metadata=shared_metadata) 