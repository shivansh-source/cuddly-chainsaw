"""Groq (OpenAI-compatible chat completions) client."""
import time

import httpx

from app.llm.base import LLMError

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_RATE_LIMIT_RETRIES = 2   # free tier returns 429 under bursts
MAX_BACKOFF_SECONDS = 8.0


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
            for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
                resp = self._client.post(GROQ_URL, json=body)
                if resp.status_code == 429 and attempt < MAX_RATE_LIMIT_RETRIES:
                    wait = float(resp.headers.get("retry-after") or 2 ** attempt)
                    time.sleep(min(wait, MAX_BACKOFF_SECONDS))
                    continue
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"groq request failed: {exc}") from exc
        raise LLMError("groq request failed: retries exhausted")
