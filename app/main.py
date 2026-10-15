import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from pymongo.errors import PyMongoError

from app import scope
from app.auth import User, create_token, current_user
from app.config import settings
from app.db import get_db
from app.deps import (
    _llm, buyer_only, get_llm, get_orchestrator, guard as _guard, rfq_for as _rfq_for,
    seller_only,
)
from app.engine.models import Action, ActionType, PricingRule, Tier
from app.negotiation.orchestrator import Orchestrator
from app.voice.routes import router as voice_router
from app.security import verify_password

app = FastAPI(title="The Negotiator")
app.include_router(voice_router)

_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
if _origins or settings.cors_origin_regex:
    app.add_middleware(CORSMiddleware, allow_origins=_origins,
                       allow_origin_regex=settings.cors_origin_regex or None,
                       allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


def _plain(doc: dict) -> dict:
    out = dict(doc)
    out["id"] = out.pop("_id")
    out.pop("password_hash", None)
    return out


def _oid(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if k != "_id"}
    out["id"] = str(doc["_id"])
    return out


def _view_rfq(user: User, rfq: dict) -> dict:
    rfq = _plain(rfq)
    if user.role == "buyer":
        return scope.clean_json(scope.rfq_for_buyer(rfq))
    return scope.clean_json(scope.rfq_for_seller(rfq, user.company_id))


# ------------------------------------------------------------------------ auth
class LoginIn(BaseModel):
    email: str
    password: str


@app.post("/auth/login")
def login(body: LoginIn) -> dict:
    user = get_db().users.find_one({"email": body.email.strip().lower()})
    # Same answer for unknown email and wrong password.
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "invalid email or password")
    token = create_token({"sub": user["email"], "role": user["role"],
                          "company_id": user["company_id"]})
    return {"access_token": token, "token_type": "bearer",
            "role": user["role"], "company_id": user["company_id"]}


@app.get("/auth/me")
def me(user: User = Depends(current_user)) -> dict:
    company = get_db().companies.find_one({"_id": user.company_id}) or {}
    return {"email": user.email, "role": user.role, "company_id": user.company_id,
            "company_name": company.get("name")}


# ------------------------------------------------------------------ reference
@app.get("/health")
def health() -> dict:
    get_db().command("ping")
    return {"ok": True, "llm": _llm().name if _llm() else "engine"}


@app.get("/companies")
def list_companies(kind: str | None = None, _: User = Depends(current_user)) -> list[dict]:
    query = {"kind": kind} if kind else {}
    return [_plain(d) for d in get_db().companies.find(query)]


@app.get("/companies/{company_id}/catalog")
def company_catalog(company_id: str, _: User = Depends(current_user)) -> list[dict]:
    """Public catalog facts (stock, lead time, MOQ, specs). Never pricing rules."""
    items = list(get_db().catalog_items.find({"company_id": company_id}, {"_id": 0}))
    if not items:
        raise HTTPException(404, "No catalog for company")
    return items


# ---------------------------------------------------------------- seller area
@app.get("/seller/products")
def seller_products(user: User = Depends(seller_only)) -> list[dict]:
    """A seller's own catalog joined with its own pricing rules (floors included)."""
    db = get_db()
    rules = {r["mpn"]: r for r in db.pricing_rules.find({"company_id": user.company_id})}
    out = []
    for item in db.catalog_items.find({"company_id": user.company_id}, {"_id": 0}):
        rule = rules.get(item["mpn"], {})
        out.append(scope.clean_json({**item, "pricing": {
            k: rule.get(k) for k in ("list_price", "floor_price", "tiers",
                                     "concession_step_pct", "max_rounds")}}))
    return out


class ProductIn(BaseModel):
    mpn: str = Field(min_length=1)
    description: str = ""
    specs: dict[str, Any] = {}
    stock_qty: int = Field(ge=0)
    lead_time_days: int = Field(ge=0)
    moq: int = Field(ge=1)
    tax_rate: float = Field(default=0.18, ge=0, le=1)
    list_price: float = Field(gt=0)
    floor_price: float = Field(gt=0)
    tiers: list[Tier] = []
    concession_step_pct: float = Field(default=0.25, ge=0, le=1)
    max_rounds: int = Field(default=3, ge=1, le=5)


