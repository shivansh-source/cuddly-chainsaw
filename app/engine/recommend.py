"""Recommendation engine: eligibility -> landed cost -> weighted score -> explanation.

Policy on missing data:
  * Hard-constraint data (MOQ, stock, lead time, a required spec) that is
    unknown FAILS eligibility, because the constraint cannot be verified.
  * Soft data (reliability, initial quote) that is unknown scores 0 on that
    criterion and is flagged. Missing data never scores well.
"""
from app.engine.models import (
    LineQuote, RankedOffer, Recommendation, RfqLineReq, SupplierQuote,
)
from app.specs import check_specs

WEIGHTS = {"cost": 0.50, "delivery": 0.20, "reliability": 0.15, "improvement": 0.15}
DEADLINE_BUFFER_RATIO = 0.5   # lead time within half the deadline scores 100
IMPROVEMENT_CAP = 0.20        # a 20% negotiated improvement scores 100


def landed_cost(line: LineQuote) -> float:
    """(unit_price x qty) + tax + shipping - discounts."""
    goods = line.unit_price * line.qty
    return round(goods + goods * line.tax_rate + line.shipping - line.discount, 2)


def check_eligibility(
    required: list[RfqLineReq], quote: SupplierQuote, deadline_days: int
) -> tuple[list[str], list[str]]:
    """Return (failures, warnings). Any failure makes the offer ineligible."""
    failures: list[str] = []
    warnings: list[str] = []
    by_mpn = {ln.mpn: ln for ln in quote.lines}
    for req in required:
        ln = by_mpn.get(req.mpn)
        if ln is None:
            failures.append(f"{req.mpn}: not offered")
            continue
        if ln.qty < req.qty:
            failures.append(f"{req.mpn}: quantity {ln.qty} does not cover required {req.qty}")
        if ln.moq is None:
            failures.append(f"{req.mpn}: MOQ not specified")
        elif req.qty < ln.moq:
            failures.append(f"{req.mpn}: required {req.qty} below MOQ {ln.moq}")
        if ln.stock_qty is None:
            failures.append(f"{req.mpn}: stock not specified")
        elif ln.stock_qty < req.qty:
            failures.append(f"{req.mpn}: stock {ln.stock_qty} below required {req.qty}")
        if ln.lead_time_days is None:
            failures.append(f"{req.mpn}: lead time not specified")
        elif ln.lead_time_days > deadline_days:
            failures.append(
                f"{req.mpn}: lead time {ln.lead_time_days}d beyond deadline {deadline_days}d"
            )
        for reason in check_specs(ln.specs, req.required_specs):
            (failures if req.mandatory else warnings).append(f"{req.mpn}: {reason}")
    return failures, warnings


def delivery_score(lead_days: int | None, deadline_days: int) -> float:
    if lead_days is None:
        return 0.0
    buffer_days = deadline_days * DEADLINE_BUFFER_RATIO
    if lead_days <= buffer_days:
        return 100.0
    span = deadline_days - buffer_days
    if span <= 0 or lead_days >= deadline_days:
        return 0.0
    return round(100.0 * (deadline_days - lead_days) / span, 2)


def improvement_pct(quote: SupplierQuote) -> float | None:
    """Value-weighted improvement vs the same-qty initial quote, or None if
    any initial quote is missing (never compare against an unlabeled price)."""
    initial = final = 0.0
    for ln in quote.lines:
        if ln.initial_unit_price is None:
            return None
        initial += ln.initial_unit_price * ln.qty
        final += ln.unit_price * ln.qty
    if initial <= 0:
        return None
    return round((initial - final) / initial, 4)


def _explain(
    offer: RankedOffer, lowest_cost: float, qty_lead: int | None
) -> str:
    parts: list[str] = []
    if offer.landed_cost is not None:
        if offer.landed_cost <= lowest_cost:
            parts.append("Lowest landed cost")
        else:
            over = 100 * (offer.landed_cost - lowest_cost) / lowest_cost
            parts.append(f"Landed cost {over:.0f}% above the lowest eligible offer")
    if qty_lead is not None:
        parts.append(f"{qty_lead}-day delivery")
    if offer.improvement_pct is not None and offer.improvement_pct > 0:
        parts.append(f"negotiated {offer.improvement_pct * 100:.0f}% below initial quote")
    if offer.flags:
        parts.append("flags: " + "; ".join(offer.flags))
    return "; ".join(parts)


def recommend(
    required: list[RfqLineReq], quotes: list[SupplierQuote], deadline_days: int
) -> Recommendation:
    evaluated: list[tuple[SupplierQuote, list[str], list[str]]] = []
    for q in quotes:
        failures, warnings = check_eligibility(required, q, deadline_days)
        evaluated.append((q, failures, warnings))

    def _total(q: SupplierQuote) -> float:
        wanted = {r.mpn for r in required}
        return round(sum(landed_cost(ln) for ln in q.lines if ln.mpn in wanted), 2)

    def _lead(q: SupplierQuote) -> int | None:
        leads = [ln.lead_time_days for ln in q.lines]
        return None if not leads or any(v is None for v in leads) else max(leads)  # type: ignore[type-var]

    eligible = [(q, w) for q, f, w in evaluated if not f]
    lowest = min((_total(q) for q, _ in eligible), default=0.0)

    ranked: list[RankedOffer] = []
    for q, warnings in eligible:
        cost = _total(q)
        lead = _lead(q)
        imp = improvement_pct(q)
        flags = list(warnings)
        if q.reliability_score is None:
            flags.append("reliability unknown (scored 0)")
        if imp is None:
            flags.append("no initial quote to compare (improvement scored 0)")

        cost_score = round(min(100.0, 100.0 * lowest / cost), 2) if cost > 0 else 0.0
        breakdown = {
            "cost": cost_score,
            "delivery": delivery_score(lead, deadline_days),
            "reliability": round(float(q.reliability_score or 0.0), 2),
            "improvement": (
                round(min(100.0, 100.0 * max(imp, 0.0) / IMPROVEMENT_CAP), 2)
                if imp is not None else 0.0
            ),
        }
        total = round(sum(breakdown[k] * w for k, w in WEIGHTS.items()), 2)
        offer = RankedOffer(
            company_id=q.company_id, name=q.name, source=q.source, eligible=True,
            landed_cost=cost, lead_time_days=lead, total_score=total,
            breakdown=breakdown, improvement_pct=imp, flags=flags,
        )
        offer.explanation = _explain(offer, lowest, lead)
        ranked.append(offer)

    # Deterministic order: score desc, then cheaper, then id.
    ranked.sort(key=lambda o: (-(o.total_score or 0), o.landed_cost or 0, o.company_id))

    rejected: list[RankedOffer] = []
    for q, failures, warnings in evaluated:
        if failures:
            rejected.append(RankedOffer(
                company_id=q.company_id, name=q.name, source=q.source, eligible=False,
                landed_cost=_total(q), lead_time_days=_lead(q),
                eligibility_failures=failures, flags=warnings,
                explanation="Not eligible: " + "; ".join(failures),
            ))
    rejected.sort(key=lambda o: o.company_id)
    return Recommendation(ranked=ranked, rejected=rejected)
