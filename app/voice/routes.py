"""Voice endpoints: session setup, ElevenLabs server tools, post-call webhook."""
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app import scope
from app.auth import User, current_user
from app.config import settings
from app.db import get_db
from app.deps import buyer_only, get_orchestrator, guard, rfq_for
from app.negotiation.orchestrator import NegotiationError, Orchestrator
from app.voice.elevenlabs import ElevenLabsClient, VoiceProviderError
from app.voice.service import VoiceService
from app.voice.webhook import SignatureError, extract_terms, verify_signature

router = APIRouter(tags=["voice"])


def _service(orch: Orchestrator = Depends(get_orchestrator)) -> VoiceService:
    return VoiceService(orch)


def _build_client() -> ElevenLabsClient:
    return ElevenLabsClient(settings.elevenlabs_api_key, settings.elevenlabs_agent_id,
                            settings.elevenlabs_phone_number_id)


def get_voice_client() -> ElevenLabsClient:
    """Required provider client (503 if not configured)."""
    try:
        return _build_client()
    except VoiceProviderError as exc:
        raise HTTPException(503, str(exc)) from exc


def get_optional_voice_client() -> ElevenLabsClient | None:
    try:
        return _build_client()
    except VoiceProviderError:
        return None


# ------------------------------------------------------------ buyer-facing
class SessionIn(BaseModel):
    seller_id: str


@router.post("/rfqs/{rfq_id}/voice/session", status_code=201)
def create_session(rfq_id: str, body: SessionIn, user: User = Depends(buyer_only),
                   svc: VoiceService = Depends(_service),
                   client: ElevenLabsClient | None = Depends(get_optional_voice_client)) -> dict:
    """Start a voice session. Puts the supplier side under human control until
    the call is finalized. When the provider is configured, also returns a
    short-lived `signed_url` for talking to the agent from a browser."""
    session = guard(lambda: svc.create_session(rfq_id, user.company_id, body.seller_id))
    session["signed_url"] = None
    session["browser_voice_error"] = None
    if client is None:
        session["browser_voice_error"] = "Voice provider is not configured on the server."
    else:
        try:
            session["signed_url"] = client.signed_url()
        except VoiceProviderError as exc:
            session["browser_voice_error"] = str(exc)
    return session


class FinalizeIn(BaseModel):
    conversation_id: str | None = None


@router.post("/rfqs/{rfq_id}/voice/{call_id}/finalize")
def finalize_call(rfq_id: str, call_id: str, body: FinalizeIn, user: User = Depends(buyer_only),
                  svc: VoiceService = Depends(_service),
                  client: ElevenLabsClient | None = Depends(get_optional_voice_client)) -> dict:
    """Called by the browser after a call ends. Pulls the transcript and
    extracted terms from ElevenLabs (no webhook needed). Without a
    conversation id, the call is closed as not completed."""
    call = get_db().voice_calls.find_one({"_id": call_id, "rfq_id": rfq_id})
    if not call or call.get("buyer_company_id") != user.company_id:
        raise HTTPException(404, "voice call not found")
    if not body.conversation_id:
        return guard(lambda: svc.abandon_call(call_id, "call ended before it connected"))
    if client is None:
        raise HTTPException(503, "Voice provider is not configured on the server.")
    try:
        result = guard(lambda: svc.finalize_from_provider(call_id, body.conversation_id, client))
    except VoiceProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return scope.clean_json(result)


class CallIn(BaseModel):
    seller_id: str
    to_number: str = Field(min_length=6)


@router.post("/rfqs/{rfq_id}/voice/call", status_code=201)
def outbound_call(rfq_id: str, body: CallIn, user: User = Depends(buyer_only),
                  svc: VoiceService = Depends(_service),
                  client: ElevenLabsClient = Depends(get_voice_client)) -> dict:
    session = guard(lambda: svc.create_session(rfq_id, user.company_id, body.seller_id))
    try:
        placed = client.outbound_call(body.to_number, session["dynamic_variables"])
    except VoiceProviderError as exc:
        svc.abandon_call(session["call_id"], str(exc))
        raise HTTPException(502, str(exc)) from exc
    get_db().voice_calls.update_one(
        {"_id": session["call_id"]}, {"$set": {"conversation_id": placed["conversation_id"]}})
    return {"call_id": session["call_id"], **placed}


@router.post("/rfqs/{rfq_id}/voice/recorded", status_code=201)
def recorded_call(rfq_id: str, body: SessionIn, user: User = Depends(buyer_only),
                  svc: VoiceService = Depends(_service)) -> dict:
    """Replay the pre-recorded demo call. Offers are labeled voice_confirmed with
    voice_mode "recorded", so they can never pass as live."""
    return guard(lambda: svc.load_recorded(rfq_id, user.company_id, body.seller_id))