@app.post("/seller/products", status_code=201)
def upsert_product(body: ProductIn, user: User = Depends(seller_only)) -> dict:
    """Add or update one product: catalog item and pricing rule together."""
    try:
        PricingRule(mpn=body.mpn, list_price=body.list_price, floor_price=body.floor_price,
                    tiers=body.tiers, concession_step_pct=body.concession_step_pct,
                    max_rounds=body.max_rounds)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors()[0]["msg"]) from exc
    db = get_db()
    now = datetime.now(timezone.utc)
    db.catalog_items.replace_one(
        {"company_id": user.company_id, "mpn": body.mpn},
        {"company_id": user.company_id, "mpn": body.mpn, "description": body.description,
         "specs": body.specs, "stock_qty": body.stock_qty,
         "lead_time_days": body.lead_time_days, "moq": body.moq, "tax_rate": body.tax_rate},
        upsert=True)
    db.pricing_rules.replace_one(
        {"company_id": user.company_id, "mpn": body.mpn},
        {"company_id": user.company_id, "mpn": body.mpn, "list_price": body.list_price,
         "floor_price": body.floor_price, "tiers": [t.model_dump() for t in body.tiers],
         "concession_step_pct": body.concession_step_pct, "max_rounds": body.max_rounds,
         "valid_from": now, "valid_to": now + timedelta(days=90)},
        upsert=True)
    return {"mpn": body.mpn, "company_id": user.company_id}


@app.get("/seller/rfqs")
def seller_rfqs(user: User = Depends(seller_only)) -> list[dict]:
    """Incoming RFQs: those this seller is invited to and the buyer has opened."""
    docs = get_db().rfqs.find({
        "participants": {"$elemMatch": {"company_id": user.company_id, "side": "seller"}},
        "status": {"$ne": "draft"}}).sort("_id")
    return [_view_rfq(user, d) for d in docs]


# ------------------------------------------------------------------------ RFQs
class LineIn(BaseModel):
    mpn: str
    qty: int = Field(ge=1)
    required_specs: dict[str, dict[str, Any]] = {}
    mandatory: bool = True


class RfqIn(BaseModel):
    title: str
    budget: float = Field(gt=0)
    budget_basis: str = Field(default="landed_incl_tax", pattern="^(landed_incl_tax|pre_tax)$")
    currency: str = "INR"
    deadline_days: int = Field(ge=1)
    max_rounds: int = Field(default=3, ge=1, le=5)
    lines: list[LineIn] = Field(min_length=1)
    invite: list[str] = Field(min_length=1)


@app.post("/rfqs", status_code=201)
def create_rfq(body: RfqIn, user: User = Depends(buyer_only)) -> dict:
    db = get_db()
    for sid in body.invite:
        if not db.companies.find_one({"_id": sid, "kind": "supplier"}):
            raise HTTPException(404, f"supplier {sid} not found")
    now = datetime.now(timezone.utc)
    rfq_id = f"rfq_{int(now.timestamp() * 1000)}"
    doc = {
        "_id": rfq_id, "buyer_company_id": user.company_id, "title": body.title,
        "budget": body.budget, "budget_basis": body.budget_basis, "currency": body.currency,
        "deadline_days": body.deadline_days, "deadline": now + timedelta(days=body.deadline_days),
        "max_rounds": body.max_rounds, "status": "draft", "round": 0,
        "lines": [ln.model_dump() for ln in body.lines],
        "participants": [
            {"company_id": user.company_id, "side": "buyer",
             "controller": "agent", "status": "active"},
            *[{"company_id": sid, "side": "seller", "controller": "agent",
               "status": "invited"} for sid in body.invite],
        ],
        "created_at": now,
    }
    db.rfqs.insert_one(doc)
    return _view_rfq(user, doc)


@app.get("/rfqs")
def list_rfqs(user: User = Depends(buyer_only)) -> list[dict]:
    docs = get_db().rfqs.find({"buyer_company_id": user.company_id}).sort("_id")
    return [_view_rfq(user, d) for d in docs]


@app.get("/rfqs/{rfq_id}")
def get_rfq(rfq_id: str, user: User = Depends(current_user),
            orch: Orchestrator = Depends(get_orchestrator)) -> dict:
    return _view_rfq(user, _rfq_for(user, rfq_id, orch))


class StartIn(BaseModel):
    run_all: bool = False
    engine_only: bool = False  # skip the LLM: deterministic, same result every time


