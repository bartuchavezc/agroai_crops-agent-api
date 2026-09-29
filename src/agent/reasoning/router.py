from typing import Optional
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from src.application.farm.declination import magnetic_to_true_bearing
from src.application.storage.router import MAX_IMAGE_SIZE_BYTES, validate_image_size, validate_image_type
from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor
from src.shared.utils.errors import InvalidInputError

from ..tools import ToolDeps
from ..tools.layout import extract_layout_from_photo
from .diagnosis_service import DiagnosisService

router = APIRouter(prefix="/analyze", tags=["Analysis"])
layout_router = APIRouter(prefix="/farm-management", tags=["Farm Management"])


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
    "/fields/layout/extract",
    summary="Extract sun/shade layout objects (walls, trees...) from an eye-level photo",
    description="Not tied to a field or a diagnosis report: the photo is stored (so the UI can show it as a "
    "reference thumbnail) and the guessed objects are returned (bearing corrected from magnetic to true north when "
    "flagged, and calibrated by the optional free-text reference_note); the client merges them into the field's "
    "layout and saves with the normal PUT /fields/{id}.",
)
@inject
async def extract_layout(
    image_file: UploadFile = File(..., description="Photo of the surroundings (JPEG, PNG or WEBP)."),
    camera_bearing_degrees: float = Form(..., ge=0, le=360),
    bearing_is_magnetic: bool = Form(False, description="True when the bearing came from a phone compass"),
    latitude: Optional[float] = Form(None, ge=-90, le=90),
    longitude: Optional[float] = Form(None, ge=-180, le=180),
    reference_note: Optional[str] = Form(None, max_length=500),
    actor: Actor = Depends(get_actor),
    deps: ToolDeps = Depends(Provide["agent.tool_deps"]),
):
    image_data = await image_file.read()
    try:
        validate_image_size(len(image_data), MAX_IMAGE_SIZE_BYTES, image_file.filename)
    except InvalidInputError as e:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=e.message) from None
    try:
        validate_image_type(image_data, image_file.content_type, image_file.filename)
    except InvalidInputError as e:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=e.message) from None

    image_identifier = await deps.storage.save_image(actor, image_file.filename, image_data, image_file.content_type)
    true_bearing = (
        magnetic_to_true_bearing(camera_bearing_degrees, latitude, longitude)
        if bearing_is_magnetic
        else camera_bearing_degrees
    )
    objects = await extract_layout_from_photo(deps, actor, image_identifier, true_bearing, reference_note)
    return {"image_identifier": image_identifier, "camera_bearing_degrees": round(true_bearing, 1), "objects": objects}
