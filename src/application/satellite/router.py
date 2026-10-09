from datetime import date
from typing import Optional
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor

from .schemas import ZoneSatelliteStatus
from .service import ZoneSatelliteService

router = APIRouter(prefix="/satellite", tags=["Satellite"])

SATELLITE = Provide["application.satellite_service"]


@router.get("/fields/{field_id}/status", response_model=ZoneSatelliteStatus, summary="Zone Satellite Status")
@inject
async def field_satellite_status(
    field_id: UUID,
    refresh: bool = Query(True, description="false: only stored data, no Copernicus call and no alerts written"),
    actor: Actor = Depends(get_actor),
    satellite: ZoneSatelliteService = Depends(SATELLITE),
):
    """With refresh=false it is a pure read: safe on every render. The status carries the last clear pass, the one
    before it (`previous_ndvi_mean`, `ndvi_delta`) and the validity threshold a pass must meet."""
    return await satellite.check_field(actor, field_id, refresh=refresh)


@router.get("/fields/{field_id}/series", summary="Field Satellite Time Series (stored data, no Copernicus call)")
@inject
async def field_satellite_series(
    field_id: UUID,
    metric: str = Query("ndvi", description="ndvi | ndre | ndmi | evi | ndwi"),
    metrics: Optional[str] = Query(None, description="Several at once, comma separated (wins over `metric`)"),
    since: Optional[date] = Query(None, description="Default: one year ago"),
    until: Optional[date] = Query(None, description="Default: today"),
    include_masked: bool = Query(False, description="Also list the dates fully covered by clouds (no values)"),
    actor: Actor = Depends(get_actor),
    satellite: ZoneSatelliteService = Depends(SATELLITE),
):
    """`passes` lists every Sentinel-2 date with `discarded` / `discard_reason`; `weekly_by_metric` has one weekly
    table per requested metric (`weekly` is the first one, as before)."""
    names = [m.strip() for m in metrics.split(",") if m.strip()] if metrics else None
    return await satellite.series(
        actor, field_id, metric=metric, since=since, until=until, metrics=names, include_masked=include_masked
    )


@router.post("/fields/{field_id}/sync", summary="Refresh The Field's Satellite Series From Copernicus")
@inject
async def sync_field_satellite_series(
    field_id: UUID, actor: Actor = Depends(get_actor), satellite: ZoneSatelliteService = Depends(SATELLITE)
):
    return await satellite.sync(actor, field_id)


@router.get("/fields/{field_id}/image", summary="Map of the field drawn from our stored satellite imagery")
@inject
async def field_satellite_image(
    field_id: UUID,
    layer: str = Query("ndvi", description="ndvi | ndmi | ndwi | rgb"),
    date: Optional[date] = Query(None, description="One stored pass (YYYY-MM-DD) instead of the composite"),
    window_days: Optional[int] = Query(None, ge=1, le=45, description="Composite window; default 15 days"),
    actor: Actor = Depends(get_actor),
    satellite: ZoneSatelliteService = Depends(SATELLITE),
):
    """Computed from the pixels we stored, never from a request to Copernicus. By default the pixel-by-pixel median of
    the passes of the last 15 days up to the latest one we have, using only each pass's clear pixels (a cloud in one
    pass is filled from another; pixels no pass saw clearly are transparent). `coverage` is the share of the field
    with a value. With `date`, that single pass (404 if we hold no imagery for it). Without any stored imagery yet,
    `image_identifier` is null."""
    return _map_response(await satellite.get_or_render_image(
        actor, field_id, layer=layer, on_date=date, window_days=window_days
    ))


@router.post("/fields/{field_id}/render-map", summary="Redraw the map from the stored imagery")
@inject
async def render_field_map(
    field_id: UUID,
    layer: str = Query("ndvi", description="ndvi | ndmi | ndwi | rgb"),
    window_days: Optional[int] = Query(None, ge=1, le=45),
    actor: Actor = Depends(get_actor),
    satellite: ZoneSatelliteService = Depends(SATELLITE),
):
    return _map_response(await satellite.get_or_render_image(
        actor, field_id, force=True, layer=layer, window_days=window_days
    ))


def _map_response(satellite_map):
    if satellite_map is None:
        return {
            "image_identifier": None,
            "message": "This field has no stored satellite imagery yet; it fills in with the daily sync.",
        }
    return {
        "image_identifier": satellite_map.image_identifier, "bbox": satellite_map.bbox, "layer": satellite_map.layer,
        "date": satellite_map.date.isoformat(), "window_days": satellite_map.window_days,
        "coverage": satellite_map.coverage, "passes_used": satellite_map.passes_used,
    }


@router.get(
    "/fields/{field_id}/boundary-base-image",
    summary="True-Color Base Image For Drawing The Field's Boundary",
)
@inject
async def field_boundary_base_image(
    field_id: UUID, actor: Actor = Depends(get_actor), satellite: ZoneSatelliteService = Depends(SATELLITE)
):
    result = await satellite.render_delineation_base(actor, field_id)
    if not result:
        return {"image_identifier": None, "bbox": None, "message": "Satellite imagery unavailable right now."}
    image_identifier, bbox = result
    return {"image_identifier": image_identifier, "bbox": bbox}
