"""
Agent long-term memory: facts the agent chooses to remember, shared per account.
Recall is hybrid: Spanish full-text (tsvector) + vector similarity (pgvector), fused with RRF.
Embeddings are best-effort: if the user's quota is exhausted the fact is still stored and
remains findable lexically.
"""
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import bindparam, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pgvector.sqlalchemy import Vector

from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import CropAnalysisError, NotFoundError, PermissionDeniedError

from .models import EMBEDDING_DIMENSIONS, AgentMemory

logger = logging.getLogger(__name__)

RRF_K = 60

_HYBRID_SQL = text(
    """
    WITH vec AS (
        SELECT id, row_number() OVER (ORDER BY embedding <=> :qvec) AS rnk
        FROM agent_memories
        WHERE account_id = :account_id AND superseded_at IS NULL
          AND embedding IS NOT NULL AND :use_vec
        ORDER BY embedding <=> :qvec
        LIMIT :k
    ),
    lex AS (
        SELECT m.id, row_number() OVER (ORDER BY ts_rank_cd(m.tsv, q) DESC) AS rnk
        FROM agent_memories m, websearch_to_tsquery('spanish', :qtext) q
        WHERE m.account_id = :account_id AND m.superseded_at IS NULL AND m.tsv @@ q
        ORDER BY ts_rank_cd(m.tsv, q) DESC
        LIMIT :k
    )
    SELECT m.id, m.content, m.tags, m.created_at, m.created_by,
           COALESCE(1.0 / (:rrf_k + vec.rnk), 0) + COALESCE(1.0 / (:rrf_k + lex.rnk), 0) AS score
    FROM agent_memories m
    LEFT JOIN vec ON vec.id = m.id
    LEFT JOIN lex ON lex.id = m.id
    WHERE vec.id IS NOT NULL OR lex.id IS NOT NULL
    ORDER BY score DESC
    LIMIT :limit
    """
).bindparams(bindparam("qvec", type_=Vector(EMBEDDING_DIMENSIONS)))


class MemoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    content: str
    tags: list[str] = []
    created_at: datetime
    created_by: Optional[UUID] = None
    score: Optional[float] = None


class MemoryService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], gemini_gateway):
        self.session_factory = session_factory
        self.gemini = gemini_gateway

    async def _embed(self, actor: Actor, content: str, task_type: str) -> Optional[list[float]]:
        try:
            return (await self.gemini.embed(actor.user_id, [content], task_type))[0]
        except CropAnalysisError as e:
            logger.warning(f"Embedding skipped ({e.error_code}); memory will be lexical-only.")
            return None

    async def remember(
        self,
        actor: Actor,
        content: str,
        tags: Optional[list[str]] = None,
        conversation_id: Optional[UUID] = None,
    ) -> MemoryRead:
        content = content.strip()
        embedding = await self._embed(actor, content, "RETRIEVAL_DOCUMENT")
        memory = AgentMemory(
            account_id=actor.account_id,
            created_by=actor.user_id,
            conversation_id=conversation_id,
            content=content,
            tags=[t.strip().lower()[:50] for t in (tags or []) if t.strip()],
            embedding=embedding,
        )
        async with self.session_factory() as session:
            session.add(memory)
            await session.commit()
            await session.refresh(memory)
        return MemoryRead.model_validate(memory)

    async def recall(self, actor: Actor, query: str, limit: int = 5) -> list[MemoryRead]:
        limit = min(max(limit, 1), 20)
        qvec = await self._embed(actor, query, "RETRIEVAL_QUERY")
        params = {
            "account_id": actor.account_id,
            "qtext": query,
            "qvec": qvec or [0.0] * EMBEDDING_DIMENSIONS,
            "use_vec": qvec is not None,
            "k": limit * 4,
            "rrf_k": RRF_K,
            "limit": limit,
        }
        async with self.session_factory() as session:
            rows = (await session.execute(_HYBRID_SQL, params)).mappings().all()
        return [MemoryRead(**dict(r)) for r in rows]

    async def list_recent(self, actor: Actor, limit: int = 50, offset: int = 0) -> list[MemoryRead]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(AgentMemory)
                    .where(AgentMemory.account_id == actor.account_id, AgentMemory.superseded_at.is_(None))
                    .order_by(AgentMemory.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).scalars().all()
        return [MemoryRead.model_validate(m) for m in rows]

    async def forget(self, actor: Actor, memory_id: UUID) -> None:
        """Memories are shared by the account: owner/tecnico can drop any, staff only the ones they created."""
        conditions = [
            AgentMemory.id == memory_id,
            AgentMemory.account_id == actor.account_id,
            AgentMemory.superseded_at.is_(None),
        ]
        async with self.session_factory() as session:
            memory = (await session.execute(select(AgentMemory).where(*conditions))).scalar_one_or_none()
            if memory is None:
                raise NotFoundError(f"Memory {memory_id} not found.")
            if not actor.is_manager and memory.created_by != actor.user_id:
                raise PermissionDeniedError("You can only delete facts you added.")
            await session.execute(update(AgentMemory).where(*conditions).values(superseded_at=utcnow()))
            await session.commit()
