"""
The capture plan of a guided walk: zone by zone, which photos to take — always a general shot, then the open
follow-ups (the most severe and the longest without a photo first), then a close-up if a slot is left. A zone
upload takes at most MAX_ZONE_PHOTOS, so the follow-ups that don't fit are counted as deferred: next time they
are the longest without a photo, so they come first.
"""
from datetime import datetime, timezone
from typing import Iterable

from src.application.farm.schemas import ActiveLotSummary, FieldZoneRead
from src.application.reports.schemas import MAX_ZONE_PHOTOS

from .schemas import CaptureCrop, CapturePlan, CaptureStep, CaptureZone, FollowUpRead

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
# What a close-up should show, by where the lot is in its cycle.
_DETAIL_HINTS = {
    "planned": "el sustrato o los almácigos donde se va a sembrar",
    "seedbed": "los plantines: hojas nuevas y color",
    "planted": "los brotes y las hojas nuevas",
    "growing": "los brotes y las hojas nuevas, de cerca",
    "harvesting": "lo que se cosecha (frutos, hojas o raíces), de cerca",
}


def followup_order(followup: FollowUpRead) -> tuple:
    return (_SEVERITY_RANK.get(followup.severity, 9), followup.last_photo_at or _EPOCH)


def followup_step(followup: FollowUpRead) -> CaptureStep:
    lot_id = followup.lot_ids[0] if len(followup.lot_ids) == 1 else None
    return CaptureStep(
        role="seguimiento", required=True, hint=followup.photo_hint or f"de cerca, donde se vio: {followup.title}",
        lot_id=lot_id, followup_id=followup.id, title=followup.title, severity=followup.severity,
        since=followup.created_at, previous_photo=followup.last_photo, previous_at=followup.last_photo_at,
    )


def zone_capture(
    zone: FieldZoneRead, lots: list[ActiveLotSummary], followups: Iterable[FollowUpRead],
    max_photos: int = MAX_ZONE_PHOTOS,
) -> CaptureZone:
    crops = [CaptureCrop(lot_id=lot.id, name=lot.crop_name, status=lot.status) for lot in lots]
    names = ", ".join(dict.fromkeys(c.name for c in crops))
    steps = [CaptureStep(role="general", required=True, hint=f"La zona entera, desde un extremo ({names})")]
    queued = sorted(followups, key=followup_order)
    taken = queued[: max_photos - 1]
    steps += [followup_step(f) for f in taken]
    if len(steps) < max_photos and lots:
        followed = {lot_id for f in taken for lot_id in f.lot_ids}
        lot = next((lot for lot in lots if lot.id not in followed), lots[0])
        what = _DETAIL_HINTS.get(lot.status, "los brotes y las hojas nuevas")
        steps.append(CaptureStep(role="detalle", required=False, hint=f"Acercate al {lot.crop_name}: {what}",
                                 lot_id=lot.id))
    return CaptureZone(
        zone_id=zone.id, label=zone.label, crops=crops, steps=steps, deferred_followups=len(queued) - len(taken)
    )


def capture_plan(
    field_id, zones: list[FieldZoneRead], lots: list[ActiveLotSummary], followups: list[FollowUpRead],
) -> CapturePlan:
    """Zones in their own order (type, then number: how they're numbered on the ground), only those with an
    active crop — the upload refuses the others."""
    plan = []
    for zone in zones:
        in_zone = [lot for lot in lots if zone.id in (lot.zone_ids or [lot.zone_id])]
        if not in_zone:
            continue
        plan.append(zone_capture(zone, in_zone, [f for f in followups if f.zone_id == zone.id]))
    return CapturePlan(field_id=field_id, max_photos=MAX_ZONE_PHOTOS, zones=plan)
