"""
Which photos of a zone-tracking report each pass of the fanned-out analysis gets (see diagnosis_service.py).

Every pass is its own Gemini call, and photos are most of a call's size: handing every photo to every pass
(overview + one call per crop group + rechecks) multiplies them. With `photo_roles` the user said what each
photo shows, so the overview gets the general shots and a crop group only the general shots plus its own
close-ups — each one labeled, so the model knows which is which. A report without roles (older clients,
the manual upload) keeps the old behavior: every pass sees every photo, unlabeled.
"""
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from src.application.reports.schemas import PhotoRole


@dataclass(frozen=True)
class ZonePhoto:
    number: int  # 1-based, in upload order: what the labels and the model's answer refer to
    part: Any  # the model-ready image (types.Part)
    role: Optional[PhotoRole] = None


def zone_photos(parts: list, roles: list[PhotoRole]) -> list[ZonePhoto]:
    """Pair each photo with its role. Roles that don't line up one-to-one with the photos are ignored."""
    usable = roles if len(roles) == len(parts) else []
    return [ZonePhoto(i + 1, part, usable[i] if usable else None) for i, part in enumerate(parts)]


def _labeled(photos: Iterable[ZonePhoto], crop_by_cycle: dict[str, str]) -> list:
    out: list = []
    for photo in photos:
        if photo.role is not None:
            out.append(photo_label(photo, crop_by_cycle))
        out.append(photo.part)
    return out


def photo_label(photo: ZonePhoto, crop_by_cycle: dict[str, str]) -> str:
    role = photo.role
    if role.role == "general":
        text = f"Foto {photo.number}: vista general de la zona"
    else:
        what = "primer plano" if role.role == "detalle" else "foto de seguimiento de algo ya visto"
        text = f"Foto {photo.number}: {what}"
        if role.lot_id:
            text += f" de {crop_by_cycle.get(str(role.lot_id), 'un cultivo')} (lot_id={role.lot_id})"
    if role.hint:
        text += f" — se pidió: {role.hint}"
    return text + "."


def overview_parts(photos: list[ZonePhoto], crop_by_cycle: dict[str, str]) -> list:
    """The general shots; every photo when there are no roles or none of them is a general shot."""
    general = [p for p in photos if p.role is not None and p.role.role == "general"]
    return _labeled(general or photos, crop_by_cycle)


def group_parts(photos: list[ZonePhoto], cycle_ids: Iterable[str], crop_by_cycle: dict[str, str]) -> list:
    """The general shots plus the close-ups of this group's lots (or of the zone as a whole). A photo of a
    follow-up goes to the follow-up pass instead (see followup_photos). Without roles, every photo."""
    if not any(p.role is not None for p in photos):
        return [p.part for p in photos]
    own = {str(c) for c in cycle_ids}
    chosen = [
        p for p in photos
        if p.role.followup_id is None
        and (p.role.role == "general" or p.role.lot_id is None or str(p.role.lot_id) in own)
    ]
    return _labeled(chosen or photos, crop_by_cycle)


def followup_photos(photos: list[ZonePhoto]) -> dict[str, list[ZonePhoto]]:
    """The photos taken to follow a problem, by follow-up id."""
    out: dict[str, list[ZonePhoto]] = {}
    for p in photos:
        if p.role is not None and p.role.followup_id is not None:
            out.setdefault(str(p.role.followup_id), []).append(p)
    return out


def photo_count(parts: list) -> int:
    return sum(1 for p in parts if not isinstance(p, str))
