import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, Column, Computed, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID

from src.shared.database import Base
from src.shared.domain.base import utcnow

EMBEDDING_DIMENSIONS = 768


class AgentMemory(Base):
    """A fact the agent decided to remember. Shared by every user of the account."""
    __tablename__ = "agent_memories"
    __table_args__ = (
        Index("ix_agent_memories_account_created", "account_id", "created_at"),
        Index("ix_agent_memories_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_agent_memories_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"))
    content = Column(Text, nullable=False)
    tags = Column(ARRAY(String(50)), nullable=False, default=list)
    embedding = Column(Vector(EMBEDDING_DIMENSIONS))
    tsv = Column(TSVECTOR, Computed("to_tsvector('spanish', content)", persisted=True))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    superseded_at = Column(DateTime(timezone=True))
