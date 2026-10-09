from datetime import date, datetime
from typing import List, Literal, Optional, Union
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query, Response, status

from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor
from src.shared.utils.routing import route_with_and_without_slash as _both

from .schemas import (
    CyclePlanProposal,
    PlanCreate,
    PlanDetail,
    PlanRead,
    PlanStatus,
    PlanUpdate,
    ReminderCreate,
    ReminderRead,
    ReminderStatus,
    ReminderUpdate,
    SowingCreate,
    SowingRead,
    SowingUpdate,
    SowRequest,
    StaggeredSowingCreate,
    StageCreate,
    StageRead,
    StageUpdate,
)
from .calendar import CalendarResponse
from .progress import CycleProgress, CycleProgressService
from .service import PlanningService

router = APIRouter(prefix="/planning", tags=["Planning"])

PLANNING = Provide["application.planning_service"]
PROGRESS = Provide["application.cycle_progress_service"]

# assigned_to filter: a member id ("mine": theirs + unassigned), or "none" for unassigned only.
IdFilter = Optional[Union[UUID, Literal["none"]]]


# ---------- calendar ----------

@router.get("/calendar", response_model=CalendarResponse, summary="Reminders, sowings and stages in a date range")
@inject
async def calendar(
    since: date,
    until: date,
    field_id: Optional[UUID] = None,
    actor: Actor = Depends(get_actor),
    planning: PlanningService = Depends(PLANNING),
):
    """Dates are the user's local days (inclusive). Recurring reminders come already expanded into their
    occurrences (from the current one on: earlier ones were never recorded); stages come as items on their start
    day and as `ranges`. At most 400 days at a time."""
    return await planning.calendar(actor, since, until, field_id)


# ---------- reminders ----------

@_both(router.get, "/reminders", response_model=List[ReminderRead], summary="List reminders (agenda)")
@inject
async def list_reminders(
    status_filter: Optional[ReminderStatus] = Query(None, alias="status"),
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    field_id: Optional[UUID] = None,
    crop_cycle_id: Optional[UUID] = None,
    plan_id: Optional[UUID] = None,
    assigned_to: IdFilter = None,
    zone_id: Optional[UUID] = None,
    before: Optional[datetime] = Query(None, description="History: reminders due before this instant, newest first"),
    limit: int = Query(200, ge=1, le=500),
    actor: Actor = Depends(get_actor),
    planning: PlanningService = Depends(PLANNING),
):
    """Ordered by due_at (the current occurrence of recurring ones); newest first when `before` is given."""
    return await planning.list_reminders(
        actor, status_filter, since, until, field_id, crop_cycle_id, plan_id, assigned_to, limit,
        zone_id=zone_id, before=before,
    )


@_both(
    router.post, "/reminders", response_model=ReminderRead, status_code=status.HTTP_201_CREATED,
    summary="Create a reminder",
)
@inject
async def create_reminder(
    body: ReminderCreate, actor: Actor = Depends(get_actor), planning: PlanningService = Depends(PLANNING)
):
    return await planning.create_reminder(actor, body)


@router.put("/reminders/{reminder_id}", response_model=ReminderRead, summary="Update / postpone a reminder")
@inject
async def update_reminder(
    reminder_id: UUID, body: ReminderUpdate, actor: Actor = Depends(get_actor),
    planning: PlanningService = Depends(PLANNING),
):
    return await planning.update_reminder(actor, reminder_id, body)


@router.post("/reminders/{reminder_id}/complete", response_model=ReminderRead, summary="Mark a reminder done")
@inject
async def complete_reminder(
    reminder_id: UUID, actor: Actor = Depends(get_actor), planning: PlanningService = Depends(PLANNING)
):
    """A recurring reminder moves on to its next occurrence."""
    return await planning.complete_reminder(actor, reminder_id)