@app.post("/rfqs/{rfq_id}/start")
def start_rfq(rfq_id: str, body: StartIn | None = None, user: User = Depends(buyer_only),
              orch: Orchestrator = Depends(get_orchestrator)) -> dict:
    """Open negotiation (round 0). With run_all, play every round and return
    the recommendation in this single call."""
    _rfq_for(user, rfq_id, orch)
    body = body or StartIn()
    if body.run_all:
        rec = _guard(lambda: orch.run_all(rfq_id, body.engine_only))
        return {"status": "completed", "recommendation": scope.clean_json(rec)}
    rfq = _guard(lambda: orch.start(rfq_id, body.engine_only))
    return {"status": rfq["status"], "round": rfq["round"]}


@app.post("/rfqs/{rfq_id}/rounds")
def next_round(rfq_id: str, user: User = Depends(buyer_only),
               orch: Orchestrator = Depends(get_orchestrator)) -> dict:
    """Advance one round. The final round also produces the recommendation."""
    _rfq_for(user, rfq_id, orch)
    rfq = _guard(lambda: orch.next_round(rfq_id))
    if rfq["round"] >= orch._max_rounds(rfq):
        rec = _guard(lambda: orch.finalize(rfq_id))
        return {"status": "completed", "round": rfq["round"],
                "recommendation": scope.clean_json(rec)}
    return {"status": rfq["status"], "round": rfq["round"]}


class TurnIn(BaseModel):
    mpn: str
    type: ActionType = "counter"
    unit_price: float | None = Field(default=None, gt=0)
    qty: int | None = Field(default=None, ge=1)
    lead_time_days: int | None = Field(default=None, ge=0)
    message: str = ""
    seller_id: str | None = None       # required when the buyer acts


@app.post("/rfqs/{rfq_id}/turns", status_code=201)
def human_turn(rfq_id: str, body: TurnIn, user: User = Depends(current_user),
               orch: Orchestrator = Depends(get_orchestrator)) -> dict:
    """A human's move, as the caller's own company. Out-of-authority offers enter
    the thread flagged and need POST /confirm with a reason before they count."""
    _rfq_for(user, rfq_id, orch)
    action = Action(type=body.type, mpn=body.mpn, unit_price=body.unit_price,
                    qty=body.qty, lead_time_days=body.lead_time_days, message=body.message)
    if user.role == "buyer":
        if not body.seller_id:
            raise HTTPException(422, "seller_id is required when the buyer acts")
        result = _guard(lambda: orch.human_buyer_turn(rfq_id, body.seller_id, body.mpn, action))
    else:
        result = _guard(lambda: orch.human_seller_turn(rfq_id, user.company_id, body.mpn, action))
    result = scope.clean_json(result)
    if user.role == "buyer" and result.get("reply"):
        result["reply"].pop("created_by", None)
    return result


class HandoverIn(BaseModel):
    controller: str = Field(pattern="^(agent|human)$")


@app.post("/rfqs/{rfq_id}/handover")
def handover(rfq_id: str, body: HandoverIn, user: User = Depends(current_user),
             orch: Orchestrator = Depends(get_orchestrator)) -> dict:
    """Take over or hand back control of the caller's own side only."""
    _rfq_for(user, rfq_id, orch)
    return _guard(lambda: orch.handover(rfq_id, user.company_id, body.controller))


class ConfirmIn(BaseModel):
    offer_id: str
    reason: str


@app.post("/rfqs/{rfq_id}/confirm", status_code=201)
def confirm_offer(rfq_id: str, body: ConfirmIn, user: User = Depends(current_user),
                  orch: Orchestrator = Depends(get_orchestrator)) -> dict:
    """Confirm your own flagged offer, with a reason that is logged."""
    _rfq_for(user, rfq_id, orch)
    from bson import ObjectId
    if not ObjectId.is_valid(body.offer_id):
        raise HTTPException(404, "offer not found")
    offer = orch.db.offers.find_one({"_id": ObjectId(body.offer_id), "rfq_id": rfq_id})
    if not offer or offer.get("created_by") != f"{user.role}:{user.company_id}":
        raise HTTPException(404, "offer not found")
    try:
        return scope.clean_json(_guard(
            lambda: orch.confirm(rfq_id, body.offer_id, body.reason, user.email)))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/rfqs/{rfq_id}/recommendation")
