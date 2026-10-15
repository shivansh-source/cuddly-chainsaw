"""Round loop, turn order, controller switching and persistence.

Every move becomes a `turns` document (audit trail). Every move that carries a
usable number also becomes an append-only `offers` document labeled with its
source. Thread state is derived from those collections, never edited in place.
"""
from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId
from pymongo.database import Database

from app.engine.guardrail import confirm_override, validate_action
from app.engine.models import (
    Action, BuyerAuthority, BuyerLimit, GuardrailResult, LineQuote, Participant,
    PricingRule,
    RfqLineReq, SellerAuthority, SupplierQuote,
)
from app.engine.pricing import (
    buyer_bid, buyer_limits, round_price, tier_price,
)
from app.engine.recommend import recommend
from app.llm import prompts
from app.llm.base import LLMClient
from app.negotiation.agents import AgentOutcome, decide_action

DEFAULT_MAX_ROUNDS = 3
OFFER_VALID_DAYS = 7
COUNTING = ("proposed", "accepted", "confirmed")


class NegotiationError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Orchestrator:
    def __init__(self, db: Database, llm: LLMClient | None = None):
        self.db = db
        self.llm = llm

    def _llm_for(self, rfq: dict) -> LLMClient | None:
        """An RFQ flagged engine_only never calls the model: fully deterministic."""
        return None if rfq.get("engine_only") else self.llm

    # ------------------------------------------------------------------ lookups
    def get_rfq(self, rfq_id: str) -> dict:
        rfq = self.db.rfqs.find_one({"_id": rfq_id})
        if not rfq:
            raise NegotiationError("RFQ not found", 404)
        return rfq

    def _participant(self, rfq: dict, company_id: str) -> Participant:
        for p in rfq["participants"]:
            if p["company_id"] == company_id:
                return Participant(company_id=company_id, side=p["side"],
                                   controller=p["controller"])
        raise NegotiationError(f"{company_id} is not a participant", 404)

    def _buyer(self, rfq: dict) -> Participant:
        p = next(p for p in rfq["participants"] if p["side"] == "buyer")
        return Participant(company_id=p["company_id"], side="buyer", controller=p["controller"])

    def _sellers(self, rfq: dict) -> list[Participant]:
        return [Participant(company_id=p["company_id"], side="seller",
                            controller=p["controller"])
                for p in rfq["participants"]
                if p["side"] == "seller" and p.get("status") != "declined"]

    def _supply(self, company_id: str, mpn: str) -> tuple[PricingRule, dict] | None:
        rule = self.db.pricing_rules.find_one({"company_id": company_id, "mpn": mpn})
        cat = self.db.catalog_items.find_one({"company_id": company_id, "mpn": mpn})
        if not rule or not cat:
            return None
        return PricingRule(**rule), cat

    def _max_rounds(self, rfq: dict) -> int:
        return int(rfq.get("max_rounds", DEFAULT_MAX_ROUNDS))

    # ---------------------------------------------------------------- thread state
    def _latest(self, rfq_id: str, company_id: str, mpn: str, side: str) -> dict | None:
        return self.db.offers.find_one(
            {"rfq_id": rfq_id, "company_id": company_id, "mpn": mpn, "side": side,
             "status": {"$in": list(COUNTING)}},
            sort=[("round", -1), ("version", -1)],
        )

    def _agreed(self, rfq_id: str, company_id: str, mpn: str) -> dict | None:
        return self.db.offers.find_one(
            {"rfq_id": rfq_id, "company_id": company_id, "mpn": mpn, "status": "accepted"})

    def _walked(self, rfq_id: str, company_id: str, mpn: str) -> bool:
        return self.db.turns.count_documents(
            {"rfq_id": rfq_id, "participant_id": company_id, "mpn": mpn,
             "validated_action.type": "walk_away"}) > 0

    def _open(self, rfq_id: str, company_id: str, mpn: str) -> bool:
        return not self._agreed(rfq_id, company_id, mpn) and not self._walked(rfq_id, company_id, mpn)

    def _has_move(self, rfq_id, company_id, mpn, side, rnd) -> bool:
        return self.db.offers.count_documents(
            {"rfq_id": rfq_id, "company_id": company_id, "mpn": mpn,
             "side": side, "round": rnd}) > 0

    # ---------------------------------------------------------------- persistence
    def _log_turn(self, rfq_id, rnd, actor: Participant, counterparty: str, mpn: str,
                  action: Action | None, guard: GuardrailResult | dict, source: str,
                  raw: str | None = None, attempts: int = 0, notes=None,
                  extra: dict | None = None) -> str:
        doc = {**(extra or {}),
            "rfq_id": rfq_id, "round": rnd, "participant_id": actor.company_id,
            "counterparty_id": counterparty, "side": actor.side, "mpn": mpn,
            "controller": actor.controller, "source": source,
            "raw_llm_output": raw,
            "validated_action": action.model_dump() if action else None,
            "guardrail_result": guard.model_dump() if isinstance(guard, GuardrailResult) else guard,
            "message": action.message if action else "",
            "attempts": attempts, "notes": notes or [], "created_at": _now(),
        }
        return str(self.db.turns.insert_one(doc).inserted_id)

    def _log_offer(self, rfq_id, rnd, company_id, side, mpn, price, qty, lead, tax_rate,
                   source, status, turn_id, created_by, extra: dict | None = None) -> dict:
        version = self.db.offers.count_documents(
            {"rfq_id": rfq_id, "company_id": company_id, "mpn": mpn, "side": side}) + 1
        goods = price * qty
        doc = {**(extra or {}),
            "rfq_id": rfq_id, "company_id": company_id, "mpn": mpn, "side": side,
            "round": rnd, "version": version, "unit_price": float(price), "qty": int(qty),
            "lead_time_days": lead, "tax_rate": tax_rate,
            "tax": round(goods * tax_rate, 2), "shipping": 0.0,
            "total_landed_cost": round(goods * (1 + tax_rate), 2),
            "valid_until": _now() + timedelta(days=OFFER_VALID_DAYS),
            "source": source, "status": status, "created_by": created_by,
            "turn_id": turn_id, "created_at": _now(),
        }
        self.db.offers.insert_one(doc)
        return doc

    # -------------------------------------------------------------------- limits
    def ensure_limits(self, rfq: dict) -> dict[str, dict] | None:
        """Buyer's per-line target/ceiling. Computed once from the round-0
        seller asks (public to the buyer), never from a seller's floor."""
        if rfq.get("buyer_limits"):
            return rfq["buyer_limits"]
        refs: list[tuple[str, int, float]] = []
        for line in rfq["lines"]:
            asks = [o["unit_price"] for o in self.db.offers.find(
                {"rfq_id": rfq["_id"], "mpn": line["mpn"], "side": "seller", "round": 0,
                 "status": {"$in": list(COUNTING)}})]
            if not asks:
                return None
            refs.append((line["mpn"], line["qty"], sum(asks) / len(asks)))
        limits = buyer_limits(rfq["budget"], rfq["budget_basis"], 0.18, refs)
        stored = {m: {"target": v.target, "ceiling": v.ceiling} for m, v in limits.items()}
        self.db.rfqs.update_one({"_id": rfq["_id"]}, {"$set": {"buyer_limits": stored}})
        rfq["buyer_limits"] = stored
        return stored

    # ----------------------------------------------------------------- agent moves
    def _seller_authority(self, cat: dict) -> SellerAuthority:
        return SellerAuthority(
            mpn=cat["mpn"], floor_price=0.0, moq=cat["moq"], stock_qty=cat["stock_qty"],
            lead_time_days=cat["lead_time_days"], deadline_days=None)

    def seller_move(self, rfq: dict, seller: Participant, line: dict, rnd: int) -> dict | None:
        rfq_id, mpn = rfq["_id"], line["mpn"]
        if self._has_move(rfq_id, seller.company_id, mpn, "seller", rnd):
            return None
        supply = self._supply(seller.company_id, mpn)
        if supply is None:
            return None
        rule, cat = supply
        qty = max(cat["moq"], min(line["qty"], cat["stock_qty"]))
        if cat["stock_qty"] < cat["moq"]:
            return None
        auth = self._seller_authority(cat).model_copy(update={"floor_price": rule.floor_price})
        policy = round_price(rule, qty, rnd)
        fallback = Action(type="counter", mpn=mpn, qty=qty, unit_price=policy,
                          lead_time_days=cat["lead_time_days"],
                          message="Concession per pricing policy.")
        last_bid = self._latest(rfq_id, seller.company_id, mpn, "buyer")
        ctx = dict(mpn=mpn, qty=qty, round=rnd, max_rounds=self._max_rounds(rfq),
                   list_price=rule.list_price, tier_price=tier_price(rule, qty),
                   floor_price=rule.floor_price, policy_price=policy,
                   stock_qty=cat["stock_qty"], lead_time_days=cat["lead_time_days"],
                   deadline_days=rfq["deadline_days"],
                   buyer_last_bid=last_bid["unit_price"] if last_bid else None)
        outcome = decide_action(self._llm_for(rfq), prompts.seller_system(), prompts.seller_user(ctx),
                                seller, auth, fallback, mpn, qty)
        return self._apply(rfq, seller, rnd, mpn, outcome, cat["tax_rate"],
                           cat["lead_time_days"], rfq["buyer_company_id"])

    def buyer_move(self, rfq: dict, seller_id: str, line: dict, rnd: int,
                   force: bool = False) -> dict | None:
        """Buyer agent's answer on one thread. `force` re-answers within the
        same round, used when a human seller posts a fresh ask."""
        rfq_id, mpn = rfq["_id"], line["mpn"]
        if not self._open(rfq_id, seller_id, mpn):
            return None
        if not force and self._has_move(rfq_id, seller_id, mpn, "buyer", rnd):
            return None
        limits = self.ensure_limits(rfq)
        ask = self._latest(rfq_id, seller_id, mpn, "seller")
        if not limits or not ask:
            return None
        buyer = self._buyer(rfq)
        lim = limits[mpn]
        limit = BuyerLimit(mpn=mpn, **lim)
        policy = buyer_bid(limit, rnd, self._max_rounds(rfq))
        if ask["unit_price"] <= policy:
            return self._accept(rfq, buyer, seller_id, mpn, ask, rnd, "engine", None)
        auth = BuyerAuthority(mpn=mpn, line_qty=line["qty"], max_unit_price=limit.ceiling)
        fallback = Action(type="counter", mpn=mpn, qty=line["qty"], unit_price=policy,
                          message="Counter within budget.")
        ctx = dict(mpn=mpn, qty=line["qty"], round=rnd, max_rounds=self._max_rounds(rfq),
                   target=limit.target, ceiling=limit.ceiling, policy_bid=policy,
                   seller_ask=ask["unit_price"], deadline_days=rfq["deadline_days"])
        outcome = decide_action(self._llm_for(rfq), prompts.buyer_system(), prompts.buyer_user(ctx),
                                buyer, auth, fallback, mpn, line["qty"])
        bid = self._apply(rfq, buyer, rnd, mpn, outcome, 0.18, None, seller_id)
        if bid and bid["unit_price"] >= ask["unit_price"]:
            self._accept(rfq, buyer, seller_id, mpn, ask, rnd, bid["source"], bid["turn_id"])
        return bid

    def _apply(self, rfq, actor: Participant, rnd, mpn, outcome: AgentOutcome,
               tax_rate, lead, counterparty) -> dict | None:
        """Persist an agent outcome. Only guardrail-approved numbers become offers."""
        rfq_id = rfq["_id"]
        company = actor.company_id if actor.side == "seller" else counterparty
        turn_id = self._log_turn(rfq_id, rnd, actor, counterparty, mpn, outcome.action,
                                 outcome.guard, outcome.source, outcome.raw_llm_output,
                                 outcome.attempts, outcome.notes)
        a = outcome.action
        if not outcome.guard.counts or a.type == "walk_away" or a.unit_price is None:
            return None
        return self._log_offer(rfq_id, rnd, company, actor.side, mpn, a.unit_price, a.qty,
                               a.lead_time_days or lead, tax_rate, outcome.source,
                               "proposed", turn_id, f"{actor.side}:{actor.company_id}")

    def _accept(self, rfq, accepter: Participant, seller_id, mpn, standing: dict, rnd,
                source, turn_id) -> dict:
        """Close a thread at the standing counterparty price."""
        action = Action(type="accept", mpn=mpn, unit_price=standing["unit_price"],
                        qty=standing["qty"], message="Accepted standing offer.")
        tid = turn_id or self._log_turn(
            rfq["_id"], rnd, accepter, standing["company_id"], mpn, action,
            GuardrailResult(status="ok"), source)
        return self._log_offer(
            rfq["_id"], rnd, seller_id, accepter.side, mpn, standing["unit_price"],
            standing["qty"], standing.get("lead_time_days"), standing.get("tax_rate", 0.18),
            source, "accepted", tid, f"{accepter.side}:{accepter.company_id}")

    # -------------------------------------------------------------------- rounds
    def step_round(self, rfq: dict, rnd: int) -> None:
        sellers = self._sellers(rfq)
        for s in sellers:
            if s.controller != "agent":
                continue
            for line in rfq["lines"]:
                if self._open(rfq["_id"], s.company_id, line["mpn"]):
                    self.seller_move(rfq, s, line, rnd)
        if self._buyer(rfq).controller == "agent":
            for s in sellers:
                for line in rfq["lines"]:
                    self.buyer_move(rfq, s.company_id, line, rnd)
        self.db.rfqs.update_one({"_id": rfq["_id"]}, {"$set": {"round": rnd}})
        rfq["round"] = rnd

    def start(self, rfq_id: str, engine_only: bool = False) -> dict:
        rfq = self.get_rfq(rfq_id)
        if rfq["status"] not in ("draft", "open"):
            raise NegotiationError(f"RFQ is {rfq['status']}, cannot start")
        self.db.rfqs.update_one({"_id": rfq_id}, {"$set": {
            "status": "negotiating", "engine_only": engine_only}})
        rfq["status"] = "negotiating"
        rfq["engine_only"] = engine_only
        self.step_round(rfq, 0)
        return rfq

    def next_round(self, rfq_id: str) -> dict:
        rfq = self.get_rfq(rfq_id)
        if rfq["status"] != "negotiating":
            raise NegotiationError(f"RFQ is {rfq['status']}, not negotiating")
        rnd = rfq["round"] + 1
        if rnd > self._max_rounds(rfq):
            raise NegotiationError("all rounds are complete; finalize instead")
        self.step_round(rfq, rnd)
        return rfq

    def run_all(self, rfq_id: str, engine_only: bool = False) -> dict:
        rfq = self.start(rfq_id, engine_only)
        while rfq["round"] < self._max_rounds(rfq):
            self.step_round(rfq, rfq["round"] + 1)
        return self.finalize(rfq_id)

    # ------------------------------------------------------------- recommendation
    def _quotes(self, rfq: dict) -> list[SupplierQuote]:
        quotes: list[SupplierQuote] = []
        for s in self._sellers(rfq):
            company = self.db.companies.find_one({"_id": s.company_id}) or {}
            lines: list[LineQuote] = []
            for line in rfq["lines"]:
                mpn = line["mpn"]
                final = self._agreed(rfq["_id"], s.company_id, mpn) \
                    or self._latest(rfq["_id"], s.company_id, mpn, "seller")
                if final is None:
                    continue
                initial = self.db.offers.find_one(
                    {"rfq_id": rfq["_id"], "company_id": s.company_id, "mpn": mpn,
                     "side": "seller", "round": 0, "status": {"$in": list(COUNTING)}},
                    sort=[("version", 1)])
                cat = self.db.catalog_items.find_one(
                    {"company_id": s.company_id, "mpn": mpn}) or {}
                src_offer = self._latest(rfq["_id"], s.company_id, mpn, "seller") or final
                lines.append(LineQuote(
                    mpn=mpn, unit_price=final["unit_price"], qty=final["qty"],
                    source=src_offer["source"],
                    moq=cat.get("moq"), stock_qty=cat.get("stock_qty"),
                    lead_time_days=final.get("lead_time_days", cat.get("lead_time_days")),
                    tax_rate=final.get("tax_rate", cat.get("tax_rate", 0.0)),
                    specs=cat.get("specs", {}),
                    initial_unit_price=initial["unit_price"] if initial else None))
            quotes.append(SupplierQuote(
                company_id=s.company_id, name=company.get("name", ""),
                reliability_score=company.get("reliability_score"),
                lines=lines))
        return quotes

    def finalize(self, rfq_id: str) -> dict:
        rfq = self.get_rfq(rfq_id)
        required = [RfqLineReq(**{k: ln[k] for k in ("mpn", "qty", "required_specs", "mandatory")})
                    for ln in rfq["lines"]]
        rec = recommend(required, self._quotes(rfq), rfq["deadline_days"])
        if rec.ranked:
            top = rec.ranked[0]
            summary = (f"{len(rec.ranked)} of {len(rec.ranked) + len(rec.rejected)} suppliers "
                       f"eligible. Top: {top.name or top.company_id} - {top.explanation}.")
        else:
            summary = "No eligible supplier. See rejection reasons."
        doc = {"rfq_id": rfq_id, "ranked": [o.model_dump() for o in rec.ranked],
               "rejected": [o.model_dump() for o in rec.rejected],
               "explanation": summary, "created_at": _now()}
        self.db.recommendations.insert_one(doc)
        self.db.rfqs.update_one({"_id": rfq_id}, {"$set": {"status": "completed"}})
        doc.pop("_id", None)
        return doc

    # ------------------------------------------------------------------ humans
    def handover(self, rfq_id: str, company_id: str, controller: str) -> dict:
        rfq = self.get_rfq(rfq_id)
        actor = self._participant(rfq, company_id)
        if actor.controller == controller:
            raise NegotiationError(f"{company_id} is already controlled by {controller}")
        self.db.rfqs.update_one(
            {"_id": rfq_id, "participants.company_id": company_id},
            {"$set": {"participants.$.controller": controller}})
        self._log_turn(rfq_id, rfq["round"], actor.with_controller(controller),
                       "", "", None,
                       {"event": "controller_switch", "from": actor.controller, "to": controller},
                       "engine")
        return {"company_id": company_id, "controller": controller}

    def human_seller_turn(self, rfq_id: str, company_id: str, mpn: str, action: Action) -> dict:
        rfq = self.get_rfq(rfq_id)
        self._require_negotiating(rfq)
        actor = self._participant(rfq, company_id)
        if actor.side != "seller" or actor.controller != "human":
            raise NegotiationError(f"{company_id} is not a human-controlled seller")
        line = self._line(rfq, mpn)
        supply = self._supply(company_id, mpn)
        if supply is None:
            raise NegotiationError("seller does not carry this MPN", 404)
        rule, cat = supply
        rnd = rfq["round"]
        action = action.model_copy(update={"mpn": mpn})
        if action.qty is None:
            action = action.model_copy(update={"qty": line["qty"]})
        if action.type == "accept":
            bid = self._latest(rfq["_id"], company_id, mpn, "buyer")
            if not bid:
                raise NegotiationError("no buyer bid to accept")
            action = action.model_copy(update={"unit_price": bid["unit_price"], "qty": bid["qty"]})
        auth = self._seller_authority(cat).model_copy(update={"floor_price": rule.floor_price})
        guard = validate_action(actor, action, auth)
        return self._human_record(rfq, actor, company_id, mpn, action, guard, cat["tax_rate"],
                                  action.lead_time_days or cat["lead_time_days"])

    def human_buyer_turn(self, rfq_id: str, seller_id: str, mpn: str, action: Action) -> dict:
        rfq = self.get_rfq(rfq_id)
        self._require_negotiating(rfq)
        actor = self._buyer(rfq)
        if actor.controller != "human":
            raise NegotiationError("buyer is agent-controlled; take over first")
        if not any(s.company_id == seller_id for s in self._sellers(rfq)):
            raise NegotiationError(f"{seller_id} is not a supplier on this RFQ", 404)
        line = self._line(rfq, mpn)
        action = action.model_copy(update={"mpn": mpn})
        if action.qty is None:
            action = action.model_copy(update={"qty": line["qty"]})
        if action.type == "accept":
            ask = self._latest(rfq["_id"], seller_id, mpn, "seller")
            if not ask:
                raise NegotiationError("no seller ask to accept")
            action = action.model_copy(update={"unit_price": ask["unit_price"], "qty": ask["qty"]})
        limits = self.ensure_limits(rfq)
        ceiling = limits[mpn]["ceiling"] if limits else float("inf")
        auth = BuyerAuthority(mpn=mpn, line_qty=line["qty"], max_unit_price=ceiling)
        guard = validate_action(actor, action, auth)
        return self._human_record(rfq, actor, seller_id, mpn, action, guard, 0.18, None)

    def _require_negotiating(self, rfq: dict) -> None:
        if rfq["status"] != "negotiating":
            raise NegotiationError(f"RFQ is {rfq['status']}, not negotiating")

    def _line(self, rfq: dict, mpn: str) -> dict:
        line = next((ln for ln in rfq["lines"] if ln["mpn"] == mpn), None)
        if line is None:
            raise NegotiationError("MPN is not on this RFQ", 404)
        return line

    def _human_record(self, rfq, actor: Participant, seller_id, mpn, action: Action,
                      guard: GuardrailResult, tax_rate, lead, source: str | None = None,
                      extra: dict | None = None, reply: bool = True) -> dict:
        source = source or ("human_seller" if actor.side == "seller" else "human_buyer")
        rnd = rfq["round"]
        counterparty = rfq["buyer_company_id"] if actor.side == "seller" else seller_id
        turn_id = self._log_turn(rfq["_id"], rnd, actor, counterparty, mpn, action, guard,
                                 source, extra=extra)
        events: list[str] = [f"{actor.side} human turn recorded ({guard.status})"]
        offer = None
        if action.unit_price is not None and action.type != "walk_away":
            status = "flagged" if guard.requires_confirmation else (
                "accepted" if action.type == "accept" else "proposed")
            offer = self._log_offer(rfq["_id"], rnd, seller_id, actor.side, mpn,
                                    action.unit_price, action.qty, lead, tax_rate, source,
                                    status, turn_id, f"{actor.side}:{actor.company_id}",
                                    extra=extra)
        reply_offer = None
        if reply and offer and offer["status"] == "proposed":
            reply_offer = self._agent_reply(rfq, actor, seller_id, mpn, offer, rnd)
        return {"turn_id": turn_id, "guardrail": guard.model_dump(), "offer": _clean(offer),
                "reply": _clean(reply_offer), "events": events}

    def _agent_reply(self, rfq, human: Participant, seller_id, mpn, offer, rnd):
        """After a human move, the agent on the other side responds immediately."""
        line = self._line(rfq, mpn)
        if human.side == "seller":
            if self._buyer(rfq).controller == "agent":
                return self.buyer_move(rfq, seller_id, line, rnd, force=True)
            return None
        seller = next((s for s in self._sellers(rfq) if s.company_id == seller_id), None)
        if seller and seller.controller == "agent":
            return self._seller_reply(rfq, seller, line, offer, rnd)
        return None

    def _seller_reply(self, rfq, seller: Participant, line, bid_offer, rnd):
        """Seller agent answers a human buyer's bid: accept if it reaches the ask,
        otherwise concede on schedule."""
        mpn = line["mpn"]
        ask = self._latest(rfq["_id"], seller.company_id, mpn, "seller")
        if ask and bid_offer["unit_price"] >= ask["unit_price"]:
            return self._accept(rfq, seller, seller.company_id, mpn, ask, rnd, "engine", None)
        return self._seller_counter_now(rfq, seller, line, rnd)

    def _seller_counter_now(self, rfq, seller, line, rnd):
        supply = self._supply(seller.company_id, line["mpn"])
        if supply is None:
            return None
        rule, cat = supply
        qty = max(cat["moq"], min(line["qty"], cat["stock_qty"]))
        # Concede one step beyond the current standing ask, never below floor.
        nxt = min(round_price(rule, qty, rnd + 1),
                  (self._latest(rfq["_id"], seller.company_id, line["mpn"], "seller")
                   or {"unit_price": rule.list_price})["unit_price"])
        auth = self._seller_authority(cat).model_copy(update={"floor_price": rule.floor_price})
        fallback = Action(type="counter", mpn=line["mpn"], qty=qty, unit_price=nxt,
                          lead_time_days=cat["lead_time_days"],
                          message="Counter after your bid, per pricing policy.")
        outcome = decide_action(None, "", "", seller, auth, fallback, line["mpn"], qty)
        return self._apply(rfq, seller, rnd, line["mpn"], outcome, cat["tax_rate"],
                           cat["lead_time_days"], rfq["buyer_company_id"])

    def confirm(self, rfq_id: str, offer_id, reason: str, confirmed_by: str) -> dict:
        """Confirm a flagged human offer. Appends a new confirmed version; the
        flagged original is never edited."""
        if not ObjectId.is_valid(offer_id):
            raise NegotiationError("offer not found", 404)
        flagged = self.db.offers.find_one({"_id": ObjectId(offer_id), "rfq_id": rfq_id})
        if not flagged or flagged["status"] != "flagged":
            raise NegotiationError("offer is not awaiting confirmation", 404)
        result = confirm_override(GuardrailResult(status="flagged_outside_authority"),
                                  reason, confirmed_by)
        rfq = self.get_rfq(rfq_id)
        actor = Participant(company_id=flagged["created_by"].split(":", 1)[1],
                            side=flagged["side"], controller="human")
        turn_id = self._log_turn(
            rfq_id, flagged["round"], actor, "", flagged["mpn"], None,
            {**result.model_dump(), "original_offer_id": offer_id}, flagged["source"])
        new = self._log_offer(
            rfq_id, rfq["round"], flagged["company_id"], flagged["side"], flagged["mpn"],
            flagged["unit_price"], flagged["qty"], flagged.get("lead_time_days"),
            flagged.get("tax_rate", 0.18), flagged["source"], "confirmed", turn_id,
            flagged["created_by"])
        return _clean(new) | {"override_reason": result.override_reason}


def _clean(doc: dict | None) -> dict | None:
    if doc is None:
        return None
    out = {k: v for k, v in doc.items() if k != "_id"}
    if "_id" in doc:
        out["id"] = str(doc["_id"])
    return out
