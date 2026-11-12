"""Read-only view of the agent's tracking plans, while the person-facing design is worked out."""
from typing import List, Optional
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException

from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor

from .schemas import TrackingPlanRead
from .service import TrackingPlanService

router = APIRouter(prefix="/farm-management", tags=["Tracking plans"])
PLANS = Provide["application.tracking_plan_service"]


@router.get("/lots/{lot_id}/tracking-plan", response_model=TrackingPlanRead, summary="The agent's plan for a lot")
@inject
async def get_tracking_plan(lot_id: UUID, actor: Actor = Depends(get_actor),
                            plans: TrackingPlanService = Depends(PLANS)):
    """Stages as estimated windows, key moments, the checks the agent will make or ask for (by section), and why it
    changed each time. 404 while the agent hasn't planned this lot."""
    plan = await plans.get(actor, lot_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="This lot has no tracking plan yet.")
    return plan


@router.get("/tracking-plans", response_model=List[TrackingPlanRead], summary="The account's tracking plans")
@inject
async def list_tracking_plans(lot_ids: Optional[List[UUID]] = None, actor: Actor = Depends(get_actor),
                              plans: TrackingPlanService = Depends(PLANS)):
    return await plans.list_plans(actor, lot_ids)
