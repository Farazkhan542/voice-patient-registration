# Voice AI Agent: Patient Registration

Call a phone number, talk to "Maya", and get registered as a patient. The record is validated, saved to a database, and available through a REST API and a small dashboard. After registering, the caller can book a first appointment.

## Live demo

| | |
|---|---|
| Phone number | **+1 (984) 246-9350** |
| API base URL | https://voice-patient-registration-production-ab62.up.railway.app |
| Dashboard | https://voice-patient-registration-production-ab62.up.railway.app/dashboard |
| API docs (Swagger) | https://voice-patient-registration-production-ab62.up.railway.app/docs |

No credentials are needed to call the number or use the API. Two seed patients (Jane Doe, Carlos Rivera) exist on first start. Hosted on Railway with PostgreSQL.

The LLM runs on Gemini's free tier, which is rate-limited: please place one call at a time.

## Architecture

```
Caller ── phone ──> Vapi (telephony, speech-to-text, text-to-speech)
                      │  each caller utterance, as an OpenAI-style chat request
                      ▼
              FastAPI backend (this repo)
              ├─ routers/vapi.py      Vapi wire format: custom-LLM endpoint + end-of-call webhook
              ├─ agent/               conversation logic (OpenAI Agents SDK, prompt, tools)
              │     └─ LLM: Gemini Flash-Lite via an OpenAI-compatible endpoint
              ├─ services/            the only code that reads/writes the database
              ├─ routers/patients.py  REST API
              └─ static/dashboard.html
                      │
                      ▼
              SQLite (local) / PostgreSQL (deployed)
```

How one turn of a call works:

1. Vapi transcribes what the caller said and POSTs it to `/vapi/llm/<secret>/chat/completions`.
2. The backend runs the registration agent (OpenAI Agents SDK). The agent may call its tools (`lookup_patient`, `save_patient`, `update_patient`, `get_appointment_slots`, `book_appointment`), which call the same service layer as the REST API.
3. The reply is streamed back and Vapi speaks it.
4. When the call ends, Vapi posts an end-of-call report to `/vapi/webhook`, and the transcript is stored against the patient.

### Where each concern lives

| Concern | Location |
|---|---|
| Telephony / provider wire format | [app/routers/vapi.py](app/routers/vapi.py), [app/agent/assistant.py](app/agent/assistant.py), [scripts/setup_vapi.py](scripts/setup_vapi.py) |
| LLM logic (agent, memory, tool schemas) | [app/agent/agent.py](app/agent/agent.py) |
| System prompt, with design notes | [app/agent/prompt.py](app/agent/prompt.py) |
| Agent actions (framework-free) | [app/agent/tools.py](app/agent/tools.py) |
| Validation rules (one place, used by API and agent) | [app/validation.py](app/validation.py), [app/schemas.py](app/schemas.py) |
| Data layer (patients, call logs, appointments) | [app/models.py](app/models.py), [app/services/](app/services/) |
| REST API | [app/routers/patients.py](app/routers/patients.py) |

## Tech stack and why

| Layer | Choice | Reason |
|---|---|---|
| Telephony + speech | Vapi | Provides a U.S. number, speech-to-text, text-to-speech, barge-in and turn-taking, so the time goes into the conversation and the backend. |
| Agent framework | OpenAI Agents SDK | Handles the tool-calling loop and streaming. Running it in our backend (Vapi "custom LLM") keeps the prompt, tools and model in version control instead of a vendor dashboard. |
| LLM | Gemini 3.5 Flash-Lite, with two fallback models | Fast enough for voice and usable on the free tier (15 requests/minute; the larger Flash models allow 5). Each Gemini model has its own quota, so a rate-limited turn is retried on the next model. Reached through an OpenAI-compatible endpoint (Google directly or OpenRouter), so changing model is an environment change. |
| Backend | FastAPI | Async streaming for the LLM endpoint, Pydantic validation, generated API docs. |
| Database | SQLAlchemy on SQLite or PostgreSQL | SQLite needs no setup locally; the same code runs on managed Postgres when deployed, where the container filesystem is not durable. |
| Dashboard | One static HTML page served by FastAPI | A read-only table does not justify a second app and a second deployment. |

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then fill it in (see below)
uvicorn app.main:app --reload --port 8000
```

The REST API and dashboard work with no keys at all: open http://localhost:8000/dashboard.

### Connecting the phone number

1. Get an LLM key: OpenRouter (https://openrouter.ai/keys) or Gemini (https://aistudio.google.com/apikey). Put it in `.env`.
2. Create a Vapi account (https://dashboard.vapi.ai). Under **Phone Numbers**, create a free U.S. number. Under **API Keys**, copy the private key into `VAPI_API_KEY`.
3. Set `VAPI_WEBHOOK_SECRET` to a long random string of letters and digits.
4. Make the backend reachable over HTTPS and set `PUBLIC_BASE_URL` to that URL:
   - deployed: see "Deploying" below, or
   - local: `ngrok http 8000` and use the `https://...ngrok-free.app` URL.
