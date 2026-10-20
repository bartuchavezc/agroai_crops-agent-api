"""Tasks HTTP API: work with someone in charge and a state, on a field, zone, lot and/or plan."""
from typing import List, Optional
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query, Response, status

from src.application.management.repository import IdFilter
from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor
from src.shared.utils.routing import route_with_and_without_slash as _both

from .schemas import TaskCreate, TaskRead, TaskStatus, TaskUpdate
from .service import TaskService

router = APIRouter(prefix="/tasks", tags=["Tasks"])
TASKS = Provide["application.task_service"]


@_both(router.get, "", response_model=List[TaskRead], summary="List tasks")
@inject
async def list_tasks(
    field_id: IdFilter = Query(None, description="A field id, or 'none' for tasks with no field"),
    zone_id: Optional[UUID] = Query(None, description="The zone's tasks and those of the lots growing in it"),
    lot_id: Optional[UUID] = None,
    plan_id: Optional[UUID] = None,
    status_filter: Optional[TaskStatus] = Query(None, alias="status"),
    open_only: bool = Query(False, description="pendiente, en curso o bloqueada"),
    assigned_to: IdFilter = None,
    actor: Actor = Depends(get_actor),
    tasks: TaskService = Depends(TASKS),
):
    return await tasks.list_tasks(
        actor, field_id=field_id, zone_id=zone_id, lot_id=lot_id, plan_id=plan_id, status=status_filter,
        open_only=open_only, assigned_to=assigned_to,
    )


@_both(router.post, "", response_model=TaskRead, status_code=status.HTTP_201_CREATED, summary="Add a task")
@inject
async def create_task(body: TaskCreate, actor: Actor = Depends(get_actor), tasks: TaskService = Depends(TASKS)):
    return await tasks.create_task(actor, body)


@router.get("/{task_id}", response_model=TaskRead, summary="Get a task")
@inject
async def get_task(task_id: UUID, actor: Actor = Depends(get_actor), tasks: TaskService = Depends(TASKS)):
    return await tasks.get_task(actor, task_id)


@router.put("/{task_id}", response_model=TaskRead, summary="Update a task")
@inject
async def update_task(
    task_id: UUID, body: TaskUpdate, actor: Actor = Depends(get_actor), tasks: TaskService = Depends(TASKS)
):
    """Setting status `hecha` with a `result_event_type` logs it in the bitácora (and moves the lot forward for a
    sowing or a transplant)."""
    return await tasks.update_task(actor, task_id, body)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a task (owner/tecnico)")
@inject
async def delete_task(task_id: UUID, actor: Actor = Depends(get_actor), tasks: TaskService = Depends(TASKS)):
    await tasks.delete_task(actor, task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
