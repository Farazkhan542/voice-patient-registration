"""Patient service layer.

The single place that reads and writes patient rows. The REST routes and the
voice-agent tools both call these functions, so a record created over the phone
goes through exactly the same code path as POST /patients.
"""

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Patient, utcnow
from app.schemas import PatientCreate, PatientUpdate


def create_patient(session: Session, data: PatientCreate) -> Patient:
    patient = Patient(**data.model_dump())
    session.add(patient)
    session.commit()
    return patient


def get_patient(session: Session, patient_id: uuid.UUID) -> Patient | None:
    patient = session.get(Patient, patient_id)
    if patient is None or patient.deleted_at is not None:
        return None
    return patient


def list_patients(
    session: Session,
    last_name: str | None = None,
    date_of_birth: date | None = None,
    phone_number: str | None = None,
) -> list[Patient]:
    query = select(Patient).where(Patient.deleted_at.is_(None))
    if last_name:
        query = query.where(func.lower(Patient.last_name) == last_name.strip().lower())
    if date_of_birth:
        query = query.where(Patient.date_of_birth == date_of_birth)
    if phone_number:
        query = query.where(Patient.phone_number == phone_number)
    return list(session.scalars(query.order_by(Patient.created_at.desc())))


def update_patient(session: Session, patient: Patient, data: PatientUpdate) -> Patient:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(patient, field, value)
    session.commit()
    return patient


def soft_delete_patient(session: Session, patient: Patient) -> Patient:
    patient.deleted_at = utcnow()
    session.commit()
    return patient
