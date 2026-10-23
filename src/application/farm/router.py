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
    LotCountCreate,
    LotCreate,
    LotLossCreate,
    LotRead,
    LotResow,
    LotResowRead,
    LotStatus,
    LotUpdate,
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
    ZoneRenumber,
)
from .service import FarmService
from .snapshot import FieldSnapshot, FieldSnapshotService
from .summary import FieldSummary, FieldSummaryService
from .log import LogPage, LogService

router = APIRouter(prefix="/farm-management", tags=["Farm Management"])

FARM = Provide["application.farm_service"]
LOG = Provide["application.log_service"]
SUMMARY = Provide["application.field_summary_service"]
SNAPSHOT = Provide["application.field_snapshot_service"]
SATELLITE = Provide["application.satellite_service"]


# ---------- overview ----------

@router.get("/overview", response_model=List[FieldOverview], summary="Fields with active lots")
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


@router.post(
    "/fields/{field_id}/zones/renumber", response_model=List[FieldZoneRead],
    summary="Renumber several zones at once (owner/tecnico)",
)
@inject
async def renumber_zones(
    field_id: UUID, body: ZoneRenumber, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)
):
    """E.g. swap Cantero 4 and Cantero 1: only the final numbering has to be unique per zone type."""
    return await farm.renumber_zones(actor, field_id, body)


@router.get("/zones/{zone_id}", response_model=FieldZoneRead, summary="Get a zone")
@inject
async def get_zone(zone_id: UUID, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)):
    return await farm.get_zone(actor, zone_id)


@router.get("/log", response_model=LogPage, summary="The bitácora of a field, a zone or a lot, by day")
@inject
async def bitacora(
    field_id: Optional[UUID] = None,
    zone_id: Optional[UUID] = None,
    lot_id: Optional[UUID] = None,
    type: Optional[EventType] = Query(None, description="Only events of this type"),
    before: Optional[datetime] = Query(None, description="Page back in time: `next_before` of the previous page"),
    since: Optional[datetime] = None,
    limit: int = Query(50, ge=1, le=200),
    actor: Actor = Depends(get_actor),
    log: LogService = Depends(LOG),
):
    """Exactly one of field_id / zone_id / lot_id. A lot's bitácora includes what was logged on its zone or field
    while it was there (event_lots), and the analyses that covered it; newest first, grouped by local day."""
    return await log.log(
        actor, field_id=field_id, zone_id=zone_id, lot_id=lot_id, before=before, since=since, limit=limit,
        event_type=type,
    )


@router.put("/zones/{zone_id}", response_model=FieldZoneRead, summary="Update a zone (owner/tecnico)")
@inject
async def update_zone(
    zone_id: UUID, body: FieldZoneUpdate, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)
):
    return await farm.update_zone(actor, zone_id, body)


@router.delete("/zones/{zone_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a zone (owner/tecnico)")
@inject
async def delete_zone(zone_id: UUID, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)):
    """Its lots stay in the field, without a zone."""
    await farm.delete_zone(actor, zone_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/fields/{field_id}/summary", response_model=FieldSummary, summary="A field's home screen in one call")
@inject
async def field_summary(
    field_id: UUID, actor: Actor = Depends(get_actor), summary: FieldSummaryService = Depends(SUMMARY)
):
    """General state, zones with their last analysis and photo, active alerts, today's reminders and the irrigation
    outlook. The irrigation block is null when the field has no coordinates or the weather data is down."""
    return await summary.summary(actor, field_id)


@router.get("/fields/{field_id}/snapshot", response_model=FieldSnapshot, summary="A field's current state in one read")
@inject
async def field_snapshot(
    field_id: UUID,
    season: Optional[str] = Query(None, description='Only the lots of this season ("26/27")'),
    actor: Actor = Depends(get_actor),
    snapshots: FieldSnapshotService = Depends(SNAPSHOT),
):
    """Zones with their active lots, pH and last bitácora entry; every lot by status; the latest entries; the next
    open tasks; today's reminders and the last completed analysis. Same read as the agent's get_farm_snapshot."""
    return await snapshots.snapshot(actor, field_id, season)


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


# ---------- lots ----------

@_both(router.get, "/lots", response_model=List[LotRead], summary="List Crop Cycles")
@inject
async def list_lots(
    field_id: Optional[UUID] = None,
    status_filter: Optional[LotStatus] = Query(None, alias="status"),
    zone_id: Optional[UUID] = None,
    actor: Actor = Depends(get_actor),
    farm: FarmService = Depends(FARM),
):
    return await farm.list_lots(actor, field_id=field_id, status=status_filter, zone_id=zone_id)


@_both(
    router.post, "/lots", response_model=LotRead, status_code=status.HTTP_201_CREATED,
    summary="Create Crop Cycle",
)
@inject
async def create_lot(
    body: LotCreate, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)
):
    return await farm.create_lot(actor, body)


