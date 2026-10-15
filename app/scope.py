"""What each side is allowed to see.

Offers never store floors or ceilings, but guardrail reasons and agent notes
do ("price 250 below floor 295"). Showing those to the other side would leak
exactly what the asymmetry protects, so counterparty turns are redacted.
"""
from typing import Any

_REDACTED_KEYS = ("raw_llm_output", "notes")


def _redact_turn(turn: dict) -> dict:
    out = dict(turn)
    for key in _REDACTED_KEYS:
        out[key] = None if key == "raw_llm_output" else []
    guard = dict(out.get("guardrail_result") or {})
    guard.pop("reasons", None)
    out["guardrail_result"] = guard
    return out


def turns_for_buyer(turns: list[dict]) -> list[dict]:
    """Buyer sees the whole thread, but a seller's internal reasoning is hidden."""
    return [_redact_turn(t) if t.get("side") == "seller" else t for t in turns]


def turns_for_seller(turns: list[dict], company_id: str) -> list[dict]:
    """Seller sees only its own thread; the buyer's internal reasoning is hidden."""
    mine = [t for t in turns
            if t.get("participant_id") == company_id or t.get("counterparty_id") == company_id]
    return [_redact_turn(t) if t.get("side") == "buyer" else t for t in mine]


def offers_for_seller(offers: list[dict], company_id: str) -> list[dict]:
    """Offers carry the thread's seller in company_id, so this hides competitors."""
    return [o for o in offers if o.get("company_id") == company_id]


def rfq_for_buyer(rfq: dict) -> dict:
    return dict(rfq)


def rfq_for_seller(rfq: dict, company_id: str) -> dict:
    """No budget, no target, no competitor identities."""
    out = {k: v for k, v in rfq.items()
           if k not in ("budget", "budget_basis", "buyer_limits", "participants")}
    out["participants"] = [
        p for p in rfq.get("participants", [])
        if p["side"] == "buyer" or p["company_id"] == company_id
    ]
    return out


def clean_json(value: Any) -> Any:
    """ObjectId/datetime-safe copy for JSON responses."""
    from datetime import datetime

    from bson import ObjectId
    if isinstance(value, dict):
        return {k: clean_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean_json(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, ObjectId):
        return str(value)
    return value