5. Push the assistant config to Vapi and attach it to the number:
   ```bash
   python -m scripts.setup_vapi
   ```
   Copy the printed assistant id into `VAPI_ASSISTANT_ID` so later runs update the same assistant.
6. Call the number.

Re-run step 5 whenever `PUBLIC_BASE_URL`, the secret, or the first message changes. Prompt and tool changes only need a backend restart, because the prompt lives in the backend.

### Deploying (Railway)

1. Push this repo to GitHub. In Railway: **New Project → Deploy from GitHub repo**. The `Dockerfile` is picked up automatically.
2. Add a **PostgreSQL** service to the project. In the app service's variables, add `DATABASE_URL = ${{Postgres.DATABASE_URL}}`.
3. Add the other variables from `.env` (`OPENROUTER_API_KEY` or `GEMINI_API_KEY`, `VAPI_WEBHOOK_SECRET`).
4. **Settings → Networking → Generate Domain**. Use that URL as `PUBLIC_BASE_URL` in your local `.env`, then run `python -m scripts.setup_vapi` locally.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | no | Defaults to `sqlite:///./data/patients.db`. `postgres://` URLs are accepted. |
| `SEED_DATA` | no | `true` (default) inserts two demo patients into an empty table. |
| `OPENROUTER_API_KEY` or `GEMINI_API_KEY` | one, for calls | LLM key. OpenRouter is used if both are set. |
| `LLM_MODEL`, `LLM_FALLBACK_MODELS`, `LLM_BASE_URL` | no | Override the model, the comma-separated fallback list, or point at any OpenAI-compatible endpoint. |
| `VAPI_WEBHOOK_SECRET` | for calls | Shared secret Vapi must present on every request to the backend. |
| `PUBLIC_BASE_URL` | setup script | Public HTTPS URL of this backend. |
| `VAPI_API_KEY` | setup script | Vapi private key. Not needed by the running server. |
| `VAPI_ASSISTANT_ID`, `VAPI_PHONE_NUMBER_ID` | no | Update an existing assistant / choose a specific number. |
| `VAPI_VOICE_PROVIDER`, `VAPI_VOICE_ID` | no | Voice override. Blank uses Vapi's default voice. |

## REST API

Every response is `{ "data": ..., "error": null }` or `{ "data": null, "error": { "code", "message", "details": [{ "field", "message" }] } }`.

| Method | Path | Notes |
|---|---|---|
| GET | `/patients` | Filters: `?last_name=` (case-insensitive), `?date_of_birth=` (MM/DD/YYYY or YYYY-MM-DD), `?phone_number=` |
| GET | `/patients/{id}` | 404 if missing or soft-deleted, 400 if the id is not a UUID |
| POST | `/patients` | 201 with the created record |
| PUT | `/patients/{id}` | Partial update; only fields in the body change |
| DELETE | `/patients/{id}` | Soft delete: sets `deleted_at`, row is kept |
| GET | `/patients/{id}/appointments` | Appointments booked for the patient |
| GET | `/patients/{id}/calls` | Call transcripts linked to the patient |
| GET | `/calls` | Most recent calls |
| GET | `/health` | Liveness check, plus which database is in use and whether the LLM key and secret are configured (booleans only) |

Status codes: 200, 201, 400 (malformed JSON or id), 404, 422 (validation, with the failing field named), 500.

```bash
curl -X POST "$BASE/patients" -H "Content-Type: application/json" -d '{
  "first_name": "Sam", "last_name": "Davis", "date_of_birth": "07/04/1990", "sex": "Male",
  "phone_number": "212-555-0147", "address_line_1": "1 Elm St",
  "city": "Newark", "state": "NJ", "zip_code": "07102"
}'
curl "$BASE/patients?last_name=Davis"
```

Validation is server-side and shared with the voice agent: names (1–50 letters, hyphens, apostrophes), a real non-future date of birth, the sex enum, 10-digit U.S. phone numbers (formatting and a leading `1` are stripped), 2-letter state (full names are converted), ZIP or ZIP+4, email format, alphanumeric member ID. Unknown fields are rejected. The database repeats the key rules as `CHECK` constraints.

## The voice agent

The system prompt is in [app/agent/prompt.py](app/agent/prompt.py), with the reasoning written at the top of the file. The main decisions:

