"""Voice call logic, shared by the live tools, the post-call webhook and the
recorded-call loader.

The ElevenLabs agent is the buyer's voice. The human on the phone is the
supplier's rep, so while a call is open the seller side is put under human
control (and handed back when the call ends).

Hard rules, same as everywhere else:
  * the agent may only speak a number the guardrail allowed;
  * the rep's verbal numbers are validated against the seller's authority and
    flagged, never silently accepted, when outside it;
  * only a confirmed read-back becomes an offer, labeled `voice_confirmed`;
  * transcript text is data: only structured, validated fields are used.
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.auth import AuthError, create_token, decode_token
from app.engine.guardrail import validate_action
from app.engine.models import (
    Action, BuyerAuthority, BuyerLimit, GuardrailResult, Participant,
)
from app.engine.pricing import buyer_bid
from app.negotiation.orchestrator import NegotiationError, Orchestrator, _clean
from app.voice.webhook import extract_terms, price_in_transcript

SESSION_TTL = 2 * 3600
RECORDED_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "recorded_call.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class VoiceService:
    def __init__(self, orch: Orchestrator):
        self.orch = orch
        self.db = orch.db

    # ---------------------------------------------------------------- sessions
    def create_session(self, rfq_id: str, buyer_company_id: str, seller_id: str,
                       mode: str = "live") -> dict:
        orch = self.orch
        rfq = orch.get_rfq(rfq_id)
        if rfq["buyer_company_id"] != buyer_company_id:
            raise NegotiationError("RFQ not found", 404)
        if rfq["status"] != "negotiating":
            raise NegotiationError(f"RFQ is {rfq['status']}, not negotiating")
        seller = next((s for s in orch._sellers(rfq) if s.company_id == seller_id), None)
        if seller is None:
            raise NegotiationError(f"{seller_id} is not a supplier on this RFQ", 404)

        handed_over = False
        if mode == "live" and seller.controller == "agent":
            orch.handover(rfq_id, seller_id, "human")
            handed_over = True

        call_id = uuid.uuid4().hex
        self.db.voice_calls.insert_one({
            "_id": call_id, "rfq_id": rfq_id, "seller_id": seller_id,
            "buyer_company_id": buyer_company_id, "mode": mode, "status": "initiated",
            "handed_over": handed_over, "conversation_id": None, "created_at": _now(),
        })
        token = create_token(
            {"typ": "voice", "sub": f"voice:{call_id}", "call_id": call_id, "rfq_id": rfq_id,
             "seller_id": seller_id, "buyer_company_id": buyer_company_id},
            ttl=SESSION_TTL)
        names = {c["_id"]: c["name"] for c in self.db.companies.find(
            {"_id": {"$in": [seller_id, buyer_company_id]}})}
        return {
            "call_id": call_id, "session_token": token,
            # Everything the agent may know. No budget, no limits.
            "dynamic_variables": {
                "session_token": token, "call_id": call_id, "rfq_id": rfq_id,
                "seller_id": seller_id, "supplier_name": names.get(seller_id, seller_id),
                "buyer_name": names.get(buyer_company_id, buyer_company_id),
                "deadline_days": rfq["deadline_days"],
                "lines": json.dumps([{"mpn": ln["mpn"], "qty": ln["qty"]} for ln in rfq["lines"]]),
            },
        }

    @staticmethod
    def claims(token: str | None) -> dict:
        if not token:
            raise NegotiationError("missing voice session token", 401)
        try:
            claims = decode_token(token)
        except AuthError as exc:
            raise NegotiationError(f"invalid voice session token: {exc}", 401) from exc
        if claims.get("typ") != "voice":
            raise NegotiationError("not a voice session token", 401)
        return claims

    def _negotiating_rfq(self, claims: dict) -> dict:
        rfq = self.orch.get_rfq(claims["rfq_id"])
        if rfq["status"] != "negotiating":
            raise NegotiationError(f"RFQ is {rfq['status']}, not negotiating")
        return rfq

    # --------------------------------------------------------------- live tools
    def get_current_offer(self, claims: dict, mpn: str) -> dict:
        orch, rfq_id, seller_id = self.orch, claims["rfq_id"], claims["seller_id"]
        rfq = self._negotiating_rfq(claims)
        line = orch._line(rfq, mpn)
        ask = orch._latest(rfq_id, seller_id, mpn, "seller")
        bid = orch._latest(rfq_id, seller_id, mpn, "buyer")
        limits = orch.ensure_limits(rfq)
        allowed = None
        if limits:
            allowed = buyer_bid(BuyerLimit(mpn=mpn, **limits[mpn]), rfq["round"],
                                orch._max_rounds(rfq))
        return {
            "mpn": mpn, "qty_required": line["qty"], "round": rfq["round"],
            "supplier_current_price": ask["unit_price"] if ask else None,
            "your_last_offer": bid["unit_price"] if bid else None,
            "allowed_offer_price": allowed,
            "instruction": "Only ever speak a price returned by this tool or by propose_offer.",
        }

    def propose_offer(self, claims: dict, mpn: str, unit_price: float) -> dict:
        orch, rfq_id, seller_id = self.orch, claims["rfq_id"], claims["seller_id"]
        rfq = self._negotiating_rfq(claims)
        line = orch._line(rfq, mpn)
        limits = orch.ensure_limits(rfq)
        if not limits:
            return {"allowed": False, "speak_price": None,
                    "message": "No reference prices yet. Ask the supplier for their price first."}
        limit = BuyerLimit(mpn=mpn, **limits[mpn])
        policy = buyer_bid(limit, rfq["round"], orch._max_rounds(rfq))
        buyer = Participant(company_id=rfq["buyer_company_id"], side="buyer", controller="agent")
        auth = BuyerAuthority(mpn=mpn, line_qty=line["qty"], max_unit_price=limit.ceiling)
        action = Action(type="counter", mpn=mpn, qty=line["qty"], unit_price=unit_price,
                        message="Offer made by voice agent.")
        guard = validate_action(buyer, action, auth)
        extra = {"channel": "voice", "call_id": claims["call_id"]}
        turn_id = orch._log_turn(rfq_id, rfq["round"], buyer, seller_id, mpn, action, guard,
                                 "llm_agent", notes=["voice agent offer"], extra=extra)
        if not guard.counts:
            # Say the allowed number instead; never explain the limit.
            return {"allowed": False, "speak_price": policy, "accepted": False,
                    "message": f"Offer {policy} instead."}
        offer = orch._log_offer(rfq_id, rfq["round"], seller_id, "buyer", mpn, unit_price,
                                line["qty"], None, 0.18, "llm_agent", "proposed", turn_id,
                                f"buyer:{rfq['buyer_company_id']}", extra=extra)
        ask = orch._latest(rfq_id, seller_id, mpn, "seller")
        accepted = False
        if ask and unit_price >= ask["unit_price"] and orch._open(rfq_id, seller_id, mpn):
            orch._accept(rfq, buyer, seller_id, mpn, ask, rfq["round"], "llm_agent", turn_id)
            accepted = True
        return {"allowed": True, "speak_price": offer["unit_price"], "accepted": accepted,
                "message": "Offer recorded."}

    def record_seller_offer(self, claims: dict, mpn: str, unit_price: float,
                            qty: int | None, lead_time_days: int | None) -> dict:
        """What the rep just said. Validated like any human seller turn."""
        orch, seller_id = self.orch, claims["seller_id"]
        rfq = self._negotiating_rfq(claims)
        line = orch._line(rfq, mpn)
        supply = orch._supply(seller_id, mpn)
        if supply is None:
            return {"recorded": False, "message": "That part is not in this supplier's catalog."}
        rule, cat = supply
        actor = Participant(company_id=seller_id, side="seller", controller="human")
        action = Action(type="counter", mpn=mpn, unit_price=unit_price,
                        qty=qty or line["qty"],
                        lead_time_days=lead_time_days or cat["lead_time_days"],
                        message="Stated by the supplier on a call.")
        auth = orch._seller_authority(cat).model_copy(update={"floor_price": rule.floor_price})
        guard = validate_action(actor, action, auth)
        orch._human_record(rfq, actor, seller_id, mpn, action, guard, cat["tax_rate"],
                           action.lead_time_days,
                           extra={"channel": "voice", "call_id": claims["call_id"]},
                           reply=False)
        # Deliberately no reasons: the agent must not learn the supplier's floor.
        return {"recorded": True,
                "message": "Noted. Call get_current_offer for your next allowed price."}

    def confirm_terms(self, claims: dict, mpn: str, unit_price: float, qty: int,
                      lead_time_days: int | None, readback_confirmed: bool) -> dict:
        """Agent's claim, after reading terms back. The webhook finalizes it."""
        self.db.voice_calls.update_one(
            {"_id": claims["call_id"]},
            {"$set": {"claimed_terms": {
                "mpn": mpn, "unit_price": unit_price, "qty": qty,
                "lead_time_days": lead_time_days,
                "readback_confirmed": readback_confirmed}}})
        return {"recorded": True,
                "message": "Terms noted. They are final once the call ends and is verified."}

    # ------------------------------------------------------------- finalization
    def finalize_call(self, call_id: str, transcript: list[dict], terms: dict | None,
                      conversation_id: str | None = None, analysis: dict | None = None) -> dict:
        """Turn a finished call into a `voice_confirmed` offer, if it earned one."""
        orch = self.orch
        call = self.db.voice_calls.find_one({"_id": call_id})
        if not call:
            raise NegotiationError("voice call not found", 404)
        if call["status"] in ("completed", "unconfirmed", "failed"):
            return {"status": call["status"], "idempotent": True}

        terms = terms or call.get("claimed_terms")
        reason = None
        offer = None
        guard_status = None
        thread_closed = False
        rfq = orch.get_rfq(call["rfq_id"])

        if not terms:
            reason = "no confirmed terms were captured"
        elif not terms.get("readback_confirmed"):
            reason = "the supplier did not confirm the read-back"
        elif terms.get("mpn") not in {ln["mpn"] for ln in rfq["lines"]}:
            reason = "confirmed part is not on this RFQ"
        elif rfq["status"] != "negotiating":
            reason = f"RFQ is {rfq['status']}"

        if reason is None:
            line = orch._line(rfq, terms["mpn"])
            supply = orch._supply(call["seller_id"], terms["mpn"])
            if supply is None:
                reason = "supplier does not carry the confirmed part"
            else:
                rule, cat = supply
                actor = Participant(company_id=call["seller_id"], side="seller",
                                    controller="human")
                action = Action(type="counter", mpn=terms["mpn"], unit_price=terms["unit_price"],
                                qty=terms["qty"] or line["qty"],
                                lead_time_days=terms.get("lead_time_days") or cat["lead_time_days"],
                                message="Confirmed by read-back on a call.")
                auth = orch._seller_authority(cat).model_copy(
                    update={"floor_price": rule.floor_price})
                guard = validate_action(actor, action, auth)
                if guard.status == "ok" and not price_in_transcript(
                        terms["unit_price"], transcript):
                    guard = GuardrailResult(
                        status="flagged_outside_authority",
                        reasons=["confirmed price was not found in the transcript"])
                result = orch._human_record(
                    rfq, actor, call["seller_id"], terms["mpn"], action, guard,
                    cat["tax_rate"], action.lead_time_days, source="voice_confirmed",
                    extra={"channel": "voice", "voice_mode": call["mode"], "call_id": call_id,
                           "conversation_id": conversation_id},
                    reply=False)
                offer = result["offer"]
                guard_status = result["guardrail"]["status"]
                thread_closed = self._close_if_within_authority(rfq, call, terms["mpn"], offer)

        status = "completed" if offer else "unconfirmed"
        self.db.voice_calls.update_one({"_id": call_id}, {"$set": {
            "status": status, "transcript": transcript, "terms": terms,
            "analysis_summary": (analysis or {}).get("transcript_summary"),
            "conversation_id": conversation_id or call.get("conversation_id"),
            "offer_id": offer["id"] if offer else None, "guardrail_status": guard_status,
            "thread_closed": thread_closed,
            "unconfirmed_reason": reason, "completed_at": _now()}})

        if call.get("handed_over"):  # give the seller side back to its agent
            try:
                orch.handover(call["rfq_id"], call["seller_id"], "agent")
            except NegotiationError:
                pass
        return {"status": status, "offer": offer, "guardrail_status": guard_status,
                "thread_closed": thread_closed, "reason": reason, "mode": call["mode"]}

    def _close_if_within_authority(self, rfq: dict, call: dict, mpn: str, offer: dict) -> bool:
        """A read-back both sides confirmed is a deal on that line: lock the thread
        at that price so the seller agent cannot keep conceding below it. Only
        done for in-authority offers and when the buyer's ceiling allows it."""
        if offer["status"] != "proposed":
            return False
        limits = self.orch.ensure_limits(rfq)
        if not limits or offer["unit_price"] > limits[mpn]["ceiling"]:
            return False
        buyer = Participant(company_id=rfq["buyer_company_id"], side="buyer", controller="agent")
        self.orch._accept(rfq, buyer, call["seller_id"], mpn, offer, rfq["round"],
                          "voice_confirmed", offer["turn_id"])
        return True

    def abandon_call(self, call_id: str, reason: str) -> dict:
        """Close a call that never produced a conversation, and give the seller
        side back to its agent. Only affects calls still `initiated`."""
        call = self.db.voice_calls.find_one({"_id": call_id})
        if not call:
            raise NegotiationError("voice call not found", 404)
        if call["status"] != "initiated":
            return {"status": call["status"], "idempotent": True}
        self.db.voice_calls.update_one({"_id": call_id}, {"$set": {
            "status": "failed", "unconfirmed_reason": reason, "completed_at": _now()}})
        if call.get("handed_over"):
            try:
                self.orch.handover(call["rfq_id"], call["seller_id"], "agent")
            except NegotiationError:
                pass
        return {"status": "failed", "reason": reason}

    def finalize_from_provider(self, call_id: str, conversation_id: str, client,
                               wait_seconds: float = 60, poll_seconds: float = 3) -> dict:
        """Pull a finished conversation from ElevenLabs and finalize the call.
        The conversation must belong to our agent and carry this call's id, so a
        caller cannot attach someone else's conversation to an RFQ."""
        import time

        call = self.db.voice_calls.find_one({"_id": call_id})
        if not call:
            raise NegotiationError("voice call not found", 404)
        if call["status"] != "initiated":
            return {"status": call["status"], "idempotent": True}
        self.db.voice_calls.update_one({"_id": call_id}, {"$set": {"conversation_id": conversation_id}})

        deadline = time.monotonic() + wait_seconds
        conv = client.conversation(conversation_id)
        while conv.get("status") not in ("done", "failed") and time.monotonic() < deadline:
            time.sleep(poll_seconds)
            conv = client.conversation(conversation_id)

        if conv.get("agent_id") != client.agent_id:
            raise NegotiationError("conversation belongs to a different agent", 403)
        variables = (conv.get("conversation_initiation_client_data") or {}).get("dynamic_variables") or {}
        if variables.get("call_id") != call_id:
            raise NegotiationError("conversation does not belong to this call", 403)
        if conv.get("status") == "failed":
            return self.abandon_call(call_id, "voice provider reported the conversation failed")
        if conv.get("status") != "done":
            raise NegotiationError("the call is still being processed; try again in a moment", 409)

        analysis = conv.get("analysis") or {}
        return self.finalize_call(call_id, conv.get("transcript") or [], extract_terms(analysis),
                                  conversation_id=conversation_id, analysis=analysis)

    def load_recorded(self, rfq_id: str, buyer_company_id: str, seller_id: str) -> dict:
        """Fallback demo: replay a call recorded in advance, labeled `recorded`."""
        if not RECORDED_FIXTURE.exists():
            raise NegotiationError("no recorded call fixture is available", 404)
        fixture = json.loads(RECORDED_FIXTURE.read_text(encoding="utf-8"))
        session = self.create_session(rfq_id, buyer_company_id, seller_id, mode="recorded")
        terms = extract_terms(fixture.get("analysis"))
        result = self.finalize_call(
            session["call_id"], fixture.get("transcript", []), terms,
            conversation_id=fixture.get("conversation_id"), analysis=fixture.get("analysis"))
        return {"call_id": session["call_id"], **{k: _clean(v) if isinstance(v, dict) else v
                                                   for k, v in result.items()}}
