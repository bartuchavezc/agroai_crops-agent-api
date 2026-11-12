"""The agent's background tasks as the web sees them: the to-do list advancing, the result, the trace."""
from typing import List, Optional
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor

from .schemas import AgentTaskRead
from .service import LongTaskService

router = APIRouter(prefix="/agent-tasks", tags=["Agent tasks"])
TASKS = Provide["agent.long_task_service"]


@router.get("", response_model=List[AgentTaskRead], summary="The agent's background tasks")
@inject
async def list_tasks(conversation_id: Optional[UUID] = None, open_only: bool = False,
                     limit: int = Query(20, ge=1, le=100), actor: Actor = Depends(get_actor),
                     tasks: LongTaskService = Depends(TASKS)):
    return await tasks.list_tasks(actor, conversation_id, open_only, limit)


@router.get("/{task_id}", response_model=AgentTaskRead, summary="One task: to-do list, status, result, trace")
@inject
async def get_task(task_id: UUID, actor: Actor = Depends(get_actor), tasks: LongTaskService = Depends(TASKS)):
    return await tasks.get(actor, task_id)


@router.post("/{task_id}/cancel", response_model=AgentTaskRead, summary="Stop a task")
@inject
async def cancel_task(task_id: UUID, actor: Actor = Depends(get_actor), tasks: LongTaskService = Depends(TASKS)):
    return await tasks.cancel(actor, task_id)
