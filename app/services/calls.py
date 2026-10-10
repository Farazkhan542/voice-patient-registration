"""Call log service: links phone calls (and their transcripts) to patient records."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CallLog, utcnow


def _get_or_create(session: Session, call_id: str) -> CallLog:
    log = session.get(CallLog, call_id)
    if log is None:
        log = CallLog(call_id=call_id)
        session.add(log)
    return log


def link_call_to_patient(
    session: Session, call_id: str, patient_id: uuid.UUID, caller_number: str | None
) -> None:
    log = _get_or_create(session, call_id)
    log.patient_id = patient_id
    log.caller_number = caller_number or log.caller_number
    session.commit()


def record_call_end(
    session: Session,
    call_id: str,
    caller_number: str | None,
    ended_reason: str | None,
    summary: str | None,
    transcript: str | None,
) -> CallLog:
    log = _get_or_create(session, call_id)
    log.caller_number = caller_number or log.caller_number
    log.ended_reason = ended_reason
    log.summary = summary
    log.transcript = transcript
    log.ended_at = utcnow()
    session.commit()
    return log


def list_calls(
    session: Session, patient_id: uuid.UUID | None = None, limit: int = 50
) -> list[CallLog]:
    query = select(CallLog)
    if patient_id is not None:
        query = query.where(CallLog.patient_id == patient_id)
    return list(session.scalars(query.order_by(CallLog.created_at.desc()).limit(limit)))
