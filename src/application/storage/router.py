# src/ingestion/reception/api/upload_router.py
"""
File upload reception endpoints.
"""
from typing import List, Optional
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel

from src.agent.reasoning.diagnosis_service import analyze_in_background
from src.application.farm.models import ACTIVE_LOT_STATUSES
from src.application.reports.schemas import ReportCreate
from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor
from src.shared.utils import get_logger
from src.shared.utils.errors import InvalidInputError

from .images import ImageTooLargeError, read_upload, shrink_to_jpeg

logger = get_logger(__name__)

router = APIRouter(prefix="/upload", tags=["Uploads"])


# Response schema
class UploadImageResponse(BaseModel):
    """Response schema for image upload."""
    report_id: UUID
    image_identifier: str
    status: str
    message: str


# Image validation constants (size and pixel limits: see images.py)
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/jpg", "image/webp"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def validate_image_type(image_bytes: bytes, content_type: str, filename: str) -> None:
    """
    Validate image type using content-type and magic bytes.
    
    Raises:
        InvalidInputError: If image type is not supported
    """
    # Check content type
    if content_type and content_type.lower() not in ALLOWED_CONTENT_TYPES:
        raise InvalidInputError(
            f"Unsupported content type: {content_type}. Allowed: {ALLOWED_CONTENT_TYPES}"
        )
    
    # Check file extension
    if filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext and ext not in ALLOWED_EXTENSIONS:
            raise InvalidInputError(
                f"Unsupported file extension: {ext}. Allowed: {ALLOWED_EXTENSIONS}"
            )
    
    # Check magic bytes
    if len(image_bytes) < 8:
        raise InvalidInputError("Image file is too small to be valid")
    
    # JPEG magic bytes: FF D8 FF
    # PNG magic bytes: 89 50 4E 47 0D 0A 1A 0A
    # WEBP: RIFF <4-byte size> WEBP
    is_jpeg = image_bytes[:3] == b'\xff\xd8\xff'
    is_png = image_bytes[:8] == b'\x89PNG\r\n\x1a\n'
    is_webp = len(image_bytes) >= 12 and image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP'

    if not (is_jpeg or is_png or is_webp):
        raise InvalidInputError(
            "Invalid image format. Only JPEG, PNG and WEBP are supported."
        )


async def receive_photo(image_file: UploadFile) -> bytes:
    """Read an uploaded photo (size-capped), check it is a JPEG/PNG/WEBP, and return it normalized: at most
    1536 px per side, JPEG, no metadata. Raises HTTP 413/415 with a message the app can show."""
    try:
        raw = await read_upload(image_file)
    except ImageTooLargeError as e:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=e.message) from None
    try:
        validate_image_type(raw, image_file.content_type, image_file.filename)
    except InvalidInputError as e:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=e.message) from None
    try:
        return await shrink_to_jpeg(raw)
    except ImageTooLargeError as e:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=e.message) from None
    except InvalidInputError as e:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=e.message) from None


def stored_name(filename: Optional[str]) -> str:
    """The upload's name with the .jpg extension it has after normalization."""
    base = (filename or "image").rsplit(".", 1)[0] or "image"
    return f"{base}.jpg"


@router.post(
    "/image",
    response_model=UploadImageResponse,
    summary="Upload Crop Image",
    description="Upload a JPEG/PNG/WEBP image and create a pending report. Use the returned image_identifier "
    "in /chat or /analyze.",
)
@inject
async def upload_crop_image(
    background_tasks: BackgroundTasks,
    image_file: UploadFile = File(..., description="Image file of the crop (JPEG, PNG or WEBP)."),
    field_id: Optional[UUID] = Form(None),
    lot_id: Optional[UUID] = Form(None),
    report_type: str = Form("diagnosis"),
    notes: Optional[str] = Form(None, max_length=2000, description="The user's own observations, if any"),
    reason: Optional[str] = Form(None, max_length=500, description='Why the photo was taken ("motivo")'),
    actor: Actor = Depends(get_actor),
    storage_service=Depends(Provide["application.storage_service"]),
    reports_service=Depends(Provide["application.reports_service"]),
    diagnosis_service=Depends(Provide["agent.diagnosis_service"]),
):
    if report_type not in ("diagnosis", "periodic", "soil"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="report_type must be 'diagnosis', 'periodic' or 'soil'."
        )
    if report_type == "periodic" and lot_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="lot_id is required for a periodic (tracking) report.",
        )

    image_data = await receive_photo(image_file)
    image_identifier = await storage_service.save_image(
        actor, stored_name(image_file.filename), image_data, "image/jpeg"
    )
    report = await reports_service.create_report(
        actor,
        ReportCreate(
            image_identifier=image_identifier, field_id=field_id, lot_id=lot_id,
            report_type=report_type, notes=(notes or "").strip() or None, reason=(reason or "").strip() or None,
        ),
    )
    logger.info(f"Image {image_identifier} uploaded for account {actor.account_id}")
    if report_type in ("periodic", "soil"):
        background_tasks.add_task(analyze_in_background, diagnosis_service, actor, report.id)
    return UploadImageResponse(
        report_id=report.id,
        image_identifier=image_identifier,
        status=report.status,
        message="Image uploaded and initial report created successfully.",
    )


MAX_ZONE_PHOTOS = 4


