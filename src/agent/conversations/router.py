"""
Chat with the agent and manage conversations (each user has many private conversations).
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

import json

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from src.application.changes.schemas import ProposalDecision, ProposalRead
from src.application.changes.service import ChangeSetService
from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor

from ..runner import AgentRunner
from ..schemas import ChatResponse
from .schemas import ConversationCreate, ConversationRead, ConversationUpdate, MessageRead
from .service import ConversationService

router = APIRouter(prefix="/chat", tags=["Chat"])

RUNNER = Provide["agent.runner"]
CONVERSATIONS = Provide["agent.conversation_service"]
CHANGES = Provide["application.change_set_service"]


class ChatContext(BaseModel):
    field_id: Optional[UUID] = None
    report_id: Optional[UUID] = None


class ChatRequest(BaseModel):
    message: str = Field("", max_length=4000, description="May be empty when an audio carries the message")
    conversation_id: Optional[UUID] = None
    image_identifier: Optional[str] = Field(None, description="From POST /upload/image")
    audio_identifier: Optional[str] = Field(
        None, description="From POST /upload/audio: transcribed into the message and kept as evidence"
    )
    context: ChatContext = Field(default_factory=ChatContext)
    retry_message_id: Optional[UUID] = Field(
        None, description="Resend this failed user message (the last one of the conversation) instead of `message`"
    )

    @model_validator(mode="after")
    def _something_to_say(self):
        if not (self.message.strip() or self.audio_identifier or self.retry_message_id):
            raise ValueError("Send a message, an audio or a retry_message_id.")
        return self


@router.post("", response_model=ChatResponse, summary="Send a message to the agent")
@inject
async def chat(body: ChatRequest, actor: Actor = Depends(get_actor), runner: AgentRunner = Depends(RUNNER)):
    """Without conversation_id a new conversation is created; its id comes back in metadata.conversation_id."""
    return await runner.chat(
        actor,
        body.message,
        conversation_id=body.conversation_id,
        field_id=body.context.field_id,
        image_identifier=body.image_identifier,
        audio_identifier=body.audio_identifier,
        report_id=body.context.report_id,
        retry_message_id=body.retry_message_id,
    )


@router.post("/stream", summary="Send a message and stream the answer (Server-Sent Events)")
@inject
async def chat_stream(body: ChatRequest, actor: Actor = Depends(get_actor), runner: AgentRunner = Depends(RUNNER)):
    """SSE events: `meta` {conversation_id}, `tool_call` {name, args}, `tool_result` {name, ok},
    `delta` {text}, `done` (same body as POST /chat), `error` {detail, error_code}.
    Missing/invalid key and unknown conversation are returned as normal HTTP errors before streaming.
    The user's message is saved before the answer starts, and the answer keeps running (and is saved)
    if the client disconnects: reopening the conversation shows it as `pending` until it's done.
    Stop it on purpose with POST /chat/conversations/{id}/stop."""
    turn = await runner.prepare_turn(
        actor,
        body.message,
        conversation_id=body.conversation_id,
        field_id=body.context.field_id,
        image_identifier=body.image_identifier,
        audio_identifier=body.audio_identifier,
        report_id=body.context.report_id,
        retry_message_id=body.retry_message_id,
    )

    relay = runner.start_stream(turn)  # started now, not when the body is first read

    async def events():
        async for event in relay:
            yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations", response_model=List[ConversationRead], summary="List my conversations")
@inject
async def list_conversations(
    include_archived: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    actor: Actor = Depends(get_actor),
    conversations: ConversationService = Depends(CONVERSATIONS),
):
    return await conversations.list_for_user(actor, include_archived=include_archived, limit=limit, offset=offset)


@router.post(
    "/conversations", response_model=ConversationRead, status_code=status.HTTP_201_CREATED,
    summary="Start a conversation",
)
@inject
async def create_conversation(
    body: ConversationCreate,
    actor: Actor = Depends(get_actor),
    conversations: ConversationService = Depends(CONVERSATIONS),
):
    return await conversations.create(actor, body)


@router.get("/conversations/{conversation_id}", response_model=ConversationRead, summary="Get a conversation")
@inject
async def get_conversation(
    conversation_id: UUID,
    actor: Actor = Depends(get_actor),
    conversations: ConversationService = Depends(CONVERSATIONS),
):
    return await conversations.get(actor, conversation_id)


@router.patch("/conversations/{conversation_id}", response_model=ConversationRead, summary="Rename / archive")
@inject
async def update_conversation(
    conversation_id: UUID,
    body: ConversationUpdate,
    actor: Actor = Depends(get_actor),
    conversations: ConversationService = Depends(CONVERSATIONS),
):
    return await conversations.update(actor, conversation_id, body)


@router.delete(
    "/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a conversation"
)
@inject
async def delete_conversation(
    conversation_id: UUID,
    actor: Actor = Depends(get_actor),
    conversations: ConversationService = Depends(CONVERSATIONS),
):
    await conversations.delete(actor, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/conversations/{conversation_id}/messages", response_model=List[MessageRead], summary="Conversation history"
)
@inject
async def conversation_messages(
    conversation_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    before: Optional[datetime] = None,
    actor: Actor = Depends(get_actor),
    conversations: ConversationService = Depends(CONVERSATIONS),
    runner: AgentRunner = Depends(RUNNER),
):
    """An answer still being generated comes back with status `pending` (poll until it changes)."""
    return await conversations.messages(
        actor, conversation_id, limit=limit, before=before, running=runner.is_running(conversation_id)
    )


@router.post(
    "/conversations/{conversation_id}/stop", status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop the answer being generated",
)
@inject
async def stop_turn(
    conversation_id: UUID,
    actor: Actor = Depends(get_actor),
    runner: AgentRunner = Depends(RUNNER),
):
    """What was generated so far is kept. No-op if nothing is running."""
    await runner.stop_turn(actor, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/memory", status_code=status.HTTP_204_NO_CONTENT, deprecated=True,
    summary="Deprecated: use DELETE /chat/conversations/{id}",
)
@inject
async def clear_memory(
    conversation_id: UUID,
    actor: Actor = Depends(get_actor),
    conversations: ConversationService = Depends(CONVERSATIONS),
):
    await conversations.delete(actor, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- proposals: writes the agent prepared, applied or rejected by the user ----------

@router.get("/proposals/{proposal_id}", response_model=ProposalRead, summary="A change proposal with its preview")
@inject
async def get_proposal(
    proposal_id: UUID, actor: Actor = Depends(get_actor), changes: ChangeSetService = Depends(CHANGES)
):
    return await changes.get_proposal(actor, proposal_id)


async def _decide(actor: Actor, proposal_id: UUID, apply: bool, excluded, changes, conversations) -> ProposalRead:
    proposal = await changes.decide(actor, proposal_id, apply=apply, excluded=excluded)
    if proposal.conversation_id:
        await conversations.add_note(actor, proposal.conversation_id, changes.note(proposal))
    return proposal


@router.post("/proposals/{proposal_id}/apply", response_model=ProposalRead, summary="Apply a proposal")
@inject
async def apply_proposal(
    proposal_id: UUID,
    body: ProposalDecision,
    actor: Actor = Depends(get_actor),
    changes: ChangeSetService = Depends(CHANGES),
    conversations: ConversationService = Depends(CONVERSATIONS),
):
    """`excluded`: the indexes the user unticked. The conversation gets a line saying what was applied."""
    return await _decide(actor, proposal_id, True, body.excluded, changes, conversations)


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalRead, summary="Reject a proposal")
@inject
async def reject_proposal(
    proposal_id: UUID,
    actor: Actor = Depends(get_actor),
    changes: ChangeSetService = Depends(CHANGES),
    conversations: ConversationService = Depends(CONVERSATIONS),
):
    return await _decide(actor, proposal_id, False, [], changes, conversations)
