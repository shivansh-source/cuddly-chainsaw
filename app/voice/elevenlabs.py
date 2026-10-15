"""ElevenLabs outbound call (via a Twilio number imported into ElevenLabs)."""
import httpx

OUTBOUND_URL = "https://api.elevenlabs.io/v1/convai/twilio/outbound-call"


class VoiceProviderError(Exception):
    pass


class ElevenLabsClient:
    def __init__(self, api_key: str, agent_id: str, phone_number_id: str,
                 transport: httpx.BaseTransport | None = None, timeout: float = 20.0):
        missing = [n for n, v in (("ELEVENLABS_API_KEY", api_key),
                                  ("ELEVENLABS_AGENT_ID", agent_id),
                                  ("ELEVENLABS_PHONE_NUMBER_ID", phone_number_id)) if not v]
        if missing:
            raise VoiceProviderError("not configured: " + ", ".join(missing))
        self._agent_id, self._phone = agent_id, phone_number_id
        self._client = httpx.Client(timeout=timeout, transport=transport,
                                    headers={"xi-api-key": api_key})

    def outbound_call(self, to_number: str, dynamic_variables: dict) -> dict:
        body = {
            "agent_id": self._agent_id,
            "agent_phone_number_id": self._phone,
            "to_number": to_number,
            "conversation_initiation_client_data": {"dynamic_variables": dynamic_variables},
        }
        try:
            resp = self._client.post(OUTBOUND_URL, json=body)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise VoiceProviderError(f"outbound call failed: {exc}") from exc
        if not data.get("success", False):
            raise VoiceProviderError(data.get("message") or "provider refused the call")
        return {"conversation_id": data.get("conversation_id"), "call_sid": data.get("callSid")}