@router.delete("/reminders/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a reminder")
@inject
async def delete_reminder(
    reminder_id: UUID, actor: Actor = Depends(get_actor), planning: PlanningService = Depends(PLANNING)
):
    await planning.delete_reminder(actor, reminder_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- plans ----------

@_both(router.get, "/plans", response_model=List[PlanRead], summary="List plans")
@inject
async def list_plans(
    field_id: Optional[UUID] = None,
    status_filter: Optional[PlanStatus] = Query(None, alias="status"),
    actor: Actor = Depends(get_actor),
    planning: PlanningService = Depends(PLANNING),
):
    return await planning.list_plans(actor, field_id, status_filter)


@_both(
    router.post, "/plans", response_model=PlanDetail, status_code=status.HTTP_201_CREATED,
    summary="Create a plan (owner/tecnico)",
)
@inject
async def create_plan(
    body: PlanCreate, actor: Actor = Depends(get_actor), planning: PlanningService = Depends(PLANNING)
):
    """With its stages and sowings at once; every sowing gets a reminder on its date."""
    return await planning.create_plan(actor, body)


@router.get("/plans/{plan_id}", response_model=PlanDetail, summary="Plan with stages, sowings and reminders")
@inject
async def get_plan(plan_id: UUID, actor: Actor = Depends(get_actor), planning: PlanningService = Depends(PLANNING)):
    return await planning.get_plan(actor, plan_id)


@router.put("/plans/{plan_id}", response_model=PlanRead, summary="Update a plan (owner/tecnico)")
@inject
async def update_plan(
    plan_id: UUID, body: PlanUpdate, actor: Actor = Depends(get_actor), planning: PlanningService = Depends(PLANNING)
):
    """Archiving cancels its pending reminders."""
    return await planning.update_plan(actor, plan_id, body)


@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a plan (owner/tecnico)")
@inject
async def delete_plan(plan_id: UUID, actor: Actor = Depends(get_actor), planning: PlanningService = Depends(PLANNING)):
    await planning.delete_plan(actor, plan_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/plans/{plan_id}/stages", response_model=StageRead, status_code=status.HTTP_201_CREATED, summary="Add a stage"
)
@inject
async def add_stage(
    plan_id: UUID, body: StageCreate, actor: Actor = Depends(get_actor), planning: PlanningService = Depends(PLANNING)
):
    return await planning.add_stage(actor, plan_id, body)


@router.put("/stages/{stage_id}", response_model=StageRead, summary="Update a stage")
@inject
async def update_stage(
    stage_id: UUID, body: StageUpdate, actor: Actor = Depends(get_actor), planning: PlanningService = Depends(PLANNING)
):
    return await planning.update_stage(actor, stage_id, body)


@router.delete("/stages/{stage_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a stage")
@inject
async def delete_stage(
    stage_id: UUID, actor: Actor = Depends(get_actor), planning: PlanningService = Depends(PLANNING)
):
    await planning.delete_stage(actor, stage_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/plans/{plan_id}/sowings", response_model=SowingRead, status_code=status.HTTP_201_CREATED,
    summary="Add a planned sowing",
)
@inject
async def add_sowing(
    plan_id: UUID, body: SowingCreate, actor: Actor = Depends(get_actor), planning: PlanningService = Depends(PLANNING)
):
    return await planning.add_sowing(actor, plan_id, body)


@router.post(
    "/plans/{plan_id}/sowings/staggered", response_model=List[SowingRead], status_code=status.HTTP_201_CREATED,
    summary="Split a sowing (and its seed) over time",
)
@inject
async def add_staggered_sowings(
    plan_id: UUID, body: StaggeredSowingCreate, actor: Actor = Depends(get_actor),
    planning: PlanningService = Depends(PLANNING),
):
    return await planning.add_staggered_sowings(actor, plan_id, body)


@router.put("/sowings/{sowing_id}", response_model=SowingRead, summary="Update a planned sowing")
@inject
async def update_sowing(
    sowing_id: UUID, body: SowingUpdate, actor: Actor = Depends(get_actor),
    planning: PlanningService = Depends(PLANNING),
):
    return await planning.update_sowing(actor, sowing_id, body)


@router.post("/sowings/{sowing_id}/sow", response_model=SowingRead, summary="Mark a planned sowing as done")
@inject
async def sow(
    sowing_id: UUID, body: SowRequest, actor: Actor = Depends(get_actor), planning: PlanningService = Depends(PLANNING)
):
    """Starts its crop cycle (with stage reminders) and discounts the seed lot, unless told not to."""
    return await planning.sow(actor, sowing_id, body)


@router.delete("/sowings/{sowing_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a planned sowing")
@inject
async def delete_sowing(
    sowing_id: UUID, actor: Actor = Depends(get_actor), planning: PlanningService = Depends(PLANNING)
):
    await planning.delete_sowing(actor, sowing_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- crop cycle stage plan ----------

@router.get(
    "/crop-cycles/{cycle_id}/stage-plan", response_model=CyclePlanProposal,
    summary="Preview the stage plan + reminders of a crop cycle",
)
@inject
async def preview_cycle_plan(
    cycle_id: UUID, actor: Actor = Depends(get_actor), planning: PlanningService = Depends(PLANNING)
):
    return await planning.propose_cycle_plan(actor, cycle_id)


@router.get(
    "/crop-cycles/{cycle_id}/progress", response_model=CycleProgress,
    summary="Expected vs. real progress of a crop cycle",
)
@inject
async def cycle_progress(
    cycle_id: UUID, actor: Actor = Depends(get_actor), progress: CycleProgressService = Depends(PROGRESS)
):
    """expected_pct, current stage and next stage from the dates and the stage plan; ok/late/affected from the latest
    completed analysis that covered the cycle (unknown when there is none)."""
    return await progress.progress(actor, cycle_id)


@router.post(
    "/crop-cycles/{cycle_id}/stage-plan", response_model=CyclePlanProposal,
    summary="Create (or regenerate) the stage plan + reminders of a crop cycle (owner/tecnico)",
)
@inject
async def apply_cycle_plan(
    cycle_id: UUID, actor: Actor = Depends(get_actor), planning: PlanningService = Depends(PLANNING)
):
    """Germinación, traspaso, etapas clave, posible cosecha and estimated harvest, from the crop's template.
    Regenerating replaces what was generated before; reminders already done are kept."""
    return await planning.apply_cycle_plan(actor, cycle_id)
