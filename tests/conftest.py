import os
import tempfile

# Point the app at a throwaway database before anything imports app.config.
_db_dir = tempfile.mkdtemp(prefix="patients-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_dir}/test.db".replace("\\", "/")
os.environ["SEED_DATA"] = "false"
os.environ["VAPI_WEBHOOK_SECRET"] = "test-secret"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(engine)


@pytest.fixture()
def patient_payload():
    return {
        "first_name": "Jane",
        "last_name": "Doe",
        "date_of_birth": "03/03/1985",
        "sex": "Female",
        "phone_number": "(732) 555-0101",
        "address_line_1": "123 Main Street",
        "city": "Somerset",
        "state": "NJ",
        "zip_code": "08873",
    }
