"""REST API for patient records. Every response uses the { data, error } envelope."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import validation
from app.db import get_session
from app.errors import ApiError, ok
from app.models import Patient
from app.schemas import AppointmentOut, CallLogOut, PatientCreate, PatientOut, PatientUpdate
from app.services import appointments as appointment_service
from app.services import calls as call_service
from app.services import patients as patient_service

router = APIRouter(prefix="/patients", tags=["patients"])


def _serialize(patient: Patient) -> dict:
    return PatientOut.model_validate(patient).model_dump(mode="json")


def _load(session: Session, patient_id: str) -> Patient:
    try:
        parsed = uuid.UUID(patient_id)
    except ValueError:
        raise ApiError(400, "invalid_id", "patient_id must be a valid UUID")
    patient = patient_service.get_patient(session, parsed)
    if patient is None:
        raise ApiError(404, "not_found", "Patient not found")
    return patient


def _query_filter(field: str, value: str | None, normalize):
    if value is None:
        return None
    try:
        return normalize(value)
    except ValueError as exc:
        raise ApiError(422, "validation_error", "Invalid query parameter",
                       [{"field": field, "message": str(exc)}])


@router.get("")
def list_patients(
    last_name: str | None = None,
    date_of_birth: str | None = None,
    phone_number: str | None = None,
    session: Session = Depends(get_session),
):
    patients = patient_service.list_patients(
        session,
        last_name=last_name,
        date_of_birth=_query_filter("date_of_birth", date_of_birth, validation.parse_date_of_birth),
        phone_number=_query_filter("phone_number", phone_number, validation.normalize_phone),
    )
    return ok([_serialize(p) for p in patients])


@router.get("/{patient_id}")
def get_patient(patient_id: str, session: Session = Depends(get_session)):
    return ok(_serialize(_load(session, patient_id)))


@router.post("", status_code=201)
def create_patient(body: PatientCreate, session: Session = Depends(get_session)):
    return ok(_serialize(patient_service.create_patient(session, body)))


@router.put("/{patient_id}")
def update_patient(patient_id: str, body: PatientUpdate, session: Session = Depends(get_session)):
    patient = _load(session, patient_id)
    return ok(_serialize(patient_service.update_patient(session, patient, body)))


@router.delete("/{patient_id}")
def delete_patient(patient_id: str, session: Session = Depends(get_session)):
    patient = _load(session, patient_id)
    return ok(_serialize(patient_service.soft_delete_patient(session, patient)))


@router.get("/{patient_id}/appointments")
def list_patient_appointments(patient_id: str, session: Session = Depends(get_session)):
    patient = _load(session, patient_id)
    appointments = appointment_service.list_appointments(session, patient.patient_id)
    return ok([AppointmentOut.model_validate(a).model_dump(mode="json") for a in appointments])


@router.get("/{patient_id}/calls")
def list_patient_calls(patient_id: str, session: Session = Depends(get_session)):
    patient = _load(session, patient_id)
    logs = call_service.list_calls(session, patient_id=patient.patient_id)
    return ok([CallLogOut.model_validate(log).model_dump(mode="json") for log in logs])
