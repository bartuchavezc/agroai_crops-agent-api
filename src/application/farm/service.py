"""
Farm service: the single write path for fields, crop catalog, crop cycles and events.
Used by both the HTTP routers and the agent tools.
"""
import logging
import math
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import InvalidInputError, NotFoundError, PermissionDeniedError

from src.application.notifications.service import NotificationService
from src.application.soil_data.service import SoilContextService

from .models import ACTIVE_CROP_CYCLE_STATUSES, CropCycle, CropMaster, Field, FieldEvent, FieldZone
from .schemas import (
    ActiveCycleSummary,
    CropCycleCreate,
    CropCycleRead,
    CropCycleUpdate,
    CropMasterCreate,
    CropMasterRead,
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
    LayoutPhoto,
    SunCellRead,
    SunExposureRead,
    SunMapRead,
    SunMomentRead,
    TerrainSunSummary,
)
from .repository import FarmRepository
from .shadows import SunMap, cells_inside, shadow_casters, sun_map
from .site import campo_polygon_m, environment_polygon_m, sun_area_polygon_m
from .solar import OCTANTS, SEASON_DATES
from .solar import Obstacle as SolarObstacle
from .solar import compute_sun_exposure

logger = logging.getLogger(__name__)


def _octant_from_xy(x_m: float, y_m: float) -> str:
    """Compass octant of a point on the top-down plan (x=East, y=North). The solar model only knows 8
    directions with no distance, so exact positions are rounded to the nearest one on purpose."""
    bearing = math.degrees(math.atan2(x_m, y_m)) % 360  # 0=N, clockwise
    return OCTANTS[round(bearing / 45) % 8]


LAYOUT_PHOTO_STALE_SECONDS = 120  # a background extraction normally takes well under this


def _is_stale(updated_at: Optional[str]) -> bool:
    if not updated_at:
        return True
    return (utcnow() - datetime.fromisoformat(updated_at)).total_seconds() > LAYOUT_PHOTO_STALE_SECONDS


def _only_cells(result: SunMap, cells: list[tuple[float, float, float]]) -> SunMap:
    """The same sun map restricted to some cells (e.g. those inside the campo), with its own mean."""
    return SunMap(
        season=result.season, cell_size_m=result.cell_size_m, cells=cells, max_hours=result.max_hours,
        mean_hours=round(sum(c[2] for c in cells) / len(cells), 2), site_area_m2=len(cells) * result.cell_size_m**2,
    )


