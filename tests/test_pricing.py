import pytest

from app.engine.models import PricingRule, Tier
from app.engine.pricing import (
    buyer_bid, buyer_limits, round_price, tier_discount, tier_price,
)

TIERS = [Tier(min_qty=50, discount_pct=0.02), Tier(min_qty=100, discount_pct=0.05),
         Tier(min_qty=500, discount_pct=0.08)]
RULE = PricingRule(mpn="ESP32-WROOM-32E", list_price=360, floor_price=295,
                   tiers=TIERS, concession_step_pct=0.25, max_rounds=3)


def test_tier_picks_best_reached_discount():
    assert tier_discount(TIERS, 10) == 0
    assert tier_discount(TIERS, 50) == 0.02
    assert tier_discount(TIERS, 120) == 0.05
    assert tier_discount(TIERS, 5000) == 0.08


def test_tier_applies_before_concession():
    assert tier_price(RULE, 100) == 342.0  # 360 * 0.95


def test_concession_schedule_moves_toward_floor():
    # gap = 342 - 295 = 47; step 25% of gap per round
    assert [round_price(RULE, 100, r) for r in range(4)] == [342.0, 330.25, 318.5, 306.75]


def test_never_below_floor_even_far_past_max_rounds():
    assert round_price(RULE, 100, 50) == 295.0


def test_floor_wins_when_tier_price_is_under_floor():
    rule = PricingRule(mpn="X", list_price=100, floor_price=98,
                       tiers=[Tier(min_qty=1, discount_pct=0.10)], concession_step_pct=0.5)
    assert round_price(rule, 10, 0) == 98.0


def test_schedule_is_deterministic_and_non_increasing():
    first = [round_price(RULE, 100, r) for r in range(6)]
    assert first == [round_price(RULE, 100, r) for r in range(6)]
    assert first == sorted(first, reverse=True)


def test_floor_above_list_rejected():
    with pytest.raises(ValueError):
        PricingRule(mpn="X", list_price=10, floor_price=20, concession_step_pct=0.1)


def test_buyer_limits_respect_budget_and_target_below_ceiling():
    lines = [("A", 100, 360.0), ("B", 100, 430.0), ("C", 200, 19.0)]
    limits = buyer_limits(93000, "landed_incl_tax", 0.18, lines)
    pre_tax = 93000 / 1.18
    total_at_ceiling = sum(limits[m].ceiling * q for m, q, _ in lines)
    assert total_at_ceiling == pytest.approx(pre_tax, rel=1e-3)
    for lim in limits.values():
        assert lim.target <= lim.ceiling


def test_buyer_bid_rises_to_but_never_exceeds_ceiling():
    limits = buyer_limits(93000, "landed_incl_tax", 0.18, [("A", 100, 360.0)])
    lim = limits["A"]
    bids = [buyer_bid(lim, r, 3) for r in range(8)]
    assert bids[0] == lim.target
    assert bids == sorted(bids)
    assert max(bids) <= lim.ceiling