- **Written for speech.** Short turns, one question at a time, no lists or symbols, explicit rules for saying digits, dates and spellings.
- **The model runs the conversation; the server decides what is valid.** The prompt asks the model to catch obvious problems early, but every save is re-validated. A rejected save returns the exact fields and reasons, and the agent re-asks for just those.
- **A fixed vocabulary of tool results** (`needs_confirmation`, `saved`, `updated`, `found`, `not_found`, `validation_error`, `error`), each with an instruction. The caller is only told they are registered after `saved` or `updated`.
- **Confirmation before any write, enforced in code.** The first `save_patient` / `update_patient` call only validates and returns `needs_confirmation`. The record is written when the same values are submitted again on a later turn, so a read-back and a caller reply always sit between collecting and saving (`_write` in [app/agent/agent.py](app/agent/agent.py)).
- **Returning callers.** After the phone number is given, the agent looks it up and offers to update the existing record.
- **Spanish.** If the caller speaks Spanish the agent switches, and stores `preferred_language = Spanish`.
- **First appointment.** After a successful save the agent offers to book a visit. Open times come from a tool (mock availability: two slots on each of the next three weekdays), the agent may only offer times the tool returned, and a booked slot is no longer offered to the next caller.

### What happens when things go wrong

| Situation | Behaviour |
|---|---|
| Invalid value (future birth date, 3-digit phone) | Agent re-asks for that field only. If the model misses it, the server rejects the save and names the field. |
| Caller corrects something or answers out of order | Agent applies it and carries on without re-asking the rest. |
| Caller says "start over" | Agent discards what it has and begins again. |
| Database write fails | Tool returns `error`; the agent apologises, retries once, then asks the caller to call back. |
| LLM rate limit or provider failure | The turn is retried on the next fallback model. If every model fails, the endpoint streams a spoken apology and asks the caller to repeat, instead of silence. |
| Caller interrupts mid-sentence | Vapi cancels the request; the backend keeps the partial reply in memory so the next turn has the right context. |
| Call drops mid-registration | Nothing unconfirmed is saved. The partial transcript is stored in `call_logs` with no patient attached. |
| Model tries to save twice in one call | The second save updates the record created by the first. |

### Observability

Everything goes to stdout: each caller utterance and agent reply, each tool call with its arguments and result, the final saved payload (`patient_saved ... payload={...}`), and the full transcript at the end of the call. Transcripts are also stored in the `call_logs` table and shown on the dashboard.

## Bonus items

All six are implemented: duplicate detection by phone number, appointment scheduling (mock availability), Spanish, call transcripts linked to the patient record, a dashboard, and automated tests.

## Tests

```bash
pytest
```

22 tests cover the REST API (CRUD, filters, validation, status codes, soft delete), the agent's actions including appointment booking, the custom-LLM endpoint (auth, streaming, failure fallback) and the end-of-call webhook. They use a temporary SQLite database and make no network calls.

## Known limitations and trade-offs

- **No authentication on the REST API or dashboard.** Left open so reviewers can query it. It holds demo data only; do not enter real patient information. A real deployment needs auth and is subject to HIPAA.
- **The Vapi secret is in the URL path** of the LLM endpoint, because that is the simplest credential Vapi reliably sends. It can therefore appear in access logs. A header-based credential would be better.
- **Conversation state is held in process memory**, keyed by call id. A restart mid-call loses that call's context, and running more than one instance would need a shared store such as Redis.
- **Ending the call depends on the agent saying "goodbye"** (a Vapi end-call phrase). If the model omits it, the call ends on the 30-second silence timeout instead.
- **Tool calls add a short pause** (two model round-trips) with no filler speech.
- **Free-tier rate limits.** On Gemini's free tier the three models together allow roughly 40 requests per minute, enough for one call at a time. Concurrent calls need a paid key.
- **The confirmation gate proves a read-back happened, not that the answer was yes.** Judging the caller's reply is still the model's job.
- **Spanish text-to-speech** depends on the configured Vapi voice being multilingual; the default voice may speak Spanish with an English accent.
- **Phone numbers are not unique** in the schema, because family members share numbers. Duplicate detection is done by the agent asking, not by a constraint.
- **Names allow spaces** ("Mary Ann", "De La Cruz") in addition to the letters, hyphens and apostrophes in the brief.
- **Schema is created with `create_all`**, with no migration tool.
- **The Agents SDK and Vapi's custom-LLM protocol are not covered by automated tests**; they are exercised by real calls.

## Next steps

- A real scheduling backend in place of the mock appointment slots.
- API authentication and rate limiting.
- Alembic migrations.
- Move per-call state to Redis so the service can scale horizontally.
- An automated conversation test suite that plays scripted callers against the agent and checks the saved record.
