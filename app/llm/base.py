"""LLM behind an interface so the provider can be swapped without touching the
engine. The model only ever returns text; the action layer parses and the
guardrail validates it."""
from typing import Protocol


class LLMError(Exception):
    """Transport or provider failure. The caller falls back to the engine."""


class LLMClient(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str:
        """Return the raw model output (expected to be one JSON object)."""
        ...
