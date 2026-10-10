"""Vapi integration: the only module that knows the telephony provider's wire format.

Two endpoints:
  * POST /vapi/llm/{token}/chat/completions - Vapi's "custom LLM" hook. Vapi sends
    each caller utterance here in OpenAI chat-completions format and speaks
    whatever we stream back.
  * POST /vapi/webhook - end-of-call report; we store the transcript and summary.

The LLM endpoint always answers with something speakable, even when the model
fails, so the caller never gets dead air.
"""

import hmac
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Body, Depends, Header
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.agent.agent import CallContext, forget_call, stream_reply
from app.config import settings
from app.db import get_session
from app.errors import ApiError
from app.services import calls as call_service

logger = logging.getLogger("voice_agent")
router = APIRouter(prefix="/vapi", tags=["vapi"])

FALLBACK_REPLY = "I'm sorry, I'm having a little trouble on my end. Could you say that again?"


def _verify_secret(provided: str | None) -> None:
    expected = settings.vapi_webhook_secret
    if not expected or not hmac.compare_digest(provided or "", expected):
        raise ApiError(401, "unauthorized", "Invalid or missing secret")


def _text_of(content: object) -> str:
    """Message content is either a string or a list of {type: text, text: ...} parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def _spoken_transcript(messages: list[dict]) -> list[dict]:
    return [
        {"role": m["role"], "content": _text_of(m.get("content"))}
        for m in messages
        if m.get("role") in ("user", "assistant") and _text_of(m.get("content")).strip()
    ]


def _call_metadata(payload: dict) -> dict:
    # Vapi sends call metadata at the top level or nested under "metadata",
    # depending on the assistant's metadata send mode.
    return payload.get("call") or (payload.get("metadata") or {}).get("call") or {}


async def _safe_reply(context: CallContext, user_text: str,
                      transcript: list[dict]) -> AsyncIterator[str]:
    produced = False
    try:
        async for delta in stream_reply(context, user_text, transcript):
            produced = True
            yield delta
    except Exception:
        logger.exception("llm_failed call_id=%s", context.call_id)
        if not produced:
            yield FALLBACK_REPLY


def _chunk(completion_id: str, delta: dict, finish_reason: str | None = None) -> str:
    body = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": settings.llm_model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(body)}\n\n"


async def _sse(context: CallContext, user_text: str, transcript: list[dict]) -> AsyncIterator[str]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    yield _chunk(completion_id, {"role": "assistant", "content": ""})
    async for delta in _safe_reply(context, user_text, transcript):
        yield _chunk(completion_id, {"content": delta})
    yield _chunk(completion_id, {}, finish_reason="stop")
    yield "data: [DONE]\n\n"


@router.post("/llm/{token}/chat/completions")
@router.post("/llm/{token}")
async def chat_completions(token: str, payload: dict = Body(...)):
    _verify_secret(token)
    call = _call_metadata(payload)
    context = CallContext(
        call_id=call.get("id"),
        caller_number=(call.get("customer") or {}).get("number"),
    )
    transcript = _spoken_transcript(payload.get("messages") or [])
    user_text = next((m["content"] for m in reversed(transcript) if m["role"] == "user"), "")
    if not user_text:
        user_text = "(The caller has not said anything yet.)"

    if payload.get("stream", True):
        return StreamingResponse(_sse(context, user_text, transcript),
                                 media_type="text/event-stream")

    reply = "".join([delta async for delta in _safe_reply(context, user_text, transcript)])
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": settings.llm_model,
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": reply}}],
    }


@router.post("/webhook")
def webhook(
    payload: dict = Body(...),
    x_vapi_secret: str | None = Header(default=None),
    session: Session = Depends(get_session),
):
    _verify_secret(x_vapi_secret)
    message = payload.get("message") or {}
    if message.get("type") != "end-of-call-report":
        return {}

    call = message.get("call") or {}
    call_id = call.get("id")
    transcript = message.get("transcript") or (message.get("artifact") or {}).get("transcript")
    summary = message.get("summary") or (message.get("analysis") or {}).get("summary")
    ended_reason = message.get("endedReason")
    logger.info("call_ended call_id=%s reason=%s\n%s", call_id, ended_reason, transcript)
    if call_id:
        call_service.record_call_end(
            session,
            call_id=call_id,
            caller_number=(call.get("customer") or {}).get("number"),
            ended_reason=ended_reason,
            summary=summary,
            transcript=transcript,
        )
        forget_call(call_id)
    return {}
