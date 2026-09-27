"""
Review what the agent remembers for the account, search it, and delete wrong facts.
"""
from typing import List
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query, Response, status

from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor

from .service import MemoryRead, MemoryService

router = APIRouter(prefix="/agent/memories", tags=["Agent Memory"])

MEMORY = Provide["agent.memory_service"]


@router.get("", response_model=List[MemoryRead], summary="List remembered facts")
@inject
async def list_memories(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    actor: Actor = Depends(get_actor),
    memory: MemoryService = Depends(MEMORY),
):
    return await memory.list_recent(actor, limit=limit, offset=offset)


@router.get("/search", response_model=List[MemoryRead], summary="Hybrid search over memories")
@inject
async def search_memories(
    q: str = Query(..., min_length=2),
    limit: int = Query(5, ge=1, le=20),
    actor: Actor = Depends(get_actor),
    memory: MemoryService = Depends(MEMORY),
):
    return await memory.recall(actor, q, limit)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Forget a fact")
@inject
async def forget_memory(memory_id: UUID, actor: Actor = Depends(get_actor), memory: MemoryService = Depends(MEMORY)):
    await memory.forget(actor, memory_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