@router.get("/rfqs/{rfq_id}/voice")
def list_calls(rfq_id: str, user: User = Depends(current_user),
               orch: Orchestrator = Depends(get_orchestrator)) -> list[dict]:
    rfq_for(user, rfq_id, orch)
    query: dict = {"rfq_id": rfq_id}
    if user.role == "seller":
        query["seller_id"] = user.company_id
    out = []
    for doc in get_db().voice_calls.find(query).sort("created_at", 1):
        doc = {**doc, "id": doc.pop("_id")}
        out.append(scope.clean_json(doc))
    return out


# ---------------------------------------------------- ElevenLabs server tools
# The agent passes its session token either as an `X-Voice-Session` header or
# as a `session_token` body field filled from the {{session_token}} dynamic
# variable. The model never sees or chooses it.
def _claims(token: str | None) -> dict:
    try:
        return VoiceService.claims(token)
    except NegotiationError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


class ToolBody(BaseModel):
    session_token: str | None = None


class OfferQuery(ToolBody):
    mpn: str


class ProposeIn(ToolBody):
    mpn: str
    unit_price: float = Field(gt=0)


class SellerOfferIn(ToolBody):
    mpn: str
    unit_price: float = Field(gt=0)
    qty: int | None = Field(default=None, ge=1)
    lead_time_days: int | None = Field(default=None, ge=0)


class ConfirmTermsIn(ToolBody):
    mpn: str
    unit_price: float = Field(gt=0)
    qty: int = Field(ge=1)
    lead_time_days: int | None = Field(default=None, ge=0)
    readback_confirmed: bool


@router.post("/voice/tools/get_current_offer")
def tool_get_current_offer(body: OfferQuery, x_voice_session: str | None = Header(default=None),
                           svc: VoiceService = Depends(_service)) -> dict:
    claims = _claims(x_voice_session or body.session_token)
    return guard(lambda: svc.get_current_offer(claims, body.mpn))


@router.post("/voice/tools/propose_offer")
def tool_propose_offer(body: ProposeIn, x_voice_session: str | None = Header(default=None),
                       svc: VoiceService = Depends(_service)) -> dict:
    claims = _claims(x_voice_session or body.session_token)
    return guard(lambda: svc.propose_offer(claims, body.mpn, body.unit_price))


@router.post("/voice/tools/record_seller_offer")
def tool_record_seller_offer(body: SellerOfferIn, x_voice_session: str | None = Header(default=None),
                             svc: VoiceService = Depends(_service)) -> dict:
    claims = _claims(x_voice_session or body.session_token)
    return guard(lambda: svc.record_seller_offer(
        claims, body.mpn, body.unit_price, body.qty, body.lead_time_days))


@router.post("/voice/tools/confirm_terms")
def tool_confirm_terms(body: ConfirmTermsIn, x_voice_session: str | None = Header(default=None),
                       svc: VoiceService = Depends(_service)) -> dict:
    claims = _claims(x_voice_session or body.session_token)
    return guard(lambda: svc.confirm_terms(
        claims, body.mpn, body.unit_price, body.qty, body.lead_time_days,
        body.readback_confirmed))


# --------------------------------------------------------------- webhook
@router.post("/voice/webhook")
async def post_call_webhook(request: Request,
                            elevenlabs_signature: str | None = Header(default=None)) -> dict:
    """ElevenLabs post-call webhook. Must answer 200 or ElevenLabs retries and
    may eventually disable it, so business-level problems are reported in the
    body and only a bad signature is rejected."""
    raw = await request.body()
    try:
        verify_signature(raw, elevenlabs_signature, settings.elevenlabs_webhook_secret)
    except SignatureError as exc:
        raise HTTPException(401, f"invalid signature: {exc}") from exc
    try:
        event = json.loads(raw)
    except ValueError:
        return {"received": True, "handled": False, "reason": "body is not JSON"}

    kind = event.get("type")
    data = event.get("data") or {}
    variables = ((data.get("conversation_initiation_client_data") or {})
                 .get("dynamic_variables") or {})
    try:
        claims = VoiceService.claims(variables.get("session_token"))
    except NegotiationError as exc:
        return {"received": True, "handled": False, "reason": str(exc)}

    svc = VoiceService(Orchestrator(get_db()))
    if kind == "call_initiation_failure":
        svc.abandon_call(claims["call_id"], "call could not be initiated")
        return {"received": True, "handled": True, "status": "failed"}
    if kind != "post_call_transcription":
        return {"received": True, "handled": False, "reason": f"ignored event {kind}"}
    try:
        result = svc.finalize_call(
            claims["call_id"], data.get("transcript") or [],
            extract_terms(data.get("analysis")), data.get("conversation_id"),
            data.get("analysis"))
    except NegotiationError as exc:
        return {"received": True, "handled": False, "reason": str(exc)}
    return {"received": True, "handled": True, "status": result["status"]}
