"""
Conversation management: each user owns many private conversations.
"""
from datetime import datetime
from typing import Awaitable, Callable, Optional
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import InvalidInputError, NotFoundError

from .models import Conversation, ConversationMessage
from .schemas import ConversationCreate, ConversationRead, ConversationUpdate, MessageRead

SessionDeleter = Callable[[Actor, UUID], Awaitable[None]]


class ConversationService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], farm_service=None):
        self.session_factory = session_factory
        self.farm = farm_service
        self._session_deleter: Optional[SessionDeleter] = None

    async def _check_field(self, actor: Actor, field_id: Optional[UUID]) -> None:
        """A field_id from the client must be one of the caller's own fields (NotFound otherwise)."""
        if field_id and self.farm is not None:
            await self.farm.get_field(actor, field_id)

    def set_session_deleter(self, deleter: SessionDeleter) -> None:
        """Hook used to drop the agent framework's session when a conversation is deleted."""
        self._session_deleter = deleter

    async def _owned(self, session: AsyncSession, actor: Actor, conversation_id: UUID) -> Conversation:
        conv = (
            await session.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id, Conversation.user_id == actor.user_id
                )
            )
        ).scalar_one_or_none()
        if conv is None:
            raise NotFoundError(f"Conversation {conversation_id} not found.")
        return conv

    async def create(self, actor: Actor, data: ConversationCreate) -> ConversationRead:
        await self._check_field(actor, data.field_id)
        conv = Conversation(
            account_id=actor.account_id, user_id=actor.user_id, title=data.title, field_id=data.field_id
        )
        async with self.session_factory() as session:
            session.add(conv)
            await session.commit()
            await session.refresh(conv)
        return ConversationRead.model_validate(conv)

    async def get(self, actor: Actor, conversation_id: UUID) -> ConversationRead:
        async with self.session_factory() as session:
            return ConversationRead.model_validate(await self._owned(session, actor, conversation_id))

    async def list_for_user(
        self, actor: Actor, include_archived: bool = False, limit: int = 50, offset: int = 0
    ) -> list[ConversationRead]:
        stmt = select(Conversation).where(Conversation.user_id == actor.user_id)
        if not include_archived:
            stmt = stmt.where(Conversation.archived_at.is_(None))
        stmt = stmt.order_by(Conversation.updated_at.desc()).offset(offset).limit(limit)
        async with self.session_factory() as session:
            return [ConversationRead.model_validate(c) for c in (await session.execute(stmt)).scalars().all()]

    async def update(self, actor: Actor, conversation_id: UUID, data: ConversationUpdate) -> ConversationRead:
        await self._check_field(actor, data.field_id)
        async with self.session_factory() as session:
            conv = await self._owned(session, actor, conversation_id)
            values = data.model_dump(exclude_unset=True)
            if "title" in values:
                conv.title = values["title"]
            if "field_id" in values:
                conv.field_id = values["field_id"]
            if "archived" in values:
                conv.archived_at = utcnow() if values["archived"] else None
            conv.updated_at = utcnow()
            await session.commit()
            await session.refresh(conv)
            return ConversationRead.model_validate(conv)

    async def set_title_if_empty(self, conversation_id: UUID, title: str) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id, Conversation.title.is_(None))
                .values(title=title[:255])
            )
            await session.commit()

    async def delete(self, actor: Actor, conversation_id: UUID) -> None:
        async with self.session_factory() as session:
            await self._owned(session, actor, conversation_id)
            await session.execute(delete(Conversation).where(Conversation.id == conversation_id))
            await session.commit()
        if self._session_deleter:
            await self._session_deleter(actor, conversation_id)

    async def start_turn(
        self,
        actor: Actor,
        conversation_id: UUID,
        user_text: str,
        image_identifier: Optional[str],
        retry_message_id: Optional[UUID] = None,
    ) -> tuple[UUID, UUID]:
        """Save the user's message and a `pending` assistant placeholder before the agent runs, so a
        turn that fails or outlives the client is still in the transcript. With retry_message_id the
        user message of a failed turn is reused (its failed answer is dropped) instead of duplicated.
        Returns (user_message_id, assistant_message_id)."""
        async with self.session_factory() as session:
            await self._owned(session, actor, conversation_id)
            if retry_message_id:
                user_msg = await self._failed_user_message(session, conversation_id, retry_message_id)
                await session.execute(
                    delete(ConversationMessage).where(
                        ConversationMessage.conversation_id == conversation_id,
                        ConversationMessage.role == "assistant",
                        ConversationMessage.created_at > user_msg.created_at,
                    )
                )
            else:
                user_msg = ConversationMessage(
                    conversation_id=conversation_id,
                    role="user",
                    content=user_text,
                    image_identifier=image_identifier,
                    created_at=utcnow(),
                )
                session.add(user_msg)
            assistant_msg = ConversationMessage(
                conversation_id=conversation_id, role="assistant", content="", status="pending", created_at=utcnow()
            )
            session.add(assistant_msg)
            await session.execute(
                update(Conversation).where(Conversation.id == conversation_id).values(updated_at=utcnow())
            )
            await session.commit()
            return user_msg.id, assistant_msg.id

    async def _failed_user_message(
        self, session: AsyncSession, conversation_id: UUID, message_id: UUID
    ) -> ConversationMessage:
        """The last user message of the conversation, only if its answer failed (or never came)."""
        last_user = (
            await session.execute(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conversation_id, ConversationMessage.role == "user")
                .order_by(ConversationMessage.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if last_user is None or last_user.id != message_id:
            raise NotFoundError("Only the last message of the conversation can be retried.")
        answered = (
            await session.execute(
                select(ConversationMessage.id).where(
                    ConversationMessage.conversation_id == conversation_id,
                    ConversationMessage.role == "assistant",
                    ConversationMessage.status != "error",
                    ConversationMessage.created_at > last_user.created_at,
                )
            )
        ).first()
        if answered is not None:
            raise InvalidInputError("That message already has an answer.")
        return last_user

    async def retry_text(self, actor: Actor, conversation_id: UUID, message_id: UUID) -> tuple[str, Optional[str]]:
        """(text, image_identifier) of a failed user message that is about to be retried."""
        async with self.session_factory() as session:
            await self._owned(session, actor, conversation_id)
            msg = await self._failed_user_message(session, conversation_id, message_id)
            return msg.content, msg.image_identifier

    async def finish_turn(
        self,
        assistant_message_id: UUID,
        assistant_text: str,
        sources: list[dict],
        tool_calls: list[dict],
        attachments: Optional[list[dict]] = None,
        error_code: Optional[str] = None,
    ) -> None:
        """Complete the turn's placeholder; with error_code it's kept as a failed answer (with
        whatever text was generated before the failure)."""
        async with self.session_factory() as session:
            await session.execute(
                update(ConversationMessage)
                .where(ConversationMessage.id == assistant_message_id)
                .values(
                    content=assistant_text,
                    sources=sources,
                    tool_calls=tool_calls,
                    attachments=attachments or [],
                    status="error" if error_code else "complete",
                    error_code=error_code,
                )
            )
            await session.commit()

    async def messages(
        self,
        actor: Actor,
        conversation_id: UUID,
        limit: int = 50,
        before: Optional[datetime] = None,
        running: bool = False,
    ) -> list[MessageRead]:
        """`running`: whether a turn of this conversation is being generated right now; otherwise a
        `pending` answer is reported as interrupted."""
        async with self.session_factory() as session:
            await self._owned(session, actor, conversation_id)
            stmt = select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id)
            if before:
                stmt = stmt.where(ConversationMessage.created_at < before)
            stmt = stmt.order_by(ConversationMessage.created_at.desc()).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
        result = []
        for m in reversed(rows):
            read = MessageRead.model_validate(m)
            if read.status == "pending" and not running:
                # The process running that turn went away (restart/deploy) without finishing it.
                read = read.model_copy(update={"status": "error", "error_code": "TURN_INTERRUPTED"})
            result.append(read)
        return result
