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
from src.shared.utils.errors import NotFoundError

from .models import Conversation, ConversationMessage
from .schemas import ConversationCreate, ConversationRead, ConversationUpdate, MessageRead

SessionDeleter = Callable[[Actor, UUID], Awaitable[None]]


class ConversationService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory
        self._session_deleter: Optional[SessionDeleter] = None

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

    async def add_turn(
        self,
        actor: Actor,
        conversation_id: UUID,
        user_text: str,
        assistant_text: str,
        image_identifier: Optional[str],
        sources: list[dict],
        tool_calls: list[dict],
        attachments: Optional[list[dict]] = None,
    ) -> tuple[MessageRead, MessageRead]:
        now = utcnow()
        user_msg = ConversationMessage(
            conversation_id=conversation_id,
            role="user",
            content=user_text,
            image_identifier=image_identifier,
            created_at=now,
        )
        assistant_msg = ConversationMessage(
            conversation_id=conversation_id,
            role="assistant",
            content=assistant_text,
            sources=sources,
            tool_calls=tool_calls,
            attachments=attachments or [],
            created_at=utcnow(),
        )
        async with self.session_factory() as session:
            await self._owned(session, actor, conversation_id)
            session.add_all([user_msg, assistant_msg])
            await session.execute(
                update(Conversation).where(Conversation.id == conversation_id).values(updated_at=utcnow())
            )
            await session.commit()
            await session.refresh(user_msg)
            await session.refresh(assistant_msg)
        return MessageRead.model_validate(user_msg), MessageRead.model_validate(assistant_msg)

    async def messages(
        self, actor: Actor, conversation_id: UUID, limit: int = 50, before: Optional[datetime] = None
    ) -> list[MessageRead]:
        async with self.session_factory() as session:
            await self._owned(session, actor, conversation_id)
            stmt = select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id)
            if before:
                stmt = stmt.where(ConversationMessage.created_at < before)
            stmt = stmt.order_by(ConversationMessage.created_at.desc()).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
        return [MessageRead.model_validate(m) for m in reversed(rows)]
