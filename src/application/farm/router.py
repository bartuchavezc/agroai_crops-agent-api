"""
Farm management HTTP API. Paths accept both with and without trailing slash
(the web dashboard uses trailing slashes, the mobile app does not).
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query, Response, status

from src.application.satellite.service import ZoneSatelliteService
from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor
from src.shared.utils.routing import route_with_and_without_slash as _both

from .schemas import (
    CropCycleCreate,
    CropCycleRead,
    CropCycleStatus,
    CropCycleUpdate,
    CropMasterCreate,
    CropMasterRead,
    EventType,
    FieldCreate,
    FieldEventCreate,
    FieldEventRead,
    FieldEventUpdate,
    FieldOverview,
    FieldRead,
    FieldUpdate,
    FieldZoneCreate,
    FieldZoneRead,
    FieldZoneUpdate,
    SunExposureRead,
    SunMapRead,
)
from .service import FarmService

router = APIRouter(prefix="/farm-management", tags=["Farm Management"])

FARM = Provide["application.farm_service"]
SATELLITE = Provide["application.satellite_service"]


# ---------- overview ----------

@router.get("/overview", response_model=List[FieldOverview], summary="Fields with active crop cycles")
@inject
async def overview(actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)):
    return await farm.overview(actor)


# ---------- fields ----------

@_both(router.get, "/fields", response_model=List[FieldRead], summary="List Fields")
@inject
async def list_fields(actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)):
    return await farm.list_fields(actor)


@_both(router.post, "/fields", response_model=FieldRead, status_code=status.HTTP_201_CREATED, summary="Create Field")
@inject
async def create_field(
    body: FieldCreate,
    actor: Actor = Depends(get_actor),
    farm: FarmService = Depends(FARM),
    satellite: ZoneSatelliteService = Depends(SATELLITE),
):
    created = await farm.create_field(actor, body)
    if created.latitude is not None:
        try:
            await satellite.check_field(actor, created.id)
        except Exception:
            pass  # best-effort context; the field is still successfully created without it
    return created


@router.get("/fields/{field_id}", response_model=FieldRead, summary="Get Field")
@inject
async def get_field(field_id: UUID, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)):
    return await farm.get_field(actor, field_id)


@router.put("/fields/{field_id}", response_model=FieldRead, summary="Update Field")
@inject
async def update_field(
    field_id: UUID, body: FieldUpdate, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)
):
    return await farm.update_field(actor, field_id, body)


@router.delete("/fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Field")
@inject
async def delete_field(field_id: UUID, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)):
    await farm.delete_field(actor, field_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- zones (cajón / cantero / invernadero / hidroponía) ----------

@router.get("/fields/{field_id}/zones", response_model=List[FieldZoneRead], summary="List a field's zones")
@inject
async def list_zones(field_id: UUID, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)):
    return await farm.list_zones(actor, field_id)


@router.post(
    "/fields/{field_id}/zones", response_model=FieldZoneRead, status_code=status.HTTP_201_CREATED,
    summary="Create a zone (owner/tecnico)",
)
@inject
async def create_zone(
    field_id: UUID, body: FieldZoneCreate, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)
):
    """Without `number` the zone gets the next free number for its type in that field."""
    return await farm.create_zone(actor, field_id, body)


@router.put("/zones/{zone_id}", response_model=FieldZoneRead, summary="Update a zone (owner/tecnico)")
@inject
async def update_zone(
    zone_id: UUID, body: FieldZoneUpdate, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)
):
    return await farm.update_zone(actor, zone_id, body)


@router.delete("/zones/{zone_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a zone (owner/tecnico)")
@inject
async def delete_zone(zone_id: UUID, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)):
    """Its crop cycles stay in the field, without a zone."""
    await farm.delete_zone(actor, zone_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/fields/{field_id}/sun-exposure", response_model=SunExposureRead, summary="Field Sun Exposure")
@inject
async def field_sun_exposure(field_id: UUID, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)):
    return await farm.sun_exposure(actor, field_id)


@router.get("/fields/{field_id}/sun-map", response_model=SunMapRead, summary="Field Sun/Shade Map")
@inject
async def field_sun_map(
    field_id: UUID,
    season: str = Query("verano", description="verano | invierno | equinoccio"),
    shadows: bool = Query(False, description="also return the shadow polygons every 30 minutes"),
    actor: Actor = Depends(get_actor),
    farm: FarmService = Depends(FARM),
):
    return await farm.sun_map(actor, field_id, season, include_shadows=shadows)


@router.get("/harvest-totals", summary="Harvest Totals")
@inject
async def harvest_totals(
    field_id: Optional[UUID] = None,
    crop_master_id: Optional[UUID] = None,
    year: Optional[int] = None,
    actor: Actor = Depends(get_actor),
    farm: FarmService = Depends(FARM),
):
    return await farm.harvest_totals(actor, field_id=field_id, crop_master_id=crop_master_id, year=year)


# ---------- crop masters ----------

@_both(router.get, "/crop-masters", response_model=List[CropMasterRead], summary="List Crop Catalog")
@inject
async def list_crop_masters(
    q: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    actor: Actor = Depends(get_actor),
    farm: FarmService = Depends(FARM),
):
    return await farm.list_crop_masters(actor, query=q, skip=skip, limit=limit)


@_both(
    router.post, "/crop-masters", response_model=CropMasterRead, status_code=status.HTTP_201_CREATED,
    summary="Add Crop To Account Catalog",
)
@inject
async def create_crop_master(
    body: CropMasterCreate, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)
):
    return await farm.create_crop_master(actor, body)


@router.get("/crop-masters/{crop_master_id}", response_model=CropMasterRead, summary="Get Crop")
@inject
async def get_crop_master(
    crop_master_id: UUID, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)
):
    return await farm.get_crop_master(actor, crop_master_id)


@router.delete("/crop-masters/{crop_master_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Crop")
@inject
async def delete_crop_master(
    crop_master_id: UUID, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)
):
    await farm.delete_crop_master(actor, crop_master_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- crop cycles ----------

@_both(router.get, "/crop-cycles", response_model=List[CropCycleRead], summary="List Crop Cycles")
@inject
async def list_crop_cycles(
    field_id: Optional[UUID] = None,
    status_filter: Optional[CropCycleStatus] = Query(None, alias="status"),
    zone_id: Optional[UUID] = None,
    actor: Actor = Depends(get_actor),
    farm: FarmService = Depends(FARM),
):
    return await farm.list_crop_cycles(actor, field_id=field_id, status=status_filter, zone_id=zone_id)


@_both(
    router.post, "/crop-cycles", response_model=CropCycleRead, status_code=status.HTTP_201_CREATED,
    summary="Create Crop Cycle",
)
@inject
async def create_crop_cycle(
    body: CropCycleCreate, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)
):
    return await farm.create_crop_cycle(actor, body)


@router.get("/crop-cycles/{cycle_id}", response_model=CropCycleRead, summary="Get Crop Cycle")
@inject
async def get_crop_cycle(cycle_id: UUID, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)):
    return await farm.get_crop_cycle(actor, cycle_id)


@router.put("/crop-cycles/{cycle_id}", response_model=CropCycleRead, summary="Update Crop Cycle")
@inject
async def update_crop_cycle(
    cycle_id: UUID, body: CropCycleUpdate, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)
):
    return await farm.update_crop_cycle(actor, cycle_id, body)


@router.delete("/crop-cycles/{cycle_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Crop Cycle")
@inject
async def delete_crop_cycle(cycle_id: UUID, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)):
    await farm.delete_crop_cycle(actor, cycle_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- events ----------

@_both(router.get, "/events", response_model=List[FieldEventRead], summary="List Field Events")
@inject
async def list_events(
    field_id: Optional[UUID] = None,
    crop_cycle_id: Optional[UUID] = None,
    type: Optional[EventType] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = Query(50, ge=1, le=500),
    actor: Actor = Depends(get_actor),
    farm: FarmService = Depends(FARM),
):
    return await farm.list_events(
        actor, field_id=field_id, crop_cycle_id=crop_cycle_id, event_type=type, since=since, until=until, limit=limit
    )


@_both(
    router.post, "/events", response_model=FieldEventRead, status_code=status.HTTP_201_CREATED,
    summary="Register Field Event",
)
@inject
async def create_event(body: FieldEventCreate, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)):
    return await farm.create_event(actor, body)


@router.get("/events/{event_id}", response_model=FieldEventRead, summary="Get Field Event")
@inject
async def get_event(event_id: UUID, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)):
    return await farm.get_event(actor, event_id)


@router.put("/events/{event_id}", response_model=FieldEventRead, summary="Update Field Event")
@inject
async def update_event(
    event_id: UUID, body: FieldEventUpdate, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)
):
    return await farm.update_event(actor, event_id, body)


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Field Event")
@inject
async def delete_event(event_id: UUID, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)):
    await farm.delete_event(actor, event_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
