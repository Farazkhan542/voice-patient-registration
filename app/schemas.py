"""Pydantic request/response models for patients."""

import uuid
from datetime import date, datetime, timezone
from typing import Callable

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator, model_validator

from app import validation as v

REQUIRED_FIELDS = (
    "first_name", "last_name", "date_of_birth", "sex", "phone_number",
    "address_line_1", "city", "state", "zip_code",
)


def _optional(normalize: Callable[[object], object]) -> Callable[[object], object]:
    """Treat null / blank strings as "not provided" for optional fields."""
    return lambda value: None if v.is_blank(value) else normalize(value)


def _text(max_length: int) -> Callable[[object], str]:
    return lambda value: v.clean_text(value, max_length)


# field name -> normaliser. One table drives validation for create and update.
_NORMALIZERS: dict[str, Callable[[object], object]] = {
    "first_name": v.normalize_name,
    "last_name": v.normalize_name,
    "date_of_birth": v.parse_date_of_birth,
    "sex": v.normalize_sex,
    "phone_number": v.normalize_phone,
    "email": _optional(v.normalize_email),
    "address_line_1": _text(200),
    "address_line_2": _optional(_text(200)),
    "city": _text(100),
    "state": v.normalize_state,
    "zip_code": v.normalize_zip,
    "insurance_provider": _optional(_text(100)),
    "insurance_member_id": _optional(v.normalize_member_id),
    "preferred_language": lambda value: "English" if v.is_blank(value) else v.clean_text(value, 50),
    "emergency_contact_name": _optional(_text(100)),
    "emergency_contact_phone": _optional(v.normalize_phone),
}
PATIENT_FIELDS = tuple(_NORMALIZERS)


class _PatientInput(BaseModel):
    # Unknown keys are rejected rather than silently dropped.
    model_config = ConfigDict(extra="forbid")

    @field_validator(*PATIENT_FIELDS, mode="before", check_fields=False)
    @classmethod
    def _normalize(cls, value: object, info) -> object:
        if value is None and info.field_name in REQUIRED_FIELDS:
            raise ValueError("is required")
        return _NORMALIZERS[info.field_name](value)


class PatientCreate(_PatientInput):
    first_name: str
    last_name: str
    date_of_birth: date
    sex: str
    phone_number: str
    email: str | None = None
    address_line_1: str
    address_line_2: str | None = None
    city: str
    state: str
    zip_code: str
    insurance_provider: str | None = None
    insurance_member_id: str | None = None
    preferred_language: str = "English"
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None


class PatientUpdate(_PatientInput):
    """Partial update: only fields present in the request body are changed."""

    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    sex: str | None = None
    phone_number: str | None = None
    email: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    insurance_provider: str | None = None
    insurance_member_id: str | None = None
    preferred_language: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None

    @model_validator(mode="after")
    def _require_a_change(self) -> "PatientUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        return self


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    # SQLite drops tzinfo; everything we store is UTC.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patient_id: uuid.UUID
    first_name: str
    last_name: str
    date_of_birth: date
    sex: str
    phone_number: str
    email: str | None
    address_line_1: str
    address_line_2: str | None
    city: str
    state: str
    zip_code: str
    insurance_provider: str | None
    insurance_member_id: str | None
    preferred_language: str
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    @field_serializer("date_of_birth")
    def _dob(self, value: date) -> str:
        return value.strftime("%m/%d/%Y")

    @field_serializer("created_at", "updated_at", "deleted_at")
    def _timestamp(self, value: datetime | None) -> str | None:
        return _utc_iso(value)


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    appointment_id: uuid.UUID
    patient_id: uuid.UUID
    # Clinic-local time (America/New_York), no offset.
    starts_at: datetime
    provider: str
    created_at: datetime

    @field_serializer("created_at")
    def _timestamp(self, value: datetime | None) -> str | None:
        return _utc_iso(value)


class CallLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    call_id: str
    patient_id: uuid.UUID | None
    caller_number: str | None
    ended_reason: str | None
    summary: str | None
    transcript: str | None
    created_at: datetime
    ended_at: datetime | None

    @field_serializer("created_at", "ended_at")
    def _timestamp(self, value: datetime | None) -> str | None:
        return _utc_iso(value)
