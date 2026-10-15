"""Shared FastAPI dependencies and access helpers."""
from functools import lru_cache

from fastapi import Depends, HTTPException

from app.auth import User, current_user
from app.config import settings
from app.db import get_db
from app.llm.base import LLMClient
from app.negotiation.orchestrator import NegotiationError, Orchestrator


@lru_cache
def _llm() -> LLMClient | None:
    """Groq if a key is configured; otherwise None, meaning the deterministic
    engine runs and every offer is labeled `engine`."""
    if not settings.groq_api_key:
        return None
    from app.llm.groq import GroqClient
    return GroqClient(settings.groq_api_key, settings.groq_model)


def get_llm() -> LLMClient | None:
    return _llm()


def get_orchestrator(llm: LLMClient | None = Depends(get_llm)) -> Orchestrator:
    return Orchestrator(get_db(), llm)


def buyer_only(user: User = Depends(current_user)) -> User:
    if user.role != "buyer":
        raise HTTPException(403, "buyers only")
    return user


def seller_only(user: User = Depends(current_user)) -> User:
    if user.role != "seller":
        raise HTTPException(403, "sellers only")
    return user


def guard(fn):
    """Run `fn`, turning orchestrator errors into HTTP errors."""
    try:
        return fn()
    except NegotiationError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


def participant_ids(rfq: dict, side: str) -> set[str]:
    return {p["company_id"] for p in rfq["participants"] if p["side"] == side}


def rfq_for(user: User, rfq_id: str, orch: Orchestrator) -> dict:
    """Load an RFQ the caller may see. Others get 404, not 403, so ids don't leak."""
    rfq = guard(lambda: orch.get_rfq(rfq_id))
    if user.role == "buyer" and rfq["buyer_company_id"] == user.company_id:
        return rfq
    if user.role == "seller" and user.company_id in participant_ids(rfq, "seller") \
            and rfq["status"] != "draft":
        return rfq
    raise HTTPException(404, "RFQ not found")
