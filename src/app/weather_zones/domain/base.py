from sqlalchemy.orm import declarative_base
from src.app.database import shared_metadata

Base = declarative_base(metadata=shared_metadata) 