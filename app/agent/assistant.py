"""Builds the Vapi assistant definition (telephony + speech settings).

Vapi handles the phone line, speech-to-text and text-to-speech. The "custom-llm"
model block points it at this backend for every conversational turn, so the
prompt, tools and model choice all live in this repository, not in Vapi.

Kept as code rather than clicked together in the Vapi dashboard so the agent is
version-controlled and reproducible: scripts/setup_vapi.py pushes this config.
"""

from app.agent.prompt import END_CALL_PHRASES, FIRST_MESSAGE
from app.config import Settings

ASSISTANT_NAME = "Patient Registration Agent"


def build_assistant_config(settings: Settings) -> dict:
    base_url = settings.public_base_url
    secret = settings.vapi_webhook_secret

    config = {
        "name": ASSISTANT_NAME,
        "firstMessage": FIRST_MESSAGE,
        "firstMessageMode": "assistant-speaks-first",
        "model": {
            "provider": "custom-llm",
            # Vapi appends /chat/completions. The secret is part of the path
            # because that is the one credential Vapi is guaranteed to send back.
            "url": f"{base_url}/vapi/llm/{secret}",
            "model": settings.llm_model,
        },
        # Multilingual transcription so a caller can switch to Spanish mid-call.
        "transcriber": {"provider": "deepgram", "model": "nova-3", "language": "multi"},
        "server": {"url": f"{base_url}/vapi/webhook", "headers": {"X-Vapi-Secret": secret}},
        "serverMessages": ["end-of-call-report"],
        "endCallPhrases": END_CALL_PHRASES,
        "silenceTimeoutSeconds": 30,
        "maxDurationSeconds": 900,
    }
    if settings.vapi_voice_provider and settings.vapi_voice_id:
        config["voice"] = {
            "provider": settings.vapi_voice_provider,
            "voiceId": settings.vapi_voice_id,
        }
    return config
