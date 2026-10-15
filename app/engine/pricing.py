"""Deterministic pricing: concession schedule, buyer limits, fallback moves.

Same inputs always give the same outputs. No LLM, no randomness.
"""
from app.engine.models import (
    Action, BuyerLimit, PricingRule, Tier,
)


def tier_discount(tiers: list[Tier], qty: int) -> float:
    """Best discount among tiers whose min_qty the quantity reaches."""
    return max((t.discount_pct for t in tiers if qty >= t.min_qty), default=0.0)


def tier_price(rule: PricingRule, qty: int) -> float:
    return round(rule.list_price * (1 - tier_discount(rule.tiers, qty)), 2)


def round_price(rule: PricingRule, qty: int, rnd: int) -> float:
    """Seller's ask in a given round.

    Quantity tier applies first. Each round the price moves from the tier
    price toward the floor by `concession_step_pct` of the remaining gap
    (tier price - floor), and never goes below the floor. Round 0 is the
    opening quote.
    """
    base = tier_price(rule, qty)
    gap = max(0.0, base - rule.floor_price)
    fraction = min(1.0, rule.concession_step_pct * max(rnd, 0))
    return round(max(rule.floor_price, base - gap * fraction), 2)


def buyer_limits(
    budget: float,
    budget_basis: str,
    tax_rate: float,
    lines: list[tuple[str, int, float]],
    target_discount: float = 0.10,
) -> dict[str, BuyerLimit]:
    """Per-line target and hard ceiling, from the buyer's own budget.

    `lines` is (mpn, qty, reference_price). The reference is something the
    buyer legitimately knows, such as the sellers' opening quotes, never a
    seller's floor. The pre-tax budget is split across lines in proportion to
    reference value, which gives each line a ceiling; the target is a
    `target_discount` below the reference, capped by that ceiling.
    """
    pre_tax = budget / (1 + tax_rate) if budget_basis == "landed_incl_tax" else budget
    reference_total = sum(qty * ref for _, qty, ref in lines)
    if reference_total <= 0:
        raise ValueError("reference total must be positive")
    ratio = pre_tax / reference_total
    out: dict[str, BuyerLimit] = {}
    for mpn, _qty, ref in lines:
        ceiling = round(ref * ratio, 2)
        target = round(min(ceiling, ref * (1 - target_discount)), 2)
        out[mpn] = BuyerLimit(mpn=mpn, target=target, ceiling=ceiling)
    return out


def buyer_bid(limit: BuyerLimit, rnd: int, max_rounds: int) -> float:
    """Buyer's deterministic bid: opens at target, rises linearly to the
    ceiling by the final round, and never exceeds the ceiling."""
    fraction = min(1.0, max(rnd, 0) / max(max_rounds, 1))
    bid = limit.target + (limit.ceiling - limit.target) * fraction
    return round(min(bid, limit.ceiling), 2)


def seller_fallback_action(rule: PricingRule, qty: int, rnd: int) -> Action:
    """What a seller agent says if the LLM output is invalid twice."""
    return Action(
        type="counter", mpn=rule.mpn, qty=qty,
        unit_price=round_price(rule, qty, rnd),
        message="Deterministic concession per pricing policy.",
    )


def buyer_fallback_action(limit: BuyerLimit, qty: int, rnd: int, max_rounds: int) -> Action:
    return Action(
        type="counter", mpn=limit.mpn, qty=qty,
        unit_price=buyer_bid(limit, rnd, max_rounds),
        message="Deterministic counter within budget.",
    )
