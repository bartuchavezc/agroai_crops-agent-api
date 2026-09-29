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

from .models import ACTIVE_CROP_CYCLE_STATUSES, CropCycle, CropMaster, Field, FieldEvent
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
    LayoutPhoto,
    SunExposureRead,
)
from .repository import FarmRepository
from .solar import OCTANTS
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
            values["layout_objects"] = [o.model_dump() for o in field.layout_objects] + objects
        await self._save_layout(actor, field_id, **values)

    async def restart_layout_photo(self, actor: Actor, field_id: UUID, photo_id: str) -> LayoutPhoto:
        """Retry: allowed for a failed photo, or one stuck in 'processing' long enough that its background
        task must have died (e.g. the server restarted mid-way)."""
        _require_manager(actor)
        field = await self.get_field(actor, field_id)
        photos = [p.model_dump() for p in field.layout_photos]
        target = next((p for p in photos if p["id"] == photo_id), None)
        if target is None:
            raise NotFoundError("Layout photo not found.")
        if target["status"] == "done":
            raise InvalidInputError("This photo was already processed.")
        if target["status"] == "processing" and not _is_stale(target.get("updated_at")):
            raise InvalidInputError("This photo is still being processed.")
        target.update(status="processing", error=None, updated_at=utcnow().isoformat())
        await self._save_layout(actor, field_id, layout_photos=photos)
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

    # ---------- crop cycles ----------

    async def list_crop_cycles(
        self, actor: Actor, field_id: Optional[UUID] = None, status: Optional[str] = None
    ) -> list[CropCycleRead]:
        statuses = [status] if status else None
        items = await self.repo.list_crop_cycles(actor.account_id, field_id=field_id, statuses=statuses)
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
        cycle = await self.repo.create_crop_cycle(
            CropCycle(account_id=actor.account_id, created_by=actor.user_id, **data.model_dump())
        )
        return CropCycleRead.model_validate(cycle)

    async def update_crop_cycle(self, actor: Actor, cycle_id: UUID, data: CropCycleUpdate) -> CropCycleRead:
        _require_manager(actor)
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
    ) -> list[FieldEventRead]:
        items = await self.repo.list_events(
            actor.account_id,
            field_id=field_id,
            crop_cycle_id=crop_cycle_id,
            event_type=event_type,
            since=since,
            until=until,
            limit=min(max(limit, 1), 500),
        )
        return [FieldEventRead.model_validate(e) for e in items]

    async def get_event(self, actor: Actor, event_id: UUID) -> FieldEventRead:
        event = await self.repo.get_event(actor.account_id, event_id)
        if event is None:
            raise NotFoundError(f"Event {event_id} not found.")
        return FieldEventRead.model_validate(event)

    async def create_event(self, actor: Actor, data: FieldEventCreate) -> FieldEventRead:
        await self.get_field(actor, data.field_id)
        if data.crop_cycle_id:
            cycle = await self.get_crop_cycle(actor, data.crop_cycle_id)
            if cycle.field_id != data.field_id:
                raise InvalidInputError("The crop cycle does not belong to that field.")
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
        by_field: dict[UUID, list[ActiveCycleSummary]] = {}
        for cycle, crop in cycles:
            by_field.setdefault(cycle.field_id, []).append(
                ActiveCycleSummary(
                    id=cycle.id,
                    crop_name=crop.name,
                    variety=crop.variety,
                    status=cycle.status,
                    planting_date=cycle.planting_date,
                    expected_harvest_date=cycle.expected_harvest_date,
                )
            )
        return [
            FieldOverview(
                field=FieldRead.model_validate(f),
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
        ]
        result = compute_sun_exposure(field.latitude, obstacles)
        return SunExposureRead(field_id=field.id, field_name=field.name, by_season=result.by_season)

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
