"""The registration agent, built on the OpenAI Agents SDK and run on Gemini.

The SDK talks to Gemini through Google's OpenAI-compatible endpoint, so swapping
the model provider is an environment change (LLM_BASE_URL / LLM_MODEL), not a
code change.

Conversation memory: Vapi re-sends the spoken transcript on every turn, but that
transcript has no record of our tool calls (for example the patient_id returned
by lookup_patient). So the full run history, tool calls included, is kept here
per call and the newest caller utterance is appended to it each turn.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from agents import (
    Agent,
    ModelSettings,
    OpenAIChatCompletionsModel,
    RunContextWrapper,
    Runner,
    function_tool,
    set_tracing_disabled,
)
from openai import APIError, AsyncOpenAI
from openai.types.responses import ResponseTextDeltaEvent

from app.agent.prompt import FIRST_MESSAGE, SYSTEM_PROMPT
from app.agent.tools import run_tool
from app.config import settings

logger = logging.getLogger("voice_agent")

# Tracing uploads run data to OpenAI; we are not using an OpenAI key, and the
# conversations contain patient details, so it stays off.
set_tracing_disabled(True)

CLINIC_TIMEZONE = ZoneInfo("America/New_York")
MAX_AGENT_TURNS = 6


@dataclass
class CallContext:
    """Per-call facts the tools need but the model should not have to supply."""

    call_id: str | None
    caller_number: str | None = None
    # Which caller utterance of the call we are answering (set by stream_reply).
    turn: int = 0


# call_id -> full Agents SDK input history (messages + tool calls + tool results).
_histories: dict[str, list] = {}
# call_id -> patient_id created during this call. Guards against a second
# save_patient in the same call creating a duplicate record.
_saved_patients: dict[str, str] = {}


# call_id -> number of caller utterances handled so far.
_turns: dict[str, int] = {}
# call_id -> (write fingerprint, turn it was first proposed on). See _write.
_proposed_writes: dict[str, tuple[str, int]] = {}


async def _act(ctx: RunContextWrapper[CallContext], name: str, arguments: dict,
               dry_run: bool = False) -> str:
    result = await asyncio.to_thread(
        run_tool, name, arguments, ctx.context.call_id, ctx.context.caller_number, dry_run
    )
    return json.dumps(result)


async def _write(ctx: RunContextWrapper[CallContext], name: str, arguments: dict) -> str:
    """Confirmation gate for save/update.

    "Read it back and get a yes before saving" is a rule the model can break, so it
    is enforced here. The first time a set of values is submitted it is only
    validated and the tool answers needs_confirmation. The write happens when the
    identical values are submitted again on a LATER turn, which means the caller has
    spoken since the read-back. Changing any value starts the cycle again.
    """
    call_id = ctx.context.call_id
    if not call_id:
        return await _act(ctx, name, arguments)
    filled = {key: value for key, value in arguments.items() if str(value).strip()}
    fingerprint = json.dumps([name, filled], sort_keys=True).lower()
    proposed = _proposed_writes.get(call_id)
    if proposed and proposed[0] == fingerprint and proposed[1] < ctx.context.turn:
        result = await _act(ctx, name, arguments)
        if json.loads(result).get("status") in ("saved", "updated"):
            _proposed_writes.pop(call_id, None)
        return result
    result = await _act(ctx, name, arguments, dry_run=True)
    if json.loads(result).get("status") == "needs_confirmation":
        first_turn = proposed[1] if proposed and proposed[0] == fingerprint else ctx.context.turn
        _proposed_writes[call_id] = (fingerprint, first_turn)
    return result


@function_tool(strict_mode=False)
async def lookup_patient(ctx: RunContextWrapper[CallContext], phone_number: str) -> str:
    """Check whether a patient record already exists for a phone number.
    Call this once, right after the caller gives their phone number.

    Args:
        phone_number: The caller's 10-digit U.S. phone number, digits only.
    """
    return await _act(ctx, "lookup_patient", {"phone_number": phone_number})


@function_tool(strict_mode=False)
async def save_patient(
    ctx: RunContextWrapper[CallContext],
    first_name: str,
    last_name: str,
    date_of_birth: str,
    sex: Literal["Male", "Female", "Other", "Decline to Answer"],
    phone_number: str,
    address_line_1: str,
    city: str,
    state: str,
    zip_code: str,
    address_line_2: str = "",
    email: str = "",
    insurance_provider: str = "",
    insurance_member_id: str = "",
    preferred_language: str = "",
    emergency_contact_name: str = "",
    emergency_contact_phone: str = "",
) -> str:
    """Create a new patient record. The first call checks the values and answers
    needs_confirmation without saving: read everything back to the caller, and after
    they clearly say yes, call again with the same values to save.
    Leave optional fields empty if the caller did not provide them.

    Args:
        first_name: Legal first name, correctly spelled.
        last_name: Legal last name, correctly spelled.
        date_of_birth: Date of birth as MM/DD/YYYY.
        sex: Sex to record on the chart.
        phone_number: 10-digit U.S. phone number, digits only.
        address_line_1: Street address, e.g. 123 Main Street.
        city: City name.
        state: 2-letter U.S. state abbreviation, e.g. NJ.
        zip_code: 5-digit ZIP code, or ZIP+4 as 12345-6789.
        address_line_2: Apartment, suite or unit, if any.
        email: Email address, e.g. jane.doe@example.com.
        insurance_provider: Insurance company name.
        insurance_member_id: Member or subscriber ID, letters and digits only.
        preferred_language: Preferred language, e.g. English or Spanish.
        emergency_contact_name: Emergency contact's full name.
        emergency_contact_phone: Emergency contact's 10-digit U.S. phone number.
    """
    arguments = {key: value for key, value in locals().items() if key != "ctx"}
    call_id = ctx.context.call_id
    if call_id and call_id in _saved_patients:
        # Already saved once on this call: apply the new values to that record.
        return await _write(ctx, "update_patient",
                            {"patient_id": _saved_patients[call_id], **arguments})
    result = await _write(ctx, "save_patient", arguments)
    if call_id and json.loads(result).get("status") == "saved":
        _saved_patients[call_id] = json.loads(result)["patient_id"]
    return result


@function_tool(strict_mode=False)
async def update_patient(
    ctx: RunContextWrapper[CallContext],
    patient_id: str,
    first_name: str = "",
    last_name: str = "",
    date_of_birth: str = "",
    sex: str = "",
    phone_number: str = "",
    address_line_1: str = "",
    address_line_2: str = "",
    city: str = "",
    state: str = "",
    zip_code: str = "",
    email: str = "",
    insurance_provider: str = "",
    insurance_member_id: str = "",
    preferred_language: str = "",
    emergency_contact_name: str = "",
    emergency_contact_phone: str = "",
) -> str:
    """Update an existing patient record found by lookup_patient. Fill in only the
    fields that changed and leave the rest empty. The first call checks the values
    and answers needs_confirmation without saving: read the changes back, and after
    the caller clearly says yes, call again with the same values to save.

    Args:
        patient_id: The patient_id returned by lookup_patient.
        first_name: Legal first name, correctly spelled.
        last_name: Legal last name, correctly spelled.
        date_of_birth: Date of birth as MM/DD/YYYY.
        sex: One of Male, Female, Other, Decline to Answer.
        phone_number: 10-digit U.S. phone number, digits only.
        address_line_1: Street address, e.g. 123 Main Street.
        address_line_2: Apartment, suite or unit.
        city: City name.
        state: 2-letter U.S. state abbreviation, e.g. NJ.
        zip_code: 5-digit ZIP code, or ZIP+4 as 12345-6789.
        email: Email address.
        insurance_provider: Insurance company name.
        insurance_member_id: Member or subscriber ID, letters and digits only.
        preferred_language: Preferred language, e.g. English or Spanish.
        emergency_contact_name: Emergency contact's full name.
        emergency_contact_phone: Emergency contact's 10-digit U.S. phone number.
    """
    arguments = {key: value for key, value in locals().items() if key != "ctx"}
    return await _write(ctx, "update_patient", arguments)


@function_tool(strict_mode=False)
async def get_appointment_slots(ctx: RunContextWrapper[CallContext]) -> str:
    """List the open times for a first appointment. Call this only after the
    patient record has been saved and the caller says they want to book a visit."""
    return await _act(ctx, "get_appointment_slots", {})


@function_tool(strict_mode=False)
async def book_appointment(ctx: RunContextWrapper[CallContext], patient_id: str, slot: str) -> str:
    """Book a first appointment in a slot the caller chose.

    Args:
        patient_id: The patient_id returned by save_patient, update_patient or lookup_patient.
        slot: The "slot" value of the chosen option from get_appointment_slots, unchanged.
    """
    return await _act(ctx, "book_appointment", {"patient_id": patient_id, "slot": slot})


def _instructions(_ctx: RunContextWrapper[CallContext], _agent: Agent) -> str:
    today = datetime.now(CLINIC_TIMEZONE).strftime("%A, %B %d, %Y")
    return SYSTEM_PROMPT.replace("{today}", today)


_llm_client = AsyncOpenAI(
    base_url=settings.llm_base_url,
    # A placeholder keeps the app importable (tests, REST API) without a key.
    api_key=settings.llm_api_key or "missing-api-key",
    # No client-side retry backoff: on a phone call it is faster to move to the
    # next model than to wait for the same one.
    max_retries=0,
)


def _build_agent(model_name: str) -> Agent[CallContext]:
    return Agent[CallContext](
        name="Patient Registration Agent",
        instructions=_instructions,
        tools=[lookup_patient, save_patient, update_patient,
               get_appointment_slots, book_appointment],
        model=OpenAIChatCompletionsModel(model=model_name, openai_client=_llm_client),
        # Low temperature: this is data capture, not creative writing.
        model_settings=ModelSettings(temperature=0.3),
    )


# Primary model first, then fallbacks. Same prompt and tools on each.
_agents = [_build_agent(name) for name in (settings.llm_model, *settings.llm_fallback_models)]


async def stream_reply(
    context: CallContext, user_text: str, transcript: list[dict] | None = None
) -> AsyncIterator[str]:
    """Run one conversational turn and yield the agent's reply as text deltas.

    `transcript` (Vapi's own text-only history) is used only when there is no
    call id to key our richer history on.
    """
    call_id = context.call_id
    if call_id:
        context.turn = _turns[call_id] = _turns.get(call_id, 0) + 1
        history = _histories.get(call_id) or [{"role": "assistant", "content": FIRST_MESSAGE}]
        items = history + [{"role": "user", "content": user_text}]
    else:
        items = transcript or [{"role": "user", "content": user_text}]

    logger.info("turn call_id=%s caller=%r", call_id, user_text)
    spoken: list[str] = []
    completed = False
    try:
        for attempt, agent in enumerate(_agents):
            try:
                result = Runner.run_streamed(
                    agent, input=items, context=context, max_turns=MAX_AGENT_TURNS
                )
                async for event in result.stream_events():
                    if (event.type == "raw_response_event"
                            and isinstance(event.data, ResponseTextDeltaEvent)):
                        spoken.append(event.data.delta)
                        yield event.data.delta
                break
            except APIError as exc:
                # Rate limit or provider failure. Retrying from the top is safe only
                # while nothing has been spoken; a repeated save_patient is turned
                # into an update by the duplicate guard above.
                if spoken or attempt == len(_agents) - 1:
                    raise
                logger.warning("llm_fallback call_id=%s model=%s error=%s",
                               call_id, agent.model.model, type(exc).__name__)
        if call_id:
            _histories[call_id] = result.to_input_list()
        completed = True
    finally:
        logger.info("turn call_id=%s agent=%r completed=%s", call_id, "".join(spoken), completed)
        if call_id and not completed:
            # The caller interrupted (Vapi dropped the request) or the model failed.
            # Keep what was actually said so the next turn has the right context.
            partial = [{"role": "assistant", "content": "".join(spoken)}] if spoken else []
            _histories[call_id] = items + partial


def forget_call(call_id: str) -> None:
    """Drop in-memory state once a call has ended."""
    for state in (_histories, _saved_patients, _turns, _proposed_writes):
        state.pop(call_id, None)
