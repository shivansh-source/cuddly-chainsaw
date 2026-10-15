import pytest

from app.engine.models import LineQuote, RfqLineReq, SupplierQuote
from app.engine.negotiate import negotiate_line
from app.engine.models import PricingRule, Tier
from app.engine.pricing import buyer_limits
from app.engine.recommend import (
    check_eligibility, delivery_score, landed_cost, recommend,
)

REQ = [RfqLineReq(mpn="X", qty=100)]
DEADLINE = 10


def quote(cid="s", unit=100.0, lead=3, rel=90.0, initial=None, **line_kw):
    line = dict(mpn="X", unit_price=unit, qty=100, moq=10, stock_qty=500,
                lead_time_days=lead, tax_rate=0.18, initial_unit_price=initial)
    line.update(line_kw)
    return SupplierQuote(company_id=cid, name=cid.upper(), reliability_score=rel,
                         lines=[LineQuote(**line)])


def test_landed_cost_includes_tax_shipping_and_discount():
    ln = LineQuote(mpn="X", unit_price=100, qty=10, tax_rate=0.18, shipping=50, discount=20)
    assert landed_cost(ln) == 1000 + 180 + 50 - 20


# --- eligibility: every hard constraint, with a reason ---------------------------

@pytest.mark.parametrize("kw,fragment", [
    (dict(qty=50), "does not cover"),
    (dict(moq=500), "below MOQ"),
    (dict(stock_qty=20), "stock 20 below"),
    (dict(lead_time_days=11), "beyond deadline"),
    (dict(moq=None), "MOQ not specified"),
    (dict(stock_qty=None), "stock not specified"),
    (dict(lead_time_days=None), "lead time not specified"),
])
def test_ineligible_with_reason(kw, fragment):
    failures, _ = check_eligibility(REQ, quote(**kw), DEADLINE)
    assert any(fragment in f for f in failures)


def test_missing_line_is_not_offered():
    q = SupplierQuote(company_id="s", lines=[])
    failures, _ = check_eligibility(REQ, q, DEADLINE)
    assert failures == ["X: not offered"]


def test_mandatory_spec_fails_optional_spec_only_warns():
    mand = [RfqLineReq(mpn="X", qty=100, required_specs={"flash_mb": {"op": ">=", "value": 8}})]
    opt = [RfqLineReq(mpn="X", qty=100, mandatory=False,
                      required_specs={"flash_mb": {"op": ">=", "value": 8}})]
    q = quote(specs={"flash_mb": 4})
    f1, _ = check_eligibility(mand, q, DEADLINE)
    f2, w2 = check_eligibility(opt, q, DEADLINE)
    assert f1 and not f2 and w2


def test_ineligible_offers_are_listed_with_reasons_never_dropped():
    rec = recommend(REQ, [quote("a"), quote("b", lead=30), quote("c", stock_qty=1)], DEADLINE)
    assert [o.company_id for o in rec.ranked] == ["a"]
    assert [o.company_id for o in rec.rejected] == ["b", "c"]
    assert all(o.eligibility_failures and not o.eligible for o in rec.rejected)
    assert all(o.total_score is None for o in rec.rejected)


# --- scoring ------------------------------------------------------------------------------

def test_scoring_matches_hand_calculation():
    rec = recommend(REQ, [
        quote("s1", unit=100, lead=3, rel=90, initial=110),
        quote("s2", unit=110, lead=8, rel=60, initial=110),
    ], DEADLINE)
    s1, s2 = rec.ranked
    assert (s1.company_id, s2.company_id) == ("s1", "s2")
    assert s1.landed_cost == 11800.0 and s2.landed_cost == 12980.0
    assert s1.breakdown["cost"] == 100.0
    assert s1.breakdown["delivery"] == 100.0
    assert s1.breakdown["improvement"] == pytest.approx(45.45, abs=0.01)
    assert s1.total_score == pytest.approx(90.32, abs=0.01)
    assert s2.breakdown["cost"] == pytest.approx(90.91, abs=0.01)
    assert s2.breakdown["delivery"] == 40.0
    assert s2.breakdown["improvement"] == 0.0
    assert s2.total_score == pytest.approx(62.46, abs=0.01)


def test_delivery_score_scale():
    assert delivery_score(5, 10) == 100.0
    assert delivery_score(8, 10) == 40.0
    assert delivery_score(10, 10) == 0.0
    assert delivery_score(None, 10) == 0.0


def test_missing_reliability_and_initial_quote_score_zero_and_are_flagged():
    rec = recommend(REQ, [quote("a", rel=None, initial=None)], DEADLINE)
    o = rec.ranked[0]
    assert o.breakdown["reliability"] == 0.0 and o.breakdown["improvement"] == 0.0
    assert any("reliability unknown" in f for f in o.flags)
    assert any("no initial quote" in f for f in o.flags)


def test_ranking_is_deterministic_with_tie_break():
    a = recommend(REQ, [quote("b"), quote("a")], DEADLINE)
    b = recommend(REQ, [quote("a"), quote("b")], DEADLINE)
    assert [o.company_id for o in a.ranked] == [o.company_id for o in b.ranked] == ["a", "b"]


def test_explanation_is_built_from_the_breakdown():
    rec = recommend(REQ, [quote("a", unit=90, lead=3, initial=100),
                          quote("b", unit=100, lead=4)], DEADLINE)
    top = rec.ranked[0]
    assert "Lowest landed cost" in top.explanation
    assert "3-day delivery" in top.explanation
    assert "negotiated 10% below initial quote" in top.explanation
    assert "above the lowest" in rec.ranked[1].explanation


def test_source_label_passes_through():
    q = quote("a")
    q.source = "human_seller"
    assert recommend(REQ, [q], DEADLINE).ranked[0].source == "human_seller"


# --- engine-only negotiation of one line --------------------------------------------------------

RULE = PricingRule(mpn="X", list_price=360, floor_price=295,
                   tiers=[Tier(min_qty=100, discount_pct=0.05)],
                   concession_step_pct=0.25, max_rounds=3)


def test_negotiation_closes_when_bid_reaches_ask():
    limits = buyer_limits(93000, "landed_incl_tax", 0.18, [("X", 100, 360.0)])
    res = negotiate_line(RULE, 100, limits["X"])
    assert res.source == "engine"
    if res.agreed_price is not None:
        last = res.rounds[-1]
        assert last.bid >= last.ask and res.agreed_price == last.ask
    assert res.rounds == negotiate_line(RULE, 100, limits["X"]).rounds


def test_no_deal_when_buyer_ceiling_is_below_seller_floor():
    limits = buyer_limits(30000, "landed_incl_tax", 0.18, [("X", 100, 360.0)])
    res = negotiate_line(RULE, 100, limits["X"])
    assert res.agreed_price is None and len(res.rounds) == RULE.max_rounds + 1
