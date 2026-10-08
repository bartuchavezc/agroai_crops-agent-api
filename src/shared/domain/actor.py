from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from src.auth.domain.models import MANAGER_ROLES, ROLE_OWNER


@dataclass(frozen=True)
class Actor:
    """Who is performing an operation. Services scope every query by account_id."""
    user_id: UUID
    account_id: UUID
    role: str
    via: Literal["user", "agent", "system"] = "user"
    # Where the person is: the agent speaks and tells time accordingly (see src/shared/domain/locale.py).
    country: str = "AR"
    timezone: str | None = None
    locale: str = "es-AR"

    @property
    def is_manager(self) -> bool:
        return self.role in MANAGER_ROLES

    @property
    def is_owner(self) -> bool:
        return self.role == ROLE_OWNER

    @classmethod
    def from_user(cls, user, via: Literal["user", "agent"] = "user") -> "Actor":
        return cls(
            user_id=user.id, account_id=user.account_id, role=user.role, via=via,
            country=getattr(user, "country", None) or "AR",
            timezone=getattr(user, "timezone", None),
            locale=getattr(user, "locale", None) or "es-AR",
        )