def _summarize_sun_map(result: SunMap, site: list[tuple[float, float]]) -> TerrainSunSummary:
    """Percent of the terrain in full sun / part shade / shade, and where the sunniest and shadiest spots are."""
    cells = result.cells
    if not cells:
        return TerrainSunSummary(
            mean_hours=0, max_hours=result.max_hours, full_sun_percent=0, part_shade_percent=0, shade_percent=0,
            sunniest_zone="sin datos", shadiest_zone="sin datos",
        )
    n = len(cells)
    full = sum(1 for _, _, h in cells if h >= 6) / n * 100
    shade = sum(1 for _, _, h in cells if h < 3) / n * 100
    cx = sum(p[0] for p in site) / len(site)
    cy = sum(p[1] for p in site) / len(site)

    def zone(selected: list[tuple[float, float, float]]) -> str:
        dx = sum(c[0] for c in selected) / len(selected) - cx
        dy = sum(c[1] for c in selected) / len(selected) - cy
        distance = math.hypot(dx, dy)
        if distance < 2:
            return "centro del área"
        return f"sector {_octant_from_xy(dx, dy)} (a {distance:.0f} m del centro)"

    hours = sorted(c[2] for c in cells)
    if hours[-1] - hours[0] < 0.25:  # no meaningful difference across the terrain
        sunniest = shadiest = "toda el área por igual"
    else:
        cut = max(1, n // 10)
        sunniest = zone([c for c in cells if c[2] >= hours[-cut]])
        shadiest = zone([c for c in cells if c[2] <= hours[cut - 1]])
    return TerrainSunSummary(
        mean_hours=result.mean_hours,
        max_hours=result.max_hours,
        full_sun_percent=round(full, 1),
        part_shade_percent=round(100 - full - shade, 1),
        shade_percent=round(shade, 1),
        sunniest_zone=sunniest,
        shadiest_zone=shadiest,
    )


_SINGLE_ELEMENTS = {"entorno", "campo"}
_AREA_ELEMENTS = _SINGLE_ELEMENTS  # areas, not obstacles: they cast no shade


def _has_entorno(field: FieldRead, objects: Optional[list[dict]] = None) -> bool:
    if objects is not None:
        return any(o["type"] == "entorno" for o in objects)
    return any(o.type == "entorno" for o in field.layout_objects)


def _require_manager(actor: Actor) -> None:
    if not actor.is_manager:
        raise PermissionDeniedError("Only owner or tecnico can do this.")


class FarmService:
    def __init__(
        self,
        repository: FarmRepository,
        notification_service: NotificationService,
        soil_context_service: SoilContextService,
    ):
        self.repo = repository
        self.notifications = notification_service
        self.soil_context = soil_context_service

    async def _soil_context_payload(self, latitude: Optional[float], longitude: Optional[float]) -> Optional[dict]:
        """Best-effort: a field without coordinates (or a lookup failure) just gets no cached soil
        context — never blocks creating/editing the field."""
        if latitude is None or longitude is None:
            return None
        try:
            context = await self.soil_context.lookup(latitude, longitude)
        except Exception:
            logger.exception("Soil context lookup failed")
            return None
        return context.model_dump(mode="json") if context else None

    async def ensure_soilgrids(self, actor: Actor, field_id: UUID) -> FieldRead:
        """The field with the SoilGrids estimate in its cached soil_context, fetching it the first time it is needed
        (analyses, the soil tool): a local lookup in the imported SoilGrids tiles. Best-effort; any user of the account
        may trigger it, since it only fills a cache."""
        field = await self.get_field(actor, field_id)
        if field.latitude is None or field.longitude is None:
            return field
        current = field.soil_context.model_dump(mode="json") if field.soil_context else None
        try:
            updated = await self.soil_context.add_soilgrids(current, field.latitude, field.longitude)
        except Exception:
            logger.exception("SoilGrids lookup failed")
            return field
        if updated is None or updated == current:
            return field
        row = await self.repo.update_field(actor.account_id, field_id, {"soil_context": updated})
        return FieldRead.model_validate(row) if row else field

    # ---------- fields ----------

    async def list_fields(self, actor: Actor) -> list[FieldRead]:
        return [FieldRead.model_validate(f) for f in await self.repo.list_fields(actor.account_id)]

    async def get_field(self, actor: Actor, field_id: UUID) -> FieldRead:
        field = await self.repo.get_field(actor.account_id, field_id)
        if field is None:
            raise NotFoundError(f"Field {field_id} not found.")
        return FieldRead.model_validate(field)

    async def find_fields(self, actor: Actor, name: str) -> list[FieldRead]:
        return [FieldRead.model_validate(f) for f in await self.repo.find_fields_by_name(actor.account_id, name)]

    async def create_field(self, actor: Actor, data: FieldCreate) -> FieldRead:
        _require_manager(actor)
        payload = data.model_dump()
        payload["soil_context"] = await self._soil_context_payload(data.latitude, data.longitude)
        try:
            field = await self.repo.create_field(Field(account_id=actor.account_id, **payload))
        except IntegrityError:
            raise InvalidInputError(f"A field named '{data.name}' already exists.") from None
        return FieldRead.model_validate(field)

    async def update_field(self, actor: Actor, field_id: UUID, data: FieldUpdate) -> FieldRead:
        _require_manager(actor)
        values = data.model_dump(exclude_unset=True)
        if "latitude" in values or "longitude" in values:
            current = await self.repo.get_field(actor.account_id, field_id)
            if current is None:
                raise NotFoundError(f"Field {field_id} not found.")
            latitude = values.get("latitude", current.latitude)
            longitude = values.get("longitude", current.longitude)
            values["soil_context"] = await self._soil_context_payload(latitude, longitude)
        try:
            field = await self.repo.update_field(actor.account_id, field_id, values)
        except IntegrityError:
            raise InvalidInputError("A field with that name already exists.") from None
        if field is None:
            raise NotFoundError(f"Field {field_id} not found.")
        return FieldRead.model_validate(field)

    # ---------- layout photos (processed in the background) ----------

    async def _save_layout(self, actor: Actor, field_id: UUID, **values) -> FieldRead:
        field = await self.repo.update_field(actor.account_id, field_id, values)
        if field is None:
            raise NotFoundError(f"Field {field_id} not found.")
        return FieldRead.model_validate(field)

    async def add_layout_photo(self, actor: Actor, field_id: UUID, photo: LayoutPhoto) -> LayoutPhoto:
        _require_manager(actor)
        field = await self.get_field(actor, field_id)
        photos = [p.model_dump() for p in field.layout_photos] + [photo.model_dump()]
        await self._save_layout(actor, field_id, layout_photos=photos)
        return photo

    async def finish_layout_photo(
        self,
        actor: Actor,
        field_id: UUID,
        photo_id: str,
        objects: Optional[list[dict]],
        error: Optional[str],
        camera_xy: Optional[tuple[float, float]] = None,
    ) -> None:
        """Background job result: merge detected objects into the layout and mark the photo done, or mark it
        failed. Re-reads the field right before writing, and skips silently if the photo was deleted or
        already finished meanwhile (a retry racing an earlier attempt must not duplicate objects)."""
        field = await self.get_field(actor, field_id)
        photos = [p.model_dump() for p in field.layout_photos]
        target = next((p for p in photos if p["id"] == photo_id), None)
        if target is None or target["status"] != "processing":
            return
        target.update(status="failed" if error else "done", error=error, updated_at=utcnow().isoformat())
        if camera_xy is not None and not error:
            target.update(camera_x_m=camera_xy[0], camera_y_m=camera_xy[1])
        values: dict = {"layout_photos": photos}
        if not error and objects:
            existing = [o.model_dump() for o in field.layout_objects]
            have_single = {o["type"] for o in existing if o["type"] in _SINGLE_ELEMENTS}
            # a plan has one entorno and one campo; a photo processed in parallel must not add a second one
            objects = [o for o in objects if o.get("type") not in have_single]
            values["layout_objects"] = existing + objects
        await self._save_layout(actor, field_id, **values)

    async def restart_layout_photo(
        self,
        actor: Actor,
        field_id: UUID,
        photo_id: str,
        entorno_ancho_m: Optional[float] = None,
        entorno_largo_m: Optional[float] = None,
        camera_height_m: Optional[float] = None,
    ) -> LayoutPhoto:
        """Retry / reprocess. Allowed for a failed photo, one stuck in 'processing' long enough that its background
        task must have died, or an already processed one ("Reprocesar"): in that case the objects it produced are
        removed first so they are regenerated instead of duplicated. The entorno's measures can be (re)given here,
        for photos uploaded before they were asked for."""
        _require_manager(actor)
        field = await self.get_field(actor, field_id)
        photos = [p.model_dump() for p in field.layout_photos]
        target = next((p for p in photos if p["id"] == photo_id), None)
        if target is None:
            raise NotFoundError("Layout photo not found.")
        if target["status"] == "processing" and not _is_stale(target.get("updated_at")):
            raise InvalidInputError("This photo is still being processed.")
        values: dict = {}
        if target["status"] == "done":
            # objects from this photo — and, for photos processed before elements carried a photo_id, the
            # untagged AI ones (they were placed by the old method and would sit on top of the new result)
            legacy = target.get("camera_x_m") is None
            values["layout_objects"] = [
                o.model_dump()
                for o in field.layout_objects
                if o.photo_id != photo_id and not (legacy and o.source == "photo_ai" and o.photo_id is None)
            ]
        target.update(status="processing", error=None, updated_at=utcnow().isoformat())
        if entorno_ancho_m:
            target["entorno_ancho_m"] = entorno_ancho_m
        if entorno_largo_m:
            target["entorno_largo_m"] = entorno_largo_m
        if camera_height_m:
            target["camera_height_m"] = camera_height_m
        if target.get("camera_x_m") is not None and not _has_entorno(field, values.get("layout_objects")):
            target["camera_x_m"] = target["camera_y_m"] = None  # the camera spot came from an entorno that is gone
        values["layout_photos"] = photos
        await self._save_layout(actor, field_id, **values)
        return LayoutPhoto.model_validate(target)

    async def remove_layout_photo(self, actor: Actor, field_id: UUID, photo_id: str) -> None:
        _require_manager(actor)
        field = await self.get_field(actor, field_id)
        photos = [p.model_dump() for p in field.layout_photos if p.id != photo_id]
        await self._save_layout(actor, field_id, layout_photos=photos)

    async def delete_field(self, actor: Actor, field_id: UUID) -> None:
        _require_manager(actor)
        if not await self.repo.delete_field(actor.account_id, field_id):
            raise NotFoundError(f"Field {field_id} not found.")

    # ---------- crop masters ----------

    async def list_crop_masters(
        self, actor: Actor, query: Optional[str] = None, skip: int = 0, limit: int = 200
    ) -> list[CropMasterRead]:
        items = await self.repo.list_crop_masters(actor.account_id, query=query, skip=skip, limit=limit)
        return [CropMasterRead.model_validate(c) for c in items]

    async def get_crop_master(self, actor: Actor, crop_master_id: UUID) -> CropMasterRead:
        crop = await self.repo.get_visible_crop_master(actor.account_id, crop_master_id)
        if crop is None:
            raise NotFoundError(f"Crop {crop_master_id} not found.")
        return CropMasterRead.model_validate(crop)

    async def find_crop_masters(self, actor: Actor, name: str, variety: Optional[str] = None) -> list[CropMasterRead]:
        items = await self.repo.find_crop_masters_by_name(actor.account_id, name, variety)
        return [CropMasterRead.model_validate(c) for c in items]

    async def create_crop_master(self, actor: Actor, data: CropMasterCreate) -> CropMasterRead:
        _require_manager(actor)
        crop = await self.repo.create_crop_master(CropMaster(account_id=actor.account_id, **data.model_dump()))
        return CropMasterRead.model_validate(crop)

    async def delete_crop_master(self, actor: Actor, crop_master_id: UUID) -> None:
        _require_manager(actor)
        try:
            deleted = await self.repo.delete_crop_master(actor.account_id, crop_master_id)
        except IntegrityError:
            raise InvalidInputError("This crop is used by crop cycles and cannot be deleted.") from None
        if not deleted:
            raise NotFoundError(f"Crop {crop_master_id} not found (global catalog entries cannot be deleted).")

    # ---------- zones ----------

    async def list_zones(self, actor: Actor, field_id: Optional[UUID] = None) -> list[FieldZoneRead]:
        if field_id:
            await self.get_field(actor, field_id)
        return [FieldZoneRead.model_validate(z) for z in await self.repo.list_zones(actor.account_id, field_id)]

    async def get_zone(self, actor: Actor, zone_id: UUID) -> FieldZoneRead:
        zone = await self.repo.get_zone(actor.account_id, zone_id)
        if zone is None:
            raise NotFoundError(f"Zone {zone_id} not found.")
        return FieldZoneRead.model_validate(zone)

    async def _check_zone_in_field(self, actor: Actor, zone_id: Optional[UUID], field_id: UUID) -> None:
        if zone_id and (await self.get_zone(actor, zone_id)).field_id != field_id:
            raise InvalidInputError("The zone does not belong to that field.")

    async def create_zone(self, actor: Actor, field_id: UUID, data: FieldZoneCreate) -> FieldZoneRead:
        _require_manager(actor)
        await self.get_field(actor, field_id)
        number = data.number or await self.repo.next_zone_number(field_id, data.type)
        if await self.repo.zone_number_taken(field_id, data.type, number):
            raise InvalidInputError(f"That field already has a {data.type} number {number}.")
        zone = await self.repo.create_zone(
            FieldZone(account_id=actor.account_id, field_id=field_id, **{**data.model_dump(), "number": number})
        )
        return FieldZoneRead.model_validate(zone)

    async def update_zone(self, actor: Actor, zone_id: UUID, data: FieldZoneUpdate) -> FieldZoneRead:
        _require_manager(actor)
        current = await self.get_zone(actor, zone_id)
        values = data.model_dump(exclude_unset=True)
        zone_type, number = values.get("type") or current.type, values.get("number") or current.number
        if await self.repo.zone_number_taken(current.field_id, zone_type, number, exclude_id=zone_id):
            raise InvalidInputError(f"That field already has a {zone_type} number {number}.")
        zone = await self.repo.update_zone(actor.account_id, zone_id, values)
        return FieldZoneRead.model_validate(zone)

    async def delete_zone(self, actor: Actor, zone_id: UUID) -> None:
        _require_manager(actor)
        if not await self.repo.delete_zone(actor.account_id, zone_id):
            raise NotFoundError(f"Zone {zone_id} not found.")

    # ---------- crop cycles ----------

    async def list_crop_cycles(
        self,
        actor: Actor,
        field_id: Optional[UUID] = None,
        status: Optional[str] = None,
        zone_id: Optional[UUID] = None,
    ) -> list[CropCycleRead]:
        statuses = [status] if status else None
        items = await self.repo.list_crop_cycles(
            actor.account_id, field_id=field_id, statuses=statuses, zone_id=zone_id
        )
        return [CropCycleRead.model_validate(c) for c in items]

    async def get_crop_cycle(self, actor: Actor, cycle_id: UUID) -> CropCycleRead:
        cycle = await self.repo.get_crop_cycle(actor.account_id, cycle_id)
        if cycle is None:
            raise NotFoundError(f"Crop cycle {cycle_id} not found.")
        return CropCycleRead.model_validate(cycle)

    async def create_crop_cycle(self, actor: Actor, data: CropCycleCreate) -> CropCycleRead:
        _require_manager(actor)
        await self.get_field(actor, data.field_id)
        await self.get_crop_master(actor, data.crop_master_id)
        await self._check_zone_in_field(actor, data.zone_id, data.field_id)
        cycle = await self.repo.create_crop_cycle(
            CropCycle(account_id=actor.account_id, created_by=actor.user_id, **data.model_dump())
        )
        return CropCycleRead.model_validate(cycle)

    async def update_crop_cycle(self, actor: Actor, cycle_id: UUID, data: CropCycleUpdate) -> CropCycleRead:
        _require_manager(actor)
        if data.zone_id:
            await self._check_zone_in_field(actor, data.zone_id, (await self.get_crop_cycle(actor, cycle_id)).field_id)
        cycle = await self.repo.update_crop_cycle(actor.account_id, cycle_id, data.model_dump(exclude_unset=True))
        if cycle is None:
            raise NotFoundError(f"Crop cycle {cycle_id} not found.")
        return CropCycleRead.model_validate(cycle)

    async def delete_crop_cycle(self, actor: Actor, cycle_id: UUID) -> None:
        _require_manager(actor)
        if not await self.repo.delete_crop_cycle(actor.account_id, cycle_id):
            raise NotFoundError(f"Crop cycle {cycle_id} not found.")

    # ---------- events ----------

    async def list_events(
        self,
        actor: Actor,
        field_id: Optional[UUID] = None,
        crop_cycle_id: Optional[UUID] = None,
        event_type: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 50,
        zone_id: Optional[UUID] = None,
        before: Optional[datetime] = None,
    ) -> list[FieldEventRead]:
        items = await self.repo.list_events(
            actor.account_id,
            field_id=field_id,
            crop_cycle_id=crop_cycle_id,
            event_type=event_type,
            since=since,
            until=until,
            limit=min(max(limit, 1), 500),
            zone_id=zone_id,
            before=before,
        )
        return [FieldEventRead.model_validate(e) for e in items]

    async def get_event(self, actor: Actor, event_id: UUID) -> FieldEventRead:
        event = await self.repo.get_event(actor.account_id, event_id)
        if event is None:
            raise NotFoundError(f"Event {event_id} not found.")
        return FieldEventRead.model_validate(event)

    async def create_event(self, actor: Actor, data: FieldEventCreate) -> FieldEventRead:
        await self.get_field(actor, data.field_id)
        await self._check_zone_in_field(actor, data.zone_id, data.field_id)
        if data.crop_cycle_id:
            cycle = await self.get_crop_cycle(actor, data.crop_cycle_id)
            if cycle.field_id != data.field_id:
                raise InvalidInputError("The crop cycle does not belong to that field.")
            if data.zone_id is None:
                data = data.model_copy(update={"zone_id": cycle.zone_id})
        values = data.model_dump()
        values["occurred_at"] = values["occurred_at"] or utcnow()
        event = await self.repo.create_event(
            FieldEvent(
                account_id=actor.account_id,
                author_user_id=actor.user_id,
                source="agent" if actor.via == "agent" else "user",
                **values,
            )
        )
        await self.notifications.notify_account(
            account_id=actor.account_id,
            exclude_user_id=actor.user_id,
            type="event",
            title="Nuevo evento registrado",
            message=f"{data.type} en el campo" + (f" ({data.notes})" if data.notes else ""),
            entity_type="event",
            entity_id=event.id,
            field_id=data.field_id,
        )
        return FieldEventRead.model_validate(event)

    async def _editable_event(self, actor: Actor, event_id: UUID) -> FieldEvent:
        event = await self.repo.get_event(actor.account_id, event_id)
        if event is None:
            raise NotFoundError(f"Event {event_id} not found.")
        if not actor.is_manager and event.author_user_id != actor.user_id:
            raise PermissionDeniedError("You can only modify events you registered.")
        return event

    async def update_event(self, actor: Actor, event_id: UUID, data: FieldEventUpdate) -> FieldEventRead:
        await self._editable_event(actor, event_id)
        event = await self.repo.update_event(actor.account_id, event_id, data.model_dump(exclude_unset=True))
        return FieldEventRead.model_validate(event)

    async def delete_event(self, actor: Actor, event_id: UUID) -> None:
        await self._editable_event(actor, event_id)
        await self.repo.delete_event(actor.account_id, event_id)

    # ---------- overview ----------

    async def overview(self, actor: Actor) -> list[FieldOverview]:
        fields = await self.repo.list_fields(actor.account_id)
        cycles = await self.repo.active_cycles_with_crop(actor.account_id)
        last_events = await self.repo.last_event_by_field(actor.account_id)
        zones = [FieldZoneRead.model_validate(z) for z in await self.repo.list_zones(actor.account_id)]
        labels = {z.id: z.label for z in zones}
        by_field: dict[UUID, list[ActiveCycleSummary]] = {}
        for cycle, crop in cycles:
            by_field.setdefault(cycle.field_id, []).append(
                ActiveCycleSummary(
                    id=cycle.id,
                    crop_name=crop.name,
                    crop_i18n=crop.i18n or {},
                    variety=crop.variety,
                    status=cycle.status,
                    planting_date=cycle.planting_date,
                    expected_harvest_date=cycle.expected_harvest_date,
                    zone_id=cycle.zone_id,
                    zone_label=labels.get(cycle.zone_id),
                )
            )
        return [
            FieldOverview(
                field=FieldRead.model_validate(f),
                zones=[z for z in zones if z.field_id == f.id],
                active_cycles=by_field.get(f.id, []),
                last_event_at=last_events.get(f.id),
            )
            for f in fields
        ]

    async def crop_families(self, actor: Actor) -> set[str]:
        """Botanical families the account has ever grown, for agent knowledge-module selection."""
        return await self.repo.used_crop_families(actor.account_id)

    # ---------- sun exposure ----------

    async def sun_exposure(self, actor: Actor, field_id: UUID) -> SunExposureRead:
        field = await self.get_field(actor, field_id)
        if field.latitude is None:
            raise InvalidInputError(f"Field '{field.name}' has no coordinates; sun exposure needs a latitude.")
        obstacles = [
            SolarObstacle(type=o.type, height_m=o.height_m, direction=_octant_from_xy(o.x_m, o.y_m))
            for o in field.layout_objects
            if o.type not in _AREA_ELEMENTS
        ]
        result = compute_sun_exposure(field.latitude, obstacles)
        environment, plot = self._area_summaries(field)
        return SunExposureRead(
            field_id=field.id, field_name=field.name, by_season=result.by_season, environment=environment, plot=plot
        )

    def _area_summaries(
        self, field: FieldRead
    ) -> tuple[Optional[dict[str, TerrainSunSummary]], Optional[dict[str, TerrainSunSummary]]]:
        """Geometric sun/shade per season over the entorno and, separately, over the campo. (None, None) when
        there is no area or nothing casts shade."""
        area = sun_area_polygon_m(field)
        if not area or len(area) < 3 or field.latitude is None or not shadow_casters(field.layout_objects):
            return None, None
        try:
            maps = {s: sun_map(field.layout_objects, area, field.latitude, s) for s in SEASON_DATES}
            environment = {season: _summarize_sun_map(result, area) for season, result in maps.items()}
            campo = campo_polygon_m(field)
            plot = None
            if campo and len(campo) >= 3 and environment_polygon_m(field):
                plot = {}
                for season, result in maps.items():
                    inside = cells_inside(result.cells, campo)
                    if inside:
                        plot[season] = _summarize_sun_map(_only_cells(result, inside), campo)
                plot = plot or None
            return environment, plot
        except Exception:  # noqa: BLE001 - a geometry hiccup must not take down the octant estimate
            logger.exception("Area sun summary failed")
            return None, None

    async def sun_map(self, actor: Actor, field_id: UUID, season: str, include_shadows: bool = False) -> SunMapRead:
        """Hours of direct sun for every 1 m x 1 m cell of the entorno (or of the campo, if that is all the plan
        has). The campo's own average is reported apart, never mixed into the entorno's."""
        field = await self.get_field(actor, field_id)
        if field.latitude is None:
            raise InvalidInputError(f"Field '{field.name}' has no coordinates; the sun map needs a latitude.")
        if season not in SEASON_DATES:
            raise InvalidInputError(f"Unknown season '{season}'. Use one of: {', '.join(SEASON_DATES)}.")
        area = sun_area_polygon_m(field)
        if not area or len(area) < 3:
            raise InvalidInputError(
                f"Field '{field.name}' has no entorno on the plan yet: upload a photo of its surroundings with the "
                "entorno's width and length, or draw it on the plan."
            )
        result = sun_map(field.layout_objects, area, field.latitude, season, include_shadows=include_shadows)
        campo = campo_polygon_m(field) if environment_polygon_m(field) else None
        plot_cells = cells_inside(result.cells, campo) if campo else []
        return SunMapRead(
            field_id=field.id,
            season=result.season,
            cell_size_m=result.cell_size_m,
            cells=[SunCellRead(x=x, y=y, hours=h) for x, y, h in result.cells],
            max_hours=result.max_hours,
            mean_hours=result.mean_hours,
            site_area_m2=result.site_area_m2,
            plot_mean_hours=round(sum(c[2] for c in plot_cells) / len(plot_cells), 2) if plot_cells else None,
            timeline=[
                SunMomentRead(hour=m.hour, altitude_deg=m.altitude_deg, azimuth_deg=m.azimuth_deg, shadows=m.shadows)
                for m in result.timeline
            ],
        )

    # ---------- harvest totals ----------

    async def harvest_totals(
        self, actor: Actor, field_id: Optional[UUID] = None, crop_master_id: Optional[UUID] = None,
        year: Optional[int] = None,
    ) -> dict:
        year = year or utcnow().year
        since = datetime(year, 1, 1, tzinfo=utcnow().tzinfo)
        until = datetime(year + 1, 1, 1, tzinfo=utcnow().tzinfo)
        events = await self.repo.list_events(
            actor.account_id, field_id=field_id, event_type="harvest", since=since, until=until, limit=1000
        )
        if crop_master_id:
            cycle_ids = {
                c.id for c in await self.repo.list_crop_cycles(actor.account_id, field_id=field_id)
                if c.crop_master_id == crop_master_id
            }
            events = [e for e in events if e.crop_cycle_id in cycle_ids]
        by_unit: dict[str, float] = {}
        for e in events:
            if e.quantity is None:
                continue
            unit = e.unit or "unidades"
            by_unit[unit] = by_unit.get(unit, 0.0) + e.quantity
        return {
            "year": year,
            "harvest_count": len(events),
            "totals_by_unit": {k: round(v, 2) for k, v in by_unit.items()},
        }

__all__ = ["FarmService", "ACTIVE_CROP_CYCLE_STATUSES"]