@router.get("/lots/{cycle_id}", response_model=LotRead, summary="Get Crop Cycle")
@inject
async def get_lot(cycle_id: UUID, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)):
    return await farm.get_lot(actor, cycle_id)


@router.put("/lots/{cycle_id}", response_model=LotRead, summary="Update Crop Cycle")
@inject
async def update_lot(
    cycle_id: UUID, body: LotUpdate, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)
):
    return await farm.update_lot(actor, cycle_id, body)


@router.post("/lots/{cycle_id}/losses", response_model=FieldEventRead, status_code=status.HTTP_201_CREATED,
             summary="Log plants or seeds lost in a lot")
@inject
async def lot_loss(
    cycle_id: UUID, body: LotLossCreate, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)
):
    """A `loss` entry on that lot: its sown quantity stays, its live quantity drops (a percent is of what is alive).
    When nothing is left, the lot fails."""
    lot = await farm.get_lot(actor, cycle_id)
    return await farm.create_event(actor, FieldEventCreate(
        field_id=lot.field_id, lot_ids=[lot.id], type="loss", quantity=body.quantity, occurred_at=body.occurred_at,
        data={k: v for k, v in {"percent": body.percent, "cause": body.cause}.items() if v is not None},
        reason=body.notes,
    ))


@router.post("/lots/{cycle_id}/counts", response_model=FieldEventRead, status_code=status.HTTP_201_CREATED,
             summary="Record a count of what is alive in a lot")
@inject
async def lot_count(
    cycle_id: UUID, body: LotCountCreate, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)
):
    lot = await farm.get_lot(actor, cycle_id)
    return await farm.create_event(actor, FieldEventCreate(
        field_id=lot.field_id, lot_ids=[lot.id], type="inspection", occurred_at=body.occurred_at, notes=body.notes,
        data={"count": body.count}, image_identifier=body.image_identifier,
    ))


@router.post("/lots/{cycle_id}/resow", response_model=LotResowRead, status_code=status.HTTP_201_CREATED,
             summary="Resow (part of) a lot")
@inject
async def resow_lot(
    cycle_id: UUID, body: LotResow, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)
):
    original, resown = await farm.resow(actor, cycle_id, **body.model_dump())
    return LotResowRead(original=original, resown=resown)


@router.delete("/lots/{cycle_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Crop Cycle")
@inject
async def delete_lot(cycle_id: UUID, actor: Actor = Depends(get_actor), farm: FarmService = Depends(FARM)):
    await farm.delete_lot(actor, cycle_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- events ----------

@_both(router.get, "/events", response_model=List[FieldEventRead], summary="List Field Events")
@inject
async def list_events(
    field_id: Optional[UUID] = None,
    lot_id: Optional[UUID] = None,
    zone_id: Optional[UUID] = None,
    type: Optional[EventType] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    before: Optional[datetime] = Query(None, description="Page back in time: only events older than this instant"),
    limit: int = Query(50, ge=1, le=500),
    actor: Actor = Depends(get_actor),
    farm: FarmService = Depends(FARM),
):
    return await farm.list_events(
        actor, field_id=field_id, lot_id=lot_id, event_type=type, since=since, until=until, limit=limit,
        zone_id=zone_id, before=before,
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
