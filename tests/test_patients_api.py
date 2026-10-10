from datetime import date, timedelta


def _create(client, payload):
    response = client.post("/patients", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_create_returns_envelope_and_generated_fields(client, patient_payload):
    response = client.post("/patients", json=patient_payload)
    body = response.json()
    assert response.status_code == 201
    assert body["error"] is None
    data = body["data"]
    assert len(data["patient_id"]) == 36
    assert data["phone_number"] == "7325550101"
    assert data["date_of_birth"] == "03/03/1985"
    assert data["preferred_language"] == "English"
    assert data["created_at"].endswith("Z") and data["updated_at"].endswith("Z")


def test_get_by_id(client, patient_payload):
    created = _create(client, patient_payload)
    response = client.get(f"/patients/{created['patient_id']}")
    assert response.status_code == 200
    assert response.json()["data"]["last_name"] == "Doe"


def test_get_unknown_id_is_404_and_malformed_id_is_400(client):
    assert client.get("/patients/00000000-0000-0000-0000-000000000000").status_code == 404
    response = client.get("/patients/not-a-uuid")
    assert response.status_code == 400
    assert response.json()["data"] is None


def test_list_filters(client, patient_payload):
    _create(client, patient_payload)
    _create(client, {**patient_payload, "first_name": "Sam", "last_name": "Davis",
                     "date_of_birth": "1990-07-04", "phone_number": "2125550147"})
    assert len(client.get("/patients").json()["data"]) == 2
    assert len(client.get("/patients", params={"last_name": "davis"}).json()["data"]) == 1
    assert len(client.get("/patients", params={"date_of_birth": "07/04/1990"}).json()["data"]) == 1
    assert len(client.get("/patients", params={"phone_number": "732-555-0101"}).json()["data"]) == 1
    assert client.get("/patients", params={"phone_number": "123"}).status_code == 422


def test_validation_errors_name_the_field(client, patient_payload):
    tomorrow = (date.today() + timedelta(days=2)).strftime("%m/%d/%Y")
    cases = {
        "date_of_birth": tomorrow,
        "phone_number": "123",
        "state": "ZZ",
        "zip_code": "1234",
        "sex": "Unknown",
        "first_name": "J4ne",
        "email": "not-an-email",
    }
    for field, bad_value in cases.items():
        response = client.post("/patients", json={**patient_payload, field: bad_value})
        assert response.status_code == 422, field
        error = response.json()["error"]
        assert [d["field"] for d in error["details"]] == [field]


def test_impossible_date_and_missing_required_field(client, patient_payload):
    assert client.post("/patients", json={**patient_payload, "date_of_birth": "02/30/1990"}).status_code == 422
    del patient_payload["last_name"]
    response = client.post("/patients", json=patient_payload)
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "last_name"


def test_malformed_json_is_400_and_unknown_field_is_422(client, patient_payload):
    response = client.post("/patients", content="{not json",
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 400
    assert client.post("/patients", json={**patient_payload, "ssn": "123"}).status_code == 422


def test_state_name_and_hyphenated_name_are_normalised(client, patient_payload):
    data = _create(client, {**patient_payload, "state": "new jersey",
                            "last_name": "O'Brien-Smith", "zip_code": "088731234"})
    assert data["state"] == "NJ"
    assert data["last_name"] == "O'Brien-Smith"
    assert data["zip_code"] == "08873-1234"


def test_partial_update(client, patient_payload):
    created = _create(client, patient_payload)
    response = client.put(f"/patients/{created['patient_id']}",
                          json={"last_name": "Davis", "email": "jane@example.com"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["last_name"] == "Davis"
    assert data["email"] == "jane@example.com"
    assert data["first_name"] == "Jane"


def test_update_rejects_bad_values(client, patient_payload):
    created = _create(client, patient_payload)
    url = f"/patients/{created['patient_id']}"
    assert client.put(url, json={"phone_number": "555"}).status_code == 422
    assert client.put(url, json={"first_name": None}).status_code == 422
    assert client.put(url, json={}).status_code == 422
    assert client.put("/patients/00000000-0000-0000-0000-000000000000",
                      json={"city": "Edison"}).status_code == 404


def test_delete_is_soft(client, patient_payload):
    created = _create(client, patient_payload)
    url = f"/patients/{created['patient_id']}"
    response = client.delete(url)
    assert response.status_code == 200
    assert response.json()["data"]["deleted_at"] is not None
    assert client.get(url).status_code == 404
    assert client.get("/patients").json()["data"] == []
    assert client.delete(url).status_code == 404

    from app.db import SessionLocal
    from app.models import Patient
    with SessionLocal() as session:
        assert session.query(Patient).count() == 1  # row is still there
