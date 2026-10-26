"""TEMPORARY — whose Gemini key pays for the work nobody asked for in a turn (the summaries, the proactive check)
while every account brings its own key (BYOK). When the platform pays for it, delete this module and its callers:
every place that picks a key for background work imports from here."""
from typing import Optional

from src.auth.domain.models import User
from src.shared.utils.errors import CropAnalysisError


async def _has_key(gemini, user: User) -> bool:
    try:
        await gemini.api_key_for(user.id)
        return True
    except CropAnalysisError:
        return False


async def owner_key_user(gemini, members: list[User]) -> Optional[User]:
    """The account's owner, when they loaded a key (the summaries are paid by the owner)."""
    for member in members:
        if member.role == "owner" and await _has_key(gemini, member):
            return member
    return None


async def any_key_user(gemini, members: list[User]) -> Optional[User]:
    """An owner's key first, else a tecnico's, else anyone's (the proactive check)."""
    for member in sorted(members, key=lambda m: {"owner": 0, "tecnico": 1}.get(m.role, 2)):
        if await _has_key(gemini, member):
            return member
    return None
