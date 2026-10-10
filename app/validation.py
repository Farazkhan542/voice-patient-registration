"""Field-level normalisation and validation rules.

Pure functions that either return the cleaned value or raise ValueError with a
message short enough for the voice agent to turn into a re-prompt. Both the REST
API and the voice tools go through these, so the rules live in exactly one place.
"""

import re
from datetime import date, datetime, timezone

from app.models import SEX_VALUES

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "PR": "Puerto Rico", "GU": "Guam", "VI": "U.S. Virgin Islands", "AS": "American Samoa",
    "MP": "Northern Mariana Islands",
}
_STATE_BY_NAME = {name.lower(): abbr for abbr, name in US_STATES.items()}
_SEX_BY_LOWER = {value.lower(): value for value in SEX_VALUES}

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
_DOB_FORMATS = ("%m/%d/%Y", "%Y-%m-%d")
_OLDEST_BIRTH_YEAR = 1900


def clean_text(value: object, max_length: int) -> str:
    """Strip control characters, collapse whitespace, enforce a length cap."""
    if not isinstance(value, str):
        raise ValueError("must be text")
    text = re.sub(r"[\x00-\x1f\x7f]", " ", value)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise ValueError("cannot be empty")
    if len(text) > max_length:
        raise ValueError(f"must be at most {max_length} characters")
    return text


def is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def normalize_name(value: object) -> str:
    """1-50 chars, letters plus hyphens and apostrophes. Spaces are allowed for
    multi-part names such as "Mary Ann" or "De La Cruz"."""
    text = clean_text(value, 50).replace("’", "'")
    if not all(ch.isalpha() or ch in "-' " for ch in text) or not text[0].isalpha():
        raise ValueError("may only contain letters, hyphens and apostrophes")
    return text


def normalize_phone(value: object) -> str:
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError("must be a valid 10-digit U.S. phone number")
    return digits


def parse_date_of_birth(value: object) -> date:
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        parsed = None
        for fmt in _DOB_FORMATS:
            try:
                parsed = datetime.strptime(str(value).strip(), fmt).date()
                break
            except ValueError:
                continue
        if parsed is None:
            raise ValueError("must be a real calendar date in MM/DD/YYYY format")
    if parsed > datetime.now(timezone.utc).date():
        raise ValueError("cannot be in the future")
    if parsed.year < _OLDEST_BIRTH_YEAR:
        raise ValueError(f"year must be {_OLDEST_BIRTH_YEAR} or later")
    return parsed


def normalize_sex(value: object) -> str:
    match = _SEX_BY_LOWER.get(str(value).strip().lower())
    if match is None:
        raise ValueError("must be one of: " + ", ".join(SEX_VALUES))
    return match


def normalize_state(value: object) -> str:
    text = str(value).strip()
    if text.upper() in US_STATES:
        return text.upper()
    abbr = _STATE_BY_NAME.get(text.lower())
    if abbr is None:
        raise ValueError("must be a valid 2-letter U.S. state abbreviation")
    return abbr


def normalize_zip(value: object) -> str:
    text = str(value).strip()
    digits = re.sub(r"[\s\-]", "", text)
    if not digits.isdigit() or len(digits) not in (5, 9):
        raise ValueError("must be a 5-digit ZIP code or ZIP+4")
    return digits if len(digits) == 5 else f"{digits[:5]}-{digits[5:]}"


def normalize_email(value: object) -> str:
    text = clean_text(value, 254).lower()
    if not _EMAIL_RE.match(text):
        raise ValueError("must be a valid email address")
    return text


def normalize_member_id(value: object) -> str:
    text = re.sub(r"[\s\-]", "", clean_text(str(value), 60)).upper()
    if not text.isalnum() or len(text) > 50:
        raise ValueError("must be letters and numbers only")
    return text
