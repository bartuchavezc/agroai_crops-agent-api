# src/shared/domain/base.py
"""
Base classes for domain models.
"""
from sqlalchemy.orm import declarative_base
from src.shared.database import shared_metadata

# Base for all domain tables using shared metadata
DomainBase = declarative_base(metadata=shared_metadata)
