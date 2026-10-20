"""Change sets over the API: preview several writes, then apply them in order (one call, many entities)."""
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends

from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor

from .schemas import ChangeSet, ChangeSetPreview, ChangeSetResult
from .service import ChangeSetService

router = APIRouter(prefix="/changes", tags=["Changes"])
CHANGES = Provide["application.change_set_service"]


@router.post("/preview", response_model=ChangeSetPreview, summary="Check and describe a change set (writes nothing)")
@inject
async def preview(body: ChangeSet, actor: Actor = Depends(get_actor), changes: ChangeSetService = Depends(CHANGES)):
    return await changes.preview(actor, body.operations)


@router.post("", response_model=ChangeSetResult, summary="Apply a change set, in order")
@inject
async def apply(body: ChangeSet, actor: Actor = Depends(get_actor), changes: ChangeSetService = Depends(CHANGES)):
    """Operations: `{op: create|update|delete, entity, id?, data}`; "$N" refers to what operation N created. If one
    fails, what the set created is removed again and the rest is skipped."""
    return await changes.apply(actor, body.operations, set(body.excluded))
