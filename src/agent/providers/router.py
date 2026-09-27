"""
BYOK endpoints: each user stores their own Gemini API key (free tier from Google AI Studio).
The key is never returned; only its last 4 characters.
"""
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from src.auth.api.dependencies import get_current_user
from src.auth.domain.schemas import UserRead

from .credentials_service import CredentialStatus, CredentialsService

router = APIRouter(prefix="/me/provider-credentials", tags=["Provider Credentials (BYOK)"])


class GeminiKeyRequest(BaseModel):
    api_key: str = Field(min_length=20, max_length=200)


@router.get("/gemini", response_model=CredentialStatus, summary="Gemini key status")
@inject
async def get_gemini_key_status(
    current_user: UserRead = Depends(get_current_user),
    credentials: CredentialsService = Depends(Provide["agent.credentials_service"]),
):
    return await credentials.status(current_user.id)


@router.put("/gemini", response_model=CredentialStatus, summary="Save (and validate) my Gemini API key")
@inject
async def put_gemini_key(
    body: GeminiKeyRequest,
    current_user: UserRead = Depends(get_current_user),
    credentials: CredentialsService = Depends(Provide["agent.credentials_service"]),
):
    return await credentials.set_gemini_key(current_user.id, body.api_key)


@router.delete("/gemini", status_code=status.HTTP_204_NO_CONTENT, summary="Remove my Gemini API key")
@inject
async def delete_gemini_key(
    current_user: UserRead = Depends(get_current_user),
    credentials: CredentialsService = Depends(Provide["agent.credentials_service"]),
):
    await credentials.delete_gemini_key(current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
