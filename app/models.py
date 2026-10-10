"""SQLAlchemy tables. Constraints here are the last line of defence behind the API validation."""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

SEX_VALUES = ("Male", "Female", "Other", "Decline to Answer")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (
        CheckConstraint(
            "sex IN ('Male', 'Female', 'Other', 'Decline to Answer')", name="ck_patients_sex"
        ),
        CheckConstraint("length(first_name) >= 1", name="ck_patients_first_name"),
        CheckConstraint("length(last_name) >= 1", name="ck_patients_last_name"),
        CheckConstraint("length(phone_number) = 10", name="ck_patients_phone_number"),
        CheckConstraint("length(state) = 2", name="ck_patients_state"),
        CheckConstraint("length(zip_code) IN (5, 10)", name="ck_patients_zip_code"),
        CheckConstraint(
            "emergency_contact_phone IS NULL OR length(emergency_contact_phone) = 10",
            name="ck_patients_emergency_contact_phone",
        ),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    first_name: Mapped[str] = mapped_column(String(50))
    last_name: Mapped[str] = mapped_column(String(50), index=True)
    date_of_birth: Mapped[date] = mapped_column(Date)
    sex: Mapped[str] = mapped_column(String(20))
    # Not unique on purpose: family members commonly share a phone number.
    phone_number: Mapped[str] = mapped_column(String(10), index=True)
    email: Mapped[str | None] = mapped_column(String(254))
    address_line_1: Mapped[str] = mapped_column(String(200))
    address_line_2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(2))
    zip_code: Mapped[str] = mapped_column(String(10))
    insurance_provider: Mapped[str | None] = mapped_column(String(100))
    insurance_member_id: Mapped[str | None] = mapped_column(String(50))
    preferred_language: Mapped[str] = mapped_column(String(50), default="English")
    emergency_contact_name: Mapped[str | None] = mapped_column(String(100))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    # Soft delete: rows are never removed, only hidden from reads.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Appointment(Base):
    """A booked first visit. Availability is mock data (see services/appointments.py)."""

    __tablename__ = "appointments"

    appointment_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("patients.patient_id"), index=True
    )
    # Clinic-local wall-clock time; unique so a slot cannot be double-booked.
    starts_at: Mapped[datetime] = mapped_column(DateTime, unique=True)
    provider: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CallLog(Base):
    """One row per phone call, linked to the patient it created or updated (if any)."""

    __tablename__ = "call_logs"

    call_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("patients.patient_id"), index=True
    )
    caller_number: Mapped[str | None] = mapped_column(String(20))
    ended_reason: Mapped[str | None] = mapped_column(String(100))
    summary: Mapped[str | None] = mapped_column(Text)
    transcript: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
