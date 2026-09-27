from datetime import datetime, timezone

from src.shared.database import Base

DomainBase = Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