def get_recommendation(rfq_id: str, user: User = Depends(buyer_only),
                       orch: Orchestrator = Depends(get_orchestrator)) -> dict:
    _rfq_for(user, rfq_id, orch)
    rec = get_db().recommendations.find_one({"rfq_id": rfq_id}, sort=[("created_at", -1)])
    if not rec:
        raise HTTPException(404, "no recommendation yet")
    return scope.clean_json(_oid(rec))


def _offers(user: User, rfq_id: str, since: datetime | None = None) -> list[dict]:
    query: dict = {"rfq_id": rfq_id}
    if since is not None:
        query["created_at"] = {"$gt": since}
    docs = [_oid(d) for d in get_db().offers.find(query).sort([("created_at", 1)])]
    if user.role == "seller":
        docs = scope.offers_for_seller(docs, user.company_id)
    return docs


def _turns(user: User, rfq_id: str, since: datetime | None = None) -> list[dict]:
    query: dict = {"rfq_id": rfq_id}
    if since is not None:
        query["created_at"] = {"$gt": since}
    docs = [_oid(d) for d in get_db().turns.find(query).sort("created_at", 1)]
    if user.role == "seller":
        return scope.turns_for_seller(docs, user.company_id)
    return scope.turns_for_buyer(docs)


@app.get("/rfqs/{rfq_id}/offers")
def list_offers(rfq_id: str, user: User = Depends(current_user),
                orch: Orchestrator = Depends(get_orchestrator)) -> list[dict]:
    _rfq_for(user, rfq_id, orch)
    return scope.clean_json(_offers(user, rfq_id))


@app.get("/rfqs/{rfq_id}/turns")
def list_turns(rfq_id: str, user: User = Depends(current_user),
               orch: Orchestrator = Depends(get_orchestrator)) -> list[dict]:
    _rfq_for(user, rfq_id, orch)
    return scope.clean_json(_turns(user, rfq_id))


# ---------------------------------------------------------------- live updates
def _parse_since(since: str | None) -> datetime | None:
    if not since:
        return None
    try:
        parsed = datetime.fromisoformat(since)
    except ValueError as exc:
        raise HTTPException(422, "since must be an ISO timestamp") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed  # pymongo returns naive UTC datetimes


def _updates(user: User, rfq: dict, since: datetime | None) -> dict:
    offers = _offers(user, rfq["_id"], since)
    turns = _turns(user, rfq["_id"], since)
    stamps = [d["created_at"] for d in offers + turns]
    cursor = max(stamps) if stamps else since
    return scope.clean_json({
        "status": rfq["status"], "round": rfq["round"],
        "offers": offers, "turns": turns,
        "cursor": cursor,  # datetime; clean_json emits explicit UTC
    })


@app.get("/rfqs/{rfq_id}/updates")
def updates(rfq_id: str, since: str | None = Query(default=None),
            user: User = Depends(current_user),
            orch: Orchestrator = Depends(get_orchestrator)) -> dict:
    """Everything new since a cursor. Poll this, or use /stream."""
    rfq = _rfq_for(user, rfq_id, orch)
    return _updates(user, rfq, _parse_since(since))


def _wait_for_change(rfq_id: str, seconds: float) -> None:
    """Block until a change-stream event or the timeout. Standalone MongoDB has
    no change streams, so it degrades to a plain sleep (the caller polls)."""
    try:
        pipeline = [{"$match": {"fullDocument.rfq_id": rfq_id}}]
        with get_db().offers.watch(pipeline, max_await_time_ms=int(seconds * 1000)) as stream:
            stream.try_next()
    except PyMongoError:
        time.sleep(seconds)


@app.get("/rfqs/{rfq_id}/stream")
def stream(rfq_id: str, since: str | None = Query(default=None),
           user: User = Depends(current_user),
           orch: Orchestrator = Depends(get_orchestrator)) -> StreamingResponse:
    """Server-sent events. Uses MongoDB change streams where available, falling
    back to polling. Closes after ~10 minutes; clients reconnect with `since`."""
    _rfq_for(user, rfq_id, orch)
    cursor = _parse_since(since)

    def events():
        nonlocal cursor
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            rfq = get_db().rfqs.find_one({"_id": rfq_id})
            payload = _updates(user, rfq, cursor)
            if payload["offers"] or payload["turns"]:
                cursor = _parse_since(payload["cursor"])
                yield f"data: {json.dumps(payload)}\n\n"
            else:
                yield ": keep-alive\n\n"
            _wait_for_change(rfq_id, 2.0)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})
