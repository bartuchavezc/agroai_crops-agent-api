from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends

from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor

from .schemas import ZoneSatelliteStatus
from .service import ZoneSatelliteService

router = APIRouter(prefix="/satellite", tags=["Satellite"])

SATELLITE = Provide["application.satellite_service"]


@router.get("/fields/{field_id}/status", response_model=ZoneSatelliteStatus, summary="Zone Satellite Status")
@inject
async def field_satellite_status(
    field_id: UUID, actor: Actor = Depends(get_actor), satellite: ZoneSatelliteService = Depends(SATELLITE)
):
    return await satellite.check_field(actor, field_id)


@router.post("/fields/{field_id}/render-map", summary="Render Zone Satellite Map")
@inject
async def render_field_map(
    field_id: UUID, actor: Actor = Depends(get_actor), satellite: ZoneSatelliteService = Depends(SATELLITE)
):
    image_identifier = await satellite.render_map_image(actor, field_id)
    if not image_identifier:
        return {"image_identifier": None, "message": "Satellite imagery unavailable right now."}
    return {"image_identifier": image_identifier}
