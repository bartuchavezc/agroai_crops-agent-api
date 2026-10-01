"""
Destructive agent actions need the user's confirmation, enforced in code instead of only in the prompt.

A tool that deletes something never deletes on the call: it registers a pending action and answers with what
it would remove. `confirm_action` runs it later, and only when all of this holds:
  - the pending action was registered in an EARLIER turn of the same conversation, by the same user;
  - the message of the current turn — the user's own words, never model or tool output — is a short yes;
  - nothing untrusted (web search results) entered the current turn before the confirmation.
So text planted in a web page can at most make the agent *propose* a deletion; the user still sees it and has
to say yes in a message of their own.
"""
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from uuid import UUID

from src.shared.domain.actor import Actor

PENDING_TTL_SECONDS = 15 * 60
_MAX_CONFIRMATION_CHARS = 80

_YES = {
    "si", "sip", "dale", "ok", "okay", "oka", "okey", "listo", "confirmo", "confirmado", "confirmar", "adelante",
    "hacelo", "borralo", "borrala", "borralos", "borralas", "eliminalo", "eliminala", "eliminalos", "eliminalas",
    "olvidalo", "olvidala", "correcto", "exacto", "yes", "claro", "obvio", "bueno", "va",
}
_NO = {"no", "nop", "nah", "cancela", "cancelar", "cancelalo", "espera", "pera", "ninguno", "nunca", "tampoco"}


def _words(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return re.findall(r"[a-z]+", plain)


def is_affirmative(message: str) -> bool:
    """A short, unambiguous yes ("sí", "dale, borralo", "ok confirmo"). Anything with a no, or long enough to
    be about something else, is not a confirmation."""
    if len(message.strip()) > _MAX_CONFIRMATION_CHARS:
        return False
    words = _words(message)
    return bool(words) and not any(w in _NO for w in words) and any(w in _YES for w in words)


@dataclass
class PendingAction:
    id: str
    conversation_id: UUID
    user_id: UUID
    turn_id: str
    summary: str
    run: Callable[[], Awaitable[dict]]
    created_at: float = field(default_factory=time.monotonic)


class PendingActionStore:
    """In-memory, per process. A restart drops pending actions: the user just asks again."""

    def __init__(self) -> None:
        self._actions: dict[str, PendingAction] = {}

    def _prune(self) -> None:
        now = time.monotonic()
        for key in [k for k, a in self._actions.items() if now - a.created_at > PENDING_TTL_SECONDS]:
            del self._actions[key]

    def add(
        self, *, conversation_id: UUID, actor: Actor, turn_id: str, summary: str, run: Callable[[], Awaitable[dict]]
    ) -> PendingAction:
        self._prune()
        # one pending deletion per conversation: a new proposal replaces the previous one
        for key in [k for k, a in self._actions.items() if a.conversation_id == conversation_id]:
            del self._actions[key]
        action = PendingAction(uuid.uuid4().hex[:12], conversation_id, actor.user_id, turn_id, summary, run)
        self._actions[action.id] = action
        return action

    def get(self, action_id: str, conversation_id: UUID, user_id: UUID) -> PendingAction | None:
        self._prune()
        action = self._actions.get(action_id)
        if action is None or action.conversation_id != conversation_id or action.user_id != user_id:
            return None
        return action

    def discard(self, action_id: str) -> None:
        self._actions.pop(action_id, None)


def propose(ctx: Any, store: PendingActionStore, summary: str, run: Callable[[], Awaitable[dict]]) -> dict:
    """What a destructive tool returns instead of acting."""
    action = store.add(
        conversation_id=ctx.conversation_id, actor=ctx.actor, turn_id=ctx.turn_id, summary=summary, run=run
    )
    return {
        "needs_confirmation": True,
        "confirmation_id": action.id,
        "would_do": summary,
        "next_step": "Nothing was deleted yet. Tell the user exactly what would be removed and ask them to confirm. "
        "Only after they answer yes in their next message, call confirm_action with this confirmation_id.",
    }


def confirm_action_tool(ctx: Any, store: PendingActionStore):
    async def confirm_action(confirmation_id: str) -> dict:
        """Carry out a deletion proposed in an earlier turn (delete_field, delete_crop_cycle, forget_fact), once
        the user has said yes to it in their own latest message. Never call it in the same turn as the proposal."""
        action = store.get(confirmation_id, ctx.conversation_id, ctx.actor.user_id)
        if action is None:
            return {"error": "No pending action with that id (it may have expired). Propose the deletion again."}
        if action.turn_id == ctx.turn_id:
            return {"error": "The user has not confirmed yet. Ask them and wait for their answer in a new message."}
        if ctx.untrusted_content_seen:
            return {"error": "Web content was read in this turn; ask the user to confirm again in a new message."}
        if not is_affirmative(ctx.user_message):
            return {
                "error": "The user's latest message is not a clear yes to this deletion. Ask again for an explicit "
                "confirmation (or drop it if they declined).",
            }
        store.discard(action.id)
        return await action.run()

    return confirm_action
