"""Groq (OpenAI-compatible chat completions) client."""
import httpx

from app.llm.base import LLMError

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqClient:
    name = "groq"

    def __init__(self, api_key: str, model: str, timeout: float = 20.0,
                 transport: httpx.BaseTransport | None = None):
        if not api_key:
            raise ValueError("GROQ_API_KEY is not set")
        self._model = model
        self._client = httpx.Client(
            timeout=timeout, transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def complete(self, system: str, user: str) -> str:
        body = {
            "model": self._model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            resp = self._client.post(GROQ_URL, json=body)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"groq request failed: {exc}") from exc
