from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends

from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor

from .schemas import FieldIrrigationResult
from .service import EvapotranspirationService

router = APIRouter(prefix="/irrigation", tags=["Irrigation"])

IRRIGATION = Provide["application.irrigation_service"]


@router.get(
    "/fields/{field_id}/recommendation", response_model=FieldIrrigationResult, summary="Irrigation Recommendation"
)
@inject
async def field_irrigation_recommendation(
    field_id: UUID, actor: Actor = Depends(get_actor), irrigation: EvapotranspirationService = Depends(IRRIGATION)
):
    return await irrigation.compute(actor, field_id)
