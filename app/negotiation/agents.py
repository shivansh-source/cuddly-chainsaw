"""Action layer: LLM proposes, guardrail disposes.

Flow per agent turn: ask the model -> parse into `Action` -> guardrail.
An invalid or blocked answer is re-prompted ONCE with the reasons, then the
deterministic counter is used and labeled `engine`. Provider failures skip
straight to the fallback.
"""
import json
from dataclasses import dataclass

from pydantic import ValidationError

from app.engine.guardrail import validate_action
from app.engine.models import (
    Action, BuyerAuthority, GuardrailResult, Participant, SellerAuthority, Source,
)
from app.llm.base import LLMClient, LLMError

MAX_LLM_ATTEMPTS = 2  # first try + one retry


@dataclass
class AgentOutcome:
    action: Action
    guard: GuardrailResult
    source: Source            # llm_agent if the model's answer passed, else engine
    raw_llm_output: str | None
    attempts: int
    notes: list[str]


def _parse(raw: str, mpn: str, qty: int) -> Action:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("model output must be a JSON object")
    data.setdefault("mpn", mpn)       # fixed by context; omitting it is harmless
    data.setdefault("qty", qty)
    allowed = {"type", "mpn", "unit_price", "qty", "lead_time_days", "message"}
    return Action(**{k: v for k, v in data.items() if k in allowed})


def decide_action(
    llm: LLMClient | None,
    system: str,
    user: str,
    participant: Participant,
    authority: SellerAuthority | BuyerAuthority,
    fallback: Action,
    mpn: str,
    qty: int,
) -> AgentOutcome:
    notes: list[str] = []
    raw: str | None = None
    attempts = 0

    if llm is not None:
        feedback = ""
        for _ in range(MAX_LLM_ATTEMPTS):
            attempts += 1
            try:
                raw = llm.complete(system, user + feedback)
            except LLMError as exc:
                notes.append(str(exc))
                break
            try:
                action = _parse(raw, mpn, qty)
            except (ValueError, ValidationError, TypeError) as exc:
                notes.append(f"attempt {attempts}: unparseable ({exc.__class__.__name__})")
                feedback = f"\nYour previous reply was not valid ({exc}). {system[-160:]}"
                continue
            guard = validate_action(participant, action, authority)
            if guard.status == "ok":
                return AgentOutcome(action, guard, "llm_agent", raw, attempts, notes)
            notes.append(f"attempt {attempts}: blocked ({'; '.join(guard.reasons)})")
            feedback = "\nYour previous reply was rejected: " + "; ".join(guard.reasons)

    guard = validate_action(participant, fallback, authority)
    notes.append("used deterministic fallback")
    return AgentOutcome(fallback, guard, "engine", raw, attempts, notes)
