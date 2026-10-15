"""ElevenLabs post-call webhook: signature check and term extraction.

Signature scheme (from ElevenLabs' SDK behaviour, to be confirmed with a real
test event): header `ElevenLabs-Signature: t=<unix>,v0=<hex>` where
v0 = HMAC-SHA256(secret, f"{t}.{raw_body}"). Replays older than 30 minutes
are rejected. The header may carry several v0 values; any match is valid.
"""
import hashlib
import hmac
import re
import time
from typing import Any

TOLERANCE_SECONDS = 30 * 60


class SignatureError(Exception):
    pass


def sign(body: bytes, secret: str, timestamp: int | None = None) -> str:
    """Build a header value the way ElevenLabs does (used by tests and tooling)."""
    ts = int(timestamp if timestamp is not None else time.time())
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v0={digest}"


def verify_signature(body: bytes, header: str | None, secret: str,
                     now: float | None = None) -> None:
    if not secret:
        raise SignatureError("webhook secret is not configured")
    if not header:
        raise SignatureError("missing signature header")
    ts: str | None = None
    candidates: list[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            ts = value
        elif key == "v0":
            candidates.append(value)
    if ts is None or not ts.isdigit() or not candidates:
        raise SignatureError("malformed signature header")
    if abs((now if now is not None else time.time()) - int(ts)) > TOLERANCE_SECONDS:
        raise SignatureError("timestamp outside tolerance")
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, c) for c in candidates):
        raise SignatureError("signature mismatch")


# ------------------------------------------------------------------ extraction
_FIELDS = ("mpn", "unit_price", "qty", "lead_time_days", "readback_confirmed")


def _value(item: Any) -> Any:
    """data_collection_results entries look like {"value": ..., "rationale": ...}."""
    return item.get("value") if isinstance(item, dict) else item


def _number(raw: Any) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    cleaned = re.sub(r"[^\d.]", "", str(raw).replace(",", ""))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _truthy(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("true", "yes", "y", "1", "confirmed")


def extract_terms(analysis: dict | None) -> dict | None:
    """Read the confirmed terms from the agent's data-collection results.

    Expected item ids (configured on the ElevenLabs agent): confirmed_mpn,
    confirmed_unit_price, confirmed_qty, confirmed_lead_time_days,
    readback_confirmed. Returns None if the structured fields are absent.
    """
    results = (analysis or {}).get("data_collection_results") or {}
    if not isinstance(results, dict) or not results:
        return None
    price = _number(_value(results.get("confirmed_unit_price")))
    qty = _number(_value(results.get("confirmed_qty")))
    if price is None or qty is None:
        return None
    lead = _number(_value(results.get("confirmed_lead_time_days")))
    return {
        "mpn": (_value(results.get("confirmed_mpn")) or None),
        "unit_price": price,
        "qty": int(qty),
        "lead_time_days": int(lead) if lead is not None else None,
        "readback_confirmed": _truthy(_value(results.get("readback_confirmed"))),
    }


def transcript_text(transcript: list[dict] | None) -> str:
    return " ".join(str(t.get("message") or "") for t in (transcript or []))


def price_in_transcript(price: float, transcript: list[dict] | None) -> bool:
    """Sanity check that the confirmed number was actually spoken or written."""
    text = transcript_text(transcript).replace(",", "")
    forms = {f"{price:.2f}", f"{price:g}", f"{price:.1f}"}
    if float(price).is_integer():
        forms.add(str(int(price)))
    return any(re.search(rf"(?<![\d.]){re.escape(f)}(?![\d])", text) for f in forms)