@router.post(
    "/zone-tracking",
    response_model=UploadImageResponse,
    summary="Daily tracking of a zone (1-4 photos)",
    description="Upload 1-4 photos of a cajón / cantero / invernadero / hidroponía and create one periodic report "
    "covering every active crop of the zone. It is analyzed in the background (poll GET /reports/{report_id}).",
)
@inject
async def upload_zone_tracking(
    background_tasks: BackgroundTasks,
    zone_id: UUID = Form(...),
    image_files: List[UploadFile] = File(..., description="1-4 photos of the zone"),
    notes: Optional[str] = Form(None, max_length=2000, description="The user's own observations, if any"),
    reason: Optional[str] = Form(None, max_length=500, description='Why the photo was taken ("motivo")'),
    actor: Actor = Depends(get_actor),
    farm_service=Depends(Provide["application.farm_service"]),
    storage_service=Depends(Provide["application.storage_service"]),
    reports_service=Depends(Provide["application.reports_service"]),
    diagnosis_service=Depends(Provide["agent.diagnosis_service"]),
):
    if not 1 <= len(image_files) <= MAX_ZONE_PHOTOS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Send between 1 and {MAX_ZONE_PHOTOS} photos."
        )
    zone = await farm_service.get_zone(actor, zone_id)
    cycles = [
        c for c in await farm_service.list_lots(actor, field_id=zone.field_id, zone_id=zone.id)
        if c.status in ACTIVE_LOT_STATUSES
    ]
    if not cycles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{zone.label} has no active lots to track. Assign its crops to the zone first.",
        )
    photos = [await receive_photo(f) for f in image_files]  # validate all before storing any
    identifiers = [
        await storage_service.save_image(actor, stored_name(f.filename), data, "image/jpeg")
        for f, data in zip(image_files, photos, strict=True)
    ]
    report = await reports_service.create_report(
        actor,
        ReportCreate(
            image_identifier=identifiers[0],
            image_identifiers=identifiers,
            field_id=zone.field_id,
            zone_id=zone.id,
            lot_ids=[c.id for c in cycles],
            report_type="periodic",
            notes=(notes or "").strip() or None,
            reason=(reason or "").strip() or None,
        ),
    )
    logger.info(f"{len(identifiers)} zone photo(s) uploaded for zone {zone.id}, account {actor.account_id}")
    background_tasks.add_task(analyze_in_background, diagnosis_service, actor, report.id)
    return UploadImageResponse(
        report_id=report.id,
        image_identifier=identifiers[0],
        status=report.status,
        message="Zone photos uploaded; the tracking report is being analyzed.",
    )


@router.get("/image/{image_identifier}", summary="Download an uploaded image (same account only)")
@inject
async def get_image(
    image_identifier: str,
    max_side: Optional[int] = Query(None, ge=1, le=4096, description="A JPEG thumbnail of at most this many pixels"),
    actor: Actor = Depends(get_actor),
    storage_service=Depends(Provide["application.storage_service"]),
):
    """Without `max_side`, the stored image as it is. With it, a cached JPEG thumbnail (32 to 1536 px)."""
    if max_side is not None:
        data, content_type = await storage_service.get_thumbnail(actor, image_identifier, max_side)
        return Response(
            content=data, media_type=content_type,
            headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"},
        )
    data, metadata = await storage_service.get_image_data(actor, image_identifier)
    return Response(
        content=data,
        media_type=metadata.get("content_type") or "image/jpeg",
        headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"},
    )


# ---------- voice messages ----------

MAX_AUDIO_BYTES = 15 * 1024 * 1024  # ~10 minutes of compressed speech; a voice note is usually under a minute
AUDIO_TYPES = {
    "audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/m4a": "m4a",
    "audio/aac": "aac", "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav",
}


class UploadAudioResponse(BaseModel):
    audio_identifier: str
    content_type: str
    size: int


def _audio_kind(data: bytes) -> Optional[str]:
    """The container by its magic bytes: what the browsers' MediaRecorder and phones actually produce."""
    if data[:4] == b"\x1aE\xdf\xa3":
        return "webm"
    if data[:4] == b"OggS":
        return "ogg"
    if data[4:8] == b"ftyp":
        return "m4a"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "mp3"
    return None


@router.post("/audio", response_model=UploadAudioResponse, summary="Upload a voice message",
             description="A recorded voice note (webm/ogg/m4a/mp3/wav, up to 15 MB). Send its audio_identifier in "
             "/chat: it is transcribed and kept as evidence of what was said.")
@inject
async def upload_audio(
    audio_file: UploadFile = File(..., description="The recording"),
    actor: Actor = Depends(get_actor),
    storage_service=Depends(Provide["application.storage_service"]),
):
    data = await audio_file.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="The audio is too long (15 MB max).")
    declared = (audio_file.content_type or "").split(";")[0].strip().lower()
    kind = _audio_kind(data) if len(data) >= 12 else None
    if kind is None:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            detail="Unsupported audio. Use webm, ogg, m4a, mp3 or wav.")
    content_type = declared if AUDIO_TYPES.get(declared) == kind else next(
        t for t, k in AUDIO_TYPES.items() if k == kind
    )
    identifier = await storage_service.save_audio(actor, f"voice.{kind}", data, content_type)
    return UploadAudioResponse(audio_identifier=identifier, content_type=content_type, size=len(data))


@router.get("/audio/{audio_identifier}", summary="Play a voice message (same account only)")
@inject
async def get_audio(
    audio_identifier: str,
    actor: Actor = Depends(get_actor),
    storage_service=Depends(Provide["application.storage_service"]),
):
    data, content_type = await storage_service.get_audio(actor, audio_identifier)
    return Response(content=data, media_type=content_type,
                    headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})
