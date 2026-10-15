"""Engine-only negotiation of one line, used as the deterministic baseline
and as the fallback path when the LLM layer is unavailable."""
from pydantic import BaseModel

from app.engine.models import BuyerLimit, PricingRule, Source
from app.engine.pricing import buyer_bid, round_price


class RoundRecord(BaseModel):
    round: int
    ask: float
    bid: float


class LineResult(BaseModel):
    rounds: list[RoundRecord]
    agreed_price: float | None
    agreed_round: int | None
    source: Source = "engine"


def negotiate_line(rule: PricingRule, qty: int, limit: BuyerLimit) -> LineResult:
    """Run rounds 0..max_rounds. A deal closes at the seller's ask the first
    time the buyer's bid reaches it. Otherwise there is no deal."""
    history: list[RoundRecord] = []
    for rnd in range(rule.max_rounds + 1):
        ask = round_price(rule, qty, rnd)
        bid = buyer_bid(limit, rnd, rule.max_rounds)
        history.append(RoundRecord(round=rnd, ask=ask, bid=bid))
        if bid >= ask:
            return LineResult(rounds=history, agreed_price=ask, agreed_round=rnd)
    return LineResult(rounds=history, agreed_price=None, agreed_round=None)
