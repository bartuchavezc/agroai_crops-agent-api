import uuid
from typing import Optional
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Response, UploadFile, status
from pydantic import BaseModel, Field

from src.application.farm.declination import magnetic_to_true_bearing
from src.application.farm.schemas import LayoutPhoto
from src.application.storage.router import receive_photo, stored_name
from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import PermissionDeniedError

from ..tools import ToolDeps
from .diagnosis_service import DiagnosisService
from .layout_jobs import process_layout_photo

router = APIRouter(prefix="/analyze", tags=["Analysis"])
layout_router = APIRouter(prefix="/farm-management", tags=["Farm Management"])


class RetryLayoutPhotoRequest(BaseModel):
    """Measures to (re)use when reprocessing — needed for photos uploaded before the entorno's size was asked."""

    entorno_ancho_m: Optional[float] = Field(default=None, gt=0, le=500)
    entorno_largo_m: Optional[float] = Field(default=None, gt=0, le=500)
    camera_height_m: Optional[float] = Field(default=None, gt=0, le=20)


class ImageAnalysisRequest(BaseModel):
    report_id: UUID
    image_identifier: Optional[str] = None


@router.post("", summary="Diagnose a crop photo (Gemini multimodal, structured output)")
@inject
async def analyze_image(
    body: ImageAnalysisRequest,
    actor: Actor = Depends(get_actor),
    diagnosis: DiagnosisService = Depends(Provide["agent.diagnosis_service"]),
):
    return await diagnosis.analyze(actor, body.report_id, body.image_identifier)


class HarvestVerdictRequest(BaseModel):
    field_id: UUID
    crop_cycle_id: Optional[UUID] = None
    image_identifier: Optional[str] = None


@router.post("/harvest-verdict", summary="Is this field/cycle ready to harvest?")
@inject
async def harvest_verdict(
    body: HarvestVerdictRequest,
    actor: Actor = Depends(get_actor),
    diagnosis: DiagnosisService = Depends(Provide["agent.diagnosis_service"]),
):
    return await diagnosis.harvest_verdict(actor, body.field_id, body.crop_cycle_id, body.image_identifier)


@layout_router.post(
    "/fields/{field_id}/layout/photos",
    response_model=LayoutPhoto,
    summary="Upload an eye-level photo of the surroundings; objects are detected in the background",
    description="Stores the photo and the user's data and returns immediately with status 'processing'. The "
    "detected objects are merged into the field's layout when the background job ends (poll the field); a "
    "failed photo can be retried without re-uploading.",
)
@inject
async def add_layout_photo(
    field_id: UUID,
    background_tasks: BackgroundTasks,
    image_file: UploadFile = File(..., description="Photo of the surroundings (JPEG, PNG or WEBP)."),
    camera_bearing_degrees: float = Form(..., ge=0, le=360),
    bearing_is_magnetic: bool = Form(False, description="True when the bearing came from a phone compass"),
    reference_note: Optional[str] = Form(None, max_length=500),
    pitch_degrees: Optional[float] = Form(None, ge=-90, le=90, description="Phone tilt at the shot, + = looking up"),
    camera_height_m: Optional[float] = Form(None, gt=0, le=20, description="Camera height above the ground"),
    entorno_ancho_m: float = Form(..., gt=0, le=500, description="Width of the surroundings, across the photo"),
    entorno_largo_m: float = Form(
        ..., gt=0, le=500, description="Length of the surroundings: from where the photo was taken to the far wall"
    ),
    actor: Actor = Depends(get_actor),
    deps: ToolDeps = Depends(Provide["agent.tool_deps"]),
):
    if not actor.is_manager:  # checked before the photo is stored, not only when the layout is saved
        raise PermissionDeniedError("Only owner or tecnico can do this.")
    field = await deps.farm.get_field(actor, field_id)
    image_data = await receive_photo(image_file)
    image_identifier = await deps.storage.save_image(actor, stored_name(image_file.filename), image_data, "image/jpeg")
    true_bearing = (
        magnetic_to_true_bearing(camera_bearing_degrees, field.latitude, field.longitude)
        if bearing_is_magnetic
        else camera_bearing_degrees
    )
    photo = await deps.farm.add_layout_photo(
        actor,
        field_id,
        LayoutPhoto(
            id=uuid.uuid4().hex,
            image_identifier=image_identifier,
            camera_bearing_degrees=round(true_bearing, 1),
            reference_note=(reference_note or "").strip() or None,
            pitch_degrees=pitch_degrees,
            camera_height_m=camera_height_m,
            entorno_ancho_m=entorno_ancho_m,
            entorno_largo_m=entorno_largo_m,
            status="processing",
            updated_at=utcnow().isoformat(),
        ),
    )
    background_tasks.add_task(process_layout_photo, deps, actor, field_id, photo.id)
    return photo


@layout_router.post(
    "/fields/{field_id}/layout/photos/{photo_id}/retry",
    response_model=LayoutPhoto,
    summary="Retry a failed or stuck layout photo, or reprocess a finished one, without re-uploading it",
)
@inject
async def retry_layout_photo(
    field_id: UUID,
    photo_id: str,
    background_tasks: BackgroundTasks,
    body: Optional[RetryLayoutPhotoRequest] = None,
    actor: Actor = Depends(get_actor),
    deps: ToolDeps = Depends(Provide["agent.tool_deps"]),
):
    body = body or RetryLayoutPhotoRequest()
    photo = await deps.farm.restart_layout_photo(
        actor, field_id, photo_id, body.entorno_ancho_m, body.entorno_largo_m, body.camera_height_m
    )
    background_tasks.add_task(process_layout_photo, deps, actor, field_id, photo_id)
    return photo


@layout_router.delete(
    "/fields/{field_id}/layout/photos/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a layout reference photo (objects already detected from it are kept)",
)
@inject
async def delete_layout_photo(
    field_id: UUID,
    photo_id: str,
    actor: Actor = Depends(get_actor),
    deps: ToolDeps = Depends(Provide["agent.tool_deps"]),
):
    await deps.farm.remove_layout_photo(actor, field_id, photo_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
