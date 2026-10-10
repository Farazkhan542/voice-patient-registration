import json

from app.agent.tools import run_tool

HEADERS = {"X-Vapi-Secret": "test-secret"}
LLM_URL = "/vapi/llm/test-secret/chat/completions"


# --- agent actions (what the LLM's tools do) --------------------------------

def test_save_then_lookup_then_update(client, patient_payload):
    assert run_tool("lookup_patient", {"phone_number": "7325550101"}) == {"status": "not_found"}

    saved = run_tool("save_patient", {**patient_payload, "email": ""}, call_id="call-1")
    assert saved["status"] == "saved" and saved["first_name"] == "Jane"

    # The record written by the agent is visible through the REST API.
    record = client.get(f"/patients/{saved['patient_id']}").json()["data"]
    assert record["city"] == "Somerset" and record["email"] is None

    found = run_tool("lookup_patient", {"phone_number": "732-555-0101"})
    assert found["status"] == "found"
    assert found["patients"][0]["patient_id"] == saved["patient_id"]

    # Blank fields mean "unchanged" on update.
    updated = run_tool("update_patient",
                       {"patient_id": saved["patient_id"], "last_name": "Davis", "city": ""})
    assert updated["status"] == "updated"
    record = client.get(f"/patients/{saved['patient_id']}").json()["data"]
    assert record["last_name"] == "Davis" and record["city"] == "Somerset"


def test_invalid_data_is_reported_per_field_and_not_saved(client, patient_payload):
    result = run_tool("save_patient",
                      {**patient_payload, "date_of_birth": "01/01/2999", "phone_number": "555"})
    assert result["status"] == "validation_error"
    assert sorted(e["field"] for e in result["errors"]) == ["date_of_birth", "phone_number"]
    assert client.get("/patients").json()["data"] == []


def test_database_failure_returns_error_status_not_a_crash(client, patient_payload, monkeypatch):
    from app.services import patients as patient_service

    def boom(*_args, **_kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(patient_service, "create_patient", boom)
    assert run_tool("save_patient", patient_payload)["status"] == "error"


# --- custom LLM endpoint ----------------------------------------------------

def _spoken_text(response) -> str:
    lines = [line[len("data: "):] for line in response.text.splitlines() if line.startswith("data: ")]
    assert lines[-1] == "[DONE]"
    chunks = [json.loads(line) for line in lines[:-1]]
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    return "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)


def _llm_request(text="My name is Jane"):
    return {"stream": True, "call": {"id": "call-1"},
            "messages": [{"role": "system", "content": "ignored"},
                         {"role": "user", "content": text}]}


def test_llm_endpoint_rejects_wrong_secret(client):
    assert client.post("/vapi/llm/wrong/chat/completions", json=_llm_request()).status_code == 401


def test_llm_endpoint_streams_agent_reply(client, monkeypatch):
    seen = {}

    async def fake_stream_reply(context, user_text, transcript=None):
        seen.update(call_id=context.call_id, user_text=user_text)
        yield "Thanks, "
        yield "Jane."

    monkeypatch.setattr("app.routers.vapi.stream_reply", fake_stream_reply)
    response = client.post(LLM_URL, json=_llm_request())
    assert response.status_code == 200
    assert _spoken_text(response) == "Thanks, Jane."
    assert seen == {"call_id": "call-1", "user_text": "My name is Jane"}


def test_llm_failure_becomes_a_spoken_apology(client, monkeypatch):
    async def broken_stream_reply(context, user_text, transcript=None):
        raise RuntimeError("model provider is down")
        yield  # pragma: no cover

    monkeypatch.setattr("app.routers.vapi.stream_reply", broken_stream_reply)
    response = client.post(LLM_URL, json=_llm_request())
    assert response.status_code == 200
    assert "trouble" in _spoken_text(response)


# --- end-of-call webhook ----------------------------------------------------

def test_webhook_requires_secret(client):
    response = client.post("/vapi/webhook", json={"message": {"type": "end-of-call-report"}})
    assert response.status_code == 401


def test_end_of_call_report_stores_transcript_linked_to_patient(client, patient_payload):
    saved = run_tool("save_patient", patient_payload, call_id="call-9",
                     caller_number="+17325550101")
    report = {
        "message": {
            "type": "end-of-call-report",
            "call": {"id": "call-9", "customer": {"number": "+17325550101"}},
            "endedReason": "assistant-ended-call",
            "analysis": {"summary": "Registered Jane Doe."},
            "artifact": {"transcript": "AI: Hello\nUser: Hi"},
        }
    }
    assert client.post("/vapi/webhook", json=report, headers=HEADERS).status_code == 200

    calls = client.get(f"/patients/{saved['patient_id']}/calls").json()["data"]
    assert len(calls) == 1
    assert calls[0]["transcript"] == "AI: Hello\nUser: Hi"
    assert calls[0]["summary"] == "Registered Jane Doe."
    assert calls[0]["ended_reason"] == "assistant-ended-call"


def test_dropped_call_is_logged_without_a_patient(client):
    report = {"message": {"type": "end-of-call-report", "call": {"id": "call-drop"},
                          "endedReason": "customer-ended-call", "transcript": "AI: Hello"}}
    client.post("/vapi/webhook", json=report, headers=HEADERS)
    calls = client.get("/calls").json()["data"]
    assert calls[0]["call_id"] == "call-drop" and calls[0]["patient_id"] is None


# --- appointment scheduling -------------------------------------------------

def test_book_appointment_and_slot_is_no_longer_offered(client, patient_payload):
    saved = run_tool("save_patient", patient_payload)
    slots = run_tool("get_appointment_slots", {})
    assert slots["status"] == "ok" and len(slots["slots"]) >= 2
    chosen = slots["slots"][0]

    booked = run_tool("book_appointment", {"patient_id": saved["patient_id"], "slot": chosen["slot"]})
    assert booked == {"status": "booked", "provider": slots["provider"], "spoken": chosen["spoken"]}

    appointments = client.get(f"/patients/{saved['patient_id']}/appointments").json()["data"]
    assert [a["starts_at"][:16] for a in appointments] == [chosen["slot"]]

    remaining = [s["slot"] for s in run_tool("get_appointment_slots", {})["slots"]]
    assert chosen["slot"] not in remaining
    again = run_tool("book_appointment", {"patient_id": saved["patient_id"], "slot": chosen["slot"]})
    assert again["status"] == "slot_unavailable"


def test_book_appointment_rejects_made_up_slot_and_unknown_patient(client, patient_payload):
    saved = run_tool("save_patient", patient_payload)
    made_up = run_tool("book_appointment", {"patient_id": saved["patient_id"], "slot": "2020-01-01T03:00"})
    assert made_up["status"] == "slot_unavailable"
    slot = run_tool("get_appointment_slots", {})["slots"][0]["slot"]
    unknown = run_tool("book_appointment",
                       {"patient_id": "00000000-0000-0000-0000-000000000000", "slot": slot})
    assert unknown["status"] == "error"
