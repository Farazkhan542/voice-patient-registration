"""Actions the voice agent can take against patient records.

Framework-free on purpose: these functions know nothing about the LLM SDK or the
telephony provider. Each returns a small dict with a "status" that the prompt
teaches the model to act on. They never raise: a failure becomes
{"status": "error"} so the agent can tell the caller what happened.
"""

import logging
import uuid

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app import validation
from app.db import SessionLocal
from app.errors import validation_details
from app.schemas import PATIENT_FIELDS, PatientCreate, PatientUpdate
from app.services import appointments as appointment_service
from app.services import calls as call_service
from app.services import patients as patient_service

logger = logging.getLogger("voice_agent")


def _validation_failure(exc: ValidationError) -> dict:
    errors = [{"field": e["field"], "problem": e["message"]} for e in validation_details(exc)]
    return {"status": "validation_error", "errors": errors}


def _patient_fields(arguments: dict) -> dict:
    """Keep known patient fields the model actually filled in (blank means "not given")."""
    return {
        key: value for key, value in arguments.items()
        if key in PATIENT_FIELDS and not validation.is_blank(value)
    }


NEEDS_CONFIRMATION = {
    "status": "needs_confirmation",
    "message": (
        "The values are valid but nothing has been saved yet. Read them back to the "
        "caller and ask if everything is correct. After the caller clearly says yes, "
        "call this tool again with the same values to save."
    ),
}


def _lookup_patient(session: Session, arguments: dict, **_) -> dict:
    try:
        phone = validation.normalize_phone(arguments.get("phone_number", ""))
    except ValueError as exc:
        return {"status": "validation_error",
                "errors": [{"field": "phone_number", "problem": str(exc)}]}
    matches = patient_service.list_patients(session, phone_number=phone)
    if not matches:
        return {"status": "not_found"}
    return {
        "status": "found",
        "patients": [
            {
                "patient_id": str(p.patient_id),
                "first_name": p.first_name,
                "last_name": p.last_name,
                "date_of_birth": p.date_of_birth.strftime("%m/%d/%Y"),
            }
            for p in matches
        ],
    }


def _save_patient(session: Session, arguments: dict, call_id: str | None,
                  caller_number: str | None, dry_run: bool = False) -> dict:
    try:
        data = PatientCreate(**_patient_fields(arguments))
    except ValidationError as exc:
        return _validation_failure(exc)
    if dry_run:
        return NEEDS_CONFIRMATION
    patient = patient_service.create_patient(session, data)
    logger.info("patient_saved call_id=%s payload=%s", call_id, data.model_dump_json())
    if call_id:
        call_service.link_call_to_patient(session, call_id, patient.patient_id, caller_number)
    return {"status": "saved", "patient_id": str(patient.patient_id),
            "first_name": patient.first_name}


def _update_patient(session: Session, arguments: dict, call_id: str | None,
                    caller_number: str | None, dry_run: bool = False) -> dict:
    try:
        patient_id = uuid.UUID(str(arguments.get("patient_id", "")))
    except ValueError:
        return {"status": "error", "message": "Unknown patient_id. Call lookup_patient first."}
    patient = patient_service.get_patient(session, patient_id)
    if patient is None:
        return {"status": "error", "message": "No patient exists with that patient_id."}
    try:
        data = PatientUpdate(**_patient_fields(arguments))
    except ValidationError as exc:
        return _validation_failure(exc)
    if dry_run:
        return NEEDS_CONFIRMATION
    patient = patient_service.update_patient(session, patient, data)
    logger.info("patient_updated call_id=%s patient_id=%s payload=%s",
                call_id, patient_id, data.model_dump_json(exclude_unset=True))
    if call_id:
        call_service.link_call_to_patient(session, call_id, patient.patient_id, caller_number)
    return {"status": "updated", "patient_id": str(patient.patient_id),
            "first_name": patient.first_name}


def _get_appointment_slots(session: Session, arguments: dict, **_) -> dict:
    slots = appointment_service.available_slots(session)
    if not slots:
        return {"status": "no_slots"}
    return {
        "status": "ok",
        "provider": appointment_service.PROVIDER,
        "slots": [
            {"slot": s.strftime(appointment_service.SLOT_FORMAT),
             "spoken": appointment_service.describe(s)}
            for s in slots
        ],
    }


def _book_appointment(session: Session, arguments: dict, call_id: str | None, **_) -> dict:
    try:
        patient_id = uuid.UUID(str(arguments.get("patient_id", "")))
    except ValueError:
        return {"status": "error", "message": "Unknown patient_id."}
    if patient_service.get_patient(session, patient_id) is None:
        return {"status": "error", "message": "No patient exists with that patient_id."}
    appointment = appointment_service.book_appointment(
        session, patient_id, str(arguments.get("slot", ""))
    )
    if appointment is None:
        return {"status": "slot_unavailable",
                "message": "That slot is not open. Call get_appointment_slots and offer another."}
    logger.info("appointment_booked call_id=%s patient_id=%s starts_at=%s",
                call_id, patient_id, appointment.starts_at)
    return {"status": "booked", "provider": appointment.provider,
            "spoken": appointment_service.describe(appointment.starts_at)}


_HANDLERS = {
    "get_appointment_slots": _get_appointment_slots,
    "book_appointment": _book_appointment,
    "lookup_patient": _lookup_patient,
    "save_patient": _save_patient,
    "update_patient": _update_patient,
}


def run_tool(name: str, arguments: dict, call_id: str | None = None,
             caller_number: str | None = None, dry_run: bool = False) -> dict:
    """Run one agent action in its own database session and log it.

    With dry_run, save/update only validate and return needs_confirmation."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"status": "error", "message": f"Unknown tool: {name}"}
    logger.info("tool_call call_id=%s tool=%s dry_run=%s args=%s", call_id, name, dry_run, arguments)
    extra = {"dry_run": True} if dry_run else {}
    with SessionLocal() as session:
        try:
            result = handler(session, arguments, call_id=call_id,
                             caller_number=caller_number, **extra)
        except Exception:
            # e.g. the database is down. Roll back and tell the agent so it can apologise.
            session.rollback()
            logger.exception("tool_failed call_id=%s tool=%s", call_id, name)
            result = {"status": "error",
                      "message": "The record could not be saved because of a system problem."}
    logger.info("tool_result call_id=%s tool=%s result=%s", call_id, name, result)
    return result
