"""Create or update the Vapi assistant and attach it to a phone number.

Usage:  python -m scripts.setup_vapi

Requires VAPI_API_KEY and PUBLIC_BASE_URL in the environment (.env). Re-run it
whenever the prompt, tools or public URL change.
"""

import sys

import httpx

from app.agent.assistant import build_assistant_config
from app.config import settings

VAPI_API = "https://api.vapi.ai"


def _request(client: httpx.Client, method: str, path: str, body: dict | None = None):
    response = client.request(method, path, json=body)
    if response.status_code >= 400:
        sys.exit(f"Vapi {method} {path} failed ({response.status_code}): {response.text}")
    return response.json()


def main() -> None:
    if not (settings.vapi_api_key and settings.public_base_url and settings.vapi_webhook_secret):
        sys.exit("Set VAPI_API_KEY, PUBLIC_BASE_URL and VAPI_WEBHOOK_SECRET in .env first.")

    config = build_assistant_config(settings)
    headers = {"Authorization": f"Bearer {settings.vapi_api_key}"}
    with httpx.Client(base_url=VAPI_API, headers=headers, timeout=30) as client:
        if settings.vapi_assistant_id:
            assistant = _request(client, "PATCH", f"/assistant/{settings.vapi_assistant_id}", config)
            print(f"Updated assistant {assistant['id']}")
        else:
            assistant = _request(client, "POST", "/assistant", config)
            print(f"Created assistant {assistant['id']}")
            print(f"  -> add VAPI_ASSISTANT_ID={assistant['id']} to .env so re-runs update it")

        numbers = _request(client, "GET", "/phone-number")
        if settings.vapi_phone_number_id:
            numbers = [n for n in numbers if n["id"] == settings.vapi_phone_number_id]
        if not numbers:
            sys.exit("No phone number found. Create one in the Vapi dashboard "
                     "(Phone Numbers -> Create), then re-run this script.")
        number = numbers[0]
        _request(client, "PATCH", f"/phone-number/{number['id']}", {"assistantId": assistant["id"]})
        print(f"Attached to phone number {number.get('number', number['id'])}")
        print(f"Backend: {settings.public_base_url}")


if __name__ == "__main__":
    main()
