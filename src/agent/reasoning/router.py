from typing import Optional
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor

from .diagnosis_service import DiagnosisService

router = APIRouter(prefix="/analyze", tags=["Analysis"])


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
