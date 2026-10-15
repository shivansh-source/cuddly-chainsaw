# the deployable link :  https://cuddly-chainsaw-smoky.vercel.app/
# The Negotiator: API

Buyers post a bill of materials. Supplier agents negotiate over several rounds, a human on either side can take over (including by voice), and the result is a ranked, evidence-backed recommendation.

This README is the contract for building a client. Every response sample below was captured from the running API.

## Contents

1. [Run it](#1-run-it)
2. [Conventions](#2-conventions)
3. [Authentication](#3-authentication)
4. [Endpoints](#4-endpoints)
5. [Data shapes](#5-data-shapes)
6. [Enum values](#6-enum-values)
7. [What each role can see](#7-what-each-role-can-see)
8. [Live updates](#8-live-updates)
9. [Flows](#9-flows)
10. [Voice](#10-voice)
11. [Errors](#11-errors)
12. [Demo accounts and data](#12-demo-accounts-and-data)
13. [Configuration](#13-configuration)

---

## 1. Run it

```bash
pip install -r requirements.txt
cp .env.example .env          # set MONGODB_URI at least
python scripts/demo_run.py    # create collections, seed, pre-run one auction
uvicorn app.main:app --reload # http://localhost:8000  (interactive docs: /docs)
python -m pytest -q tests     # uses a local MongoDB; set TEST_MONGODB_URI to change
```

- `scripts/seed.py` resets all data and leaves every RFQ in `draft`.
- `scripts/demo_run.py` does the same, then pre-runs `rfq_demo_2` with the deterministic engine so a fresh login already has history. `rfq_demo_1` stays in `draft`.
- A finished RFQ cannot be restarted. Re-run the script to reset.
- `GET /openapi.json` and `/docs` are always the exact, current schema.

## 2. Conventions

| Topic | Rule |
|---|---|
| Base URL | Wherever the app is hosted, no path prefix |
| Format | JSON in, JSON out |
| Auth | `Authorization: Bearer <access_token>` on every route except `/health` and `/auth/login` |
| Timestamps | ISO 8601 with an explicit UTC offset, e.g. `2026-10-15T11:43:01.155000+00:00` |
| Money | Numbers in INR per unit unless a field says otherwise |
| Ids | RFQs and companies use readable string ids (`rfq_demo_1`, `co_sup_a`). Offers and turns use opaque 24-char strings |
| CORS | Allowed origins come from `CORS_ORIGINS` (comma-separated) |
| Unknown or forbidden resource | `404`, not `403`, so ids do not leak |

## 3. Authentication

### `POST /auth/login`
Request
```json
{ "email": "buyer@acme.test", "password": "demo1234" }
```
Response `200`
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5...",
  "token_type": "bearer",
  "role": "buyer",
  "company_id": "co_buy_01"
}
```
- Tokens last 12 hours. There is no refresh; log in again.
- Wrong email and wrong password return the same `401`.
- `role` is `buyer` or `seller`. Role and company come from the token, never from a request body.

### `GET /auth/me`
```json
{ "email": "buyer@acme.test", "role": "buyer", "company_id": "co_buy_01", "company_name": "Acme Robotics Pvt Ltd" }
```

## 4. Endpoints

Role column: **B** buyer only, **S** seller only, **any** either role (with ownership checks).

### Reference
| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/health` | none | `{ "ok": true, "llm": "groq" \| "engine" }` |
| GET | `/companies?kind=buyer\|supplier` | any | List companies |
| GET | `/companies/{company_id}/catalog` | any | Public catalog facts (stock, lead time, MOQ, specs). Never prices |

### RFQs
| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/rfqs` | B | Create an RFQ (status `draft`) |
| GET | `/rfqs` | B | The buyer's own RFQs |
| GET | `/rfqs/{id}` | any | One RFQ, shaped for the caller's role |
| POST | `/rfqs/{id}/start` | B | Open round 0. With `run_all`, play every round and return the recommendation |
| POST | `/rfqs/{id}/rounds` | B | Advance one round. The final round also returns the recommendation |
| GET | `/rfqs/{id}/recommendation` | B | Latest stored recommendation |
| GET | `/rfqs/{id}/offers` | any | Offers (scoped by role) |
| GET | `/rfqs/{id}/turns` | any | Audit trail of moves (scoped and redacted by role) |
| GET | `/rfqs/{id}/updates?since=` | any | Everything new since a cursor |
| GET | `/rfqs/{id}/stream?since=` | any | Server-sent events version of `/updates` |

### Human control
| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/rfqs/{id}/handover` | any | Take over or hand back the caller's own side |
| POST | `/rfqs/{id}/turns` | any | Post a human move (the caller's side must be human-controlled) |
| POST | `/rfqs/{id}/confirm` | any | Confirm your own flagged offer, with a reason |

### Seller area
| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/seller/rfqs` | S | Incoming RFQs the buyer has opened |
| GET | `/seller/products` | S | Own catalog joined with own pricing (floor included) |
| POST | `/seller/products` | S | Add or replace one product (catalog item and pricing rule) |

### Voice
See [section 10](#10-voice).

### Request bodies

`POST /rfqs`
```json
{
  "title": "Sensor node batch",
  "budget": 93000,
  "budget_basis": "landed_incl_tax",
  "currency": "INR",
  "deadline_days": 14,
  "max_rounds": 3,
  "lines": [
    { "mpn": "BME280", "qty": 100, "mandatory": true,
      "required_specs": { "interface": { "op": "==", "value": "I2C" } } }
  ],
  "invite": ["co_sup_a", "co_sup_b"]
}
```
- `budget_basis`: `landed_incl_tax` (default) or `pre_tax`. `max_rounds`: 1 to 5, default 3.
- The buyer company comes from the token.
- `required_specs` comparison `op`: `>=`, `<=`, `==`, `in` (value is a list).

`POST /rfqs/{id}/start`
```json
{ "run_all": false, "engine_only": false }
```
- `run_all`: play every round now, finish, and return the recommendation.
- `engine_only`: never call the LLM. Deterministic and identical every run. Use this for a predictable demo.
- Response without `run_all`: `{ "status": "negotiating", "round": 0 }`.
- Response with `run_all`: `{ "status": "completed", "recommendation": { ... } }`.

`POST /rfqs/{id}/rounds`
- No body. Response `{ "status": "negotiating", "round": 1 }`.
- On the last round: `{ "status": "completed", "round": 3, "recommendation": { ... } }`.
- With 3 rounds there are 4 steps: round 0 (opening quotes) then rounds 1, 2, 3.

`POST /rfqs/{id}/handover`
```json
{ "controller": "human" }
```
`controller` is `human` or `agent`. It changes only the caller's own side. Response `{ "company_id": "co_sup_a", "controller": "human" }`.

`POST /rfqs/{id}/turns` (human move)
```json
{ "mpn": "BME280", "type": "counter", "unit_price": 410, "qty": 100,
  "lead_time_days": 3, "message": "Best I can do", "seller_id": null }
```
- `type`: `propose`, `counter`, `trade`, `ask`, `accept`, `walk_away`. For `accept`, the price is taken from the standing counter-offer.
- A **seller** acts for their own company. A **buyer** must also send `seller_id` (which supplier's thread).
- `qty` defaults to the RFQ line quantity; `lead_time_days` defaults to the catalog value.
- Needs the caller's side to be human-controlled, otherwise `409`.

Response `201`
```json
{
  "turn_id": "6ad0bc504e1406dd5a1b4b02",
  "guardrail": {
    "status": "flagged_outside_authority",
    "reasons": ["price 300.0 below floor 352.5"],
    "override_reason": null,
    "confirmed_by": null
  },
  "offer": { "...": "an Offer, status \"flagged\", source \"human_seller\"" },
  "reply": null,
  "events": ["seller human turn recorded (flagged_outside_authority)"]
}
```
- `reply` is the other side's agent answering immediately (an Offer), or `null`. A flagged offer gets no reply.
- `guardrail.reasons` is only returned to the side that owns the move.

`POST /rfqs/{id}/confirm`
```json
{ "offer_id": "6ad0bc504e1406dd5a1b4b03", "reason": "Clearing old stock" }
```
Appends a new offer version with status `confirmed`. The flagged original is never edited. `422` if the reason is blank.

`POST /seller/products`
```json
{
  "mpn": "LM358", "description": "Dual op-amp", "specs": { "channels": 2 },
  "stock_qty": 2000, "lead_time_days": 4, "moq": 20, "tax_rate": 0.18,
  "list_price": 12, "floor_price": 8,
  "tiers": [{ "min_qty": 100, "discount_pct": 0.05 }],
  "concession_step_pct": 0.25, "max_rounds": 3
}
```
`422` if `floor_price` is above `list_price`.

## 5. Data shapes

### RFQ (buyer view)
```json
{
  "id": "rfq_demo_1",
  "buyer_company_id": "co_buy_01",
  "title": "Sensor node batch",
  "budget": 93000.0,
  "budget_basis": "landed_incl_tax",
  "currency": "INR",
  "deadline": "2026-10-29T11:42:59.161000+00:00",
  "deadline_days": 14,
  "status": "negotiating",
  "round": 0,
  "max_rounds": 3,
  "engine_only": true,
  "lines": [
    { "mpn": "ESP32-WROOM-32E", "qty": 100, "mandatory": true,
      "required_specs": { "flash_mb": { "op": ">=", "value": 4 } } }
  ],
  "participants": [
    { "company_id": "co_buy_01", "side": "buyer",  "controller": "agent", "status": "active" },
    { "company_id": "co_sup_a", "side": "seller", "controller": "agent", "status": "invited" }
  ],
  "buyer_limits": {
    "BME280": { "target": 365.09, "ceiling": 409.08 }
  },
  "created_at": "2026-10-15T11:42:59.161000+00:00"
}
```
- `buyer_limits` exists only after round 0 and only in the buyer's own view.
- `max_rounds` and `engine_only` may be absent on a seeded or unstarted RFQ; treat a missing `max_rounds` as 3 and a missing `engine_only` as false.
- `status` moves `draft` to `negotiating` to `completed`.

### RFQ (seller view)
Same shape without `budget`, `budget_basis` and `buyer_limits`. `participants` lists only the buyer and the caller's own company.

### Offer
```json
{
  "id": "6ad0bc454e1406dd5a1b4ade",
  "rfq_id": "rfq_demo_1",
  "company_id": "co_sup_a",
  "mpn": "ESP32-WROOM-32E",
  "side": "seller",
  "round": 0,
  "version": 1,
  "unit_price": 342.0,
  "qty": 100,
  "lead_time_days": 3,
  "tax_rate": 0.18,
  "tax": 6156.0,
  "shipping": 0.0,
  "total_landed_cost": 40356.0,
  "valid_until": "2026-10-22T11:43:01.155000+00:00",
  "source": "engine",
  "status": "proposed",
  "created_by": "seller:co_sup_a",
  "turn_id": "6ad0bc454e1406dd5a1b4add",
  "created_at": "2026-10-15T11:43:01.155000+00:00"
}
```
- `company_id` is always the **supplier** of the thread, for both seller offers and buyer bids. `side` says who made it.
- Offers are append-only. A revision is a new `version`; read the latest.
- Voice offers also carry `channel: "voice"`, `voice_mode: "live" | "recorded"`, `call_id`, `conversation_id`.

### Turn (one move in the audit trail)
```json
{
  "id": "6ad0bc454e1406dd5a1b4add",
  "rfq_id": "rfq_demo_1",
  "round": 0,
  "participant_id": "co_sup_a",
  "counterparty_id": "co_buy_01",
  "side": "seller",
  "mpn": "ESP32-WROOM-32E",
  "controller": "agent",
  "source": "engine",
  "raw_llm_output": null,
  "validated_action": { "type": "counter", "mpn": "ESP32-WROOM-32E", "unit_price": 342.0,
                        "qty": 100, "lead_time_days": 3, "message": "Concession per pricing policy." },
  "guardrail_result": { "status": "ok", "reasons": [], "override_reason": null, "confirmed_by": null },
  "message": "Concession per pricing policy.",
  "attempts": 0,
  "notes": ["used deterministic fallback"],
  "created_at": "2026-10-15T11:43:01.016000+00:00"
}
```
- `attempts`: number of model tries (0 when no model was used, 2 when the first answer was rejected).
- `notes`: human-readable trace, e.g. `attempt 1: blocked (...)`, `used deterministic fallback`.
- Handover events are turns with `guardrail_result: { "event": "controller_switch", "from": "agent", "to": "human" }` and `validated_action: null`.
- `raw_llm_output`, `notes` and `guardrail_result.reasons` are blanked for the **other** side's turns. See section 7.

### Recommendation
```json
{
  "id": "6ad0bc674e1406dd5a1b4b46",
  "explanation": "2 of 3 suppliers eligible. Top: Silicon Mart - Lowest landed cost; 4-day delivery; negotiated 8% below initial quote.",
  "created_at": "2026-10-15T11:43:35.156000+00:00",
  "ranked": [
    {
      "company_id": "co_sup_c",
      "name": "Silicon Mart",
      "eligible": true,
      "source": "engine",
      "line_sources": { "ESP32-WROOM-32E": "engine", "BME280": "engine", "USB4105-GF-A": "engine" },
      "landed_cost": 89251.66,
      "lead_time_days": 4,
      "total_score": 85.44,
      "breakdown": { "cost": 100.0, "delivery": 100.0, "reliability": 65.0, "improvement": 37.9 },
      "improvement_pct": 0.0758,
      "eligibility_failures": [],
      "flags": [],
      "explanation": "Lowest landed cost; 4-day delivery; negotiated 8% below initial quote"
    }
  ],
  "rejected": [
    {
      "company_id": "co_sup_b",
      "name": "Circuit Bazaar",
      "eligible": false,
      "source": "engine",
      "landed_cost": 83142.8,
      "lead_time_days": 21,
      "total_score": null,
      "breakdown": {},
      "eligibility_failures": ["USB4105-GF-A: lead time 21d beyond deadline 14d"],
      "explanation": "Not eligible: USB4105-GF-A: lead time 21d beyond deadline 14d"
    }
  ]
}
```
- `ranked` is eligible offers, best first. `rejected` is ineligible offers with reasons; they are never silently dropped.
- `breakdown` values are 0 to 100 per criterion. Weights: cost 50%, delivery 20%, reliability 15%, improvement 15%.
- `source` is the most human-sourced line; `line_sources` keeps each line's own label.
- `flags` holds soft warnings (e.g. `reliability unknown (scored 0)`).
- `improvement_pct` is a fraction (0.0758 is 7.58%) versus the same-quantity opening quote.

### Seller product (`GET /seller/products`)
```json
{
  "company_id": "co_sup_a", "mpn": "AMS1117-3.3", "description": "3.3V LDO regulator",
  "specs": { "vout_v": 3.3, "iout_ma": 1000, "package": "SOT-223" },
  "stock_qty": 2400, "lead_time_days": 3, "moq": 10, "tax_rate": 0.18,
  "pricing": {
    "list_price": 9.0, "floor_price": 7.5,
    "tiers": [{ "min_qty": 50, "discount_pct": 0.02 }],
    "concession_step_pct": 0.25, "max_rounds": 3
  }
}
```

### Updates (`GET /rfqs/{id}/updates`)
```json
{
  "status": "negotiating",
  "round": 0,
  "offers": [ { "...": "Offer" } ],
  "turns":  [ { "...": "Turn" } ],
  "cursor": "2026-10-15T11:43:08.286000+00:00"
}
```

## 6. Enum values

| Field | Values |
|---|---|
| `role` / `side` | `buyer`, `seller` |
| `controller` | `agent`, `human` (turns can also show `engine`) |
| Offer `source` | `engine`, `llm_agent`, `human_seller`, `human_buyer`, `voice_confirmed`, `seeded` |
| Offer `status` | `proposed`, `accepted`, `flagged`, `confirmed` (`countered`, `rejected` are reserved) |
| RFQ `status` | `draft`, `negotiating`, `completed` (`open`, `cancelled` reserved) |
| Action `type` | `propose`, `counter`, `trade`, `ask`, `accept`, `walk_away` |
| `guardrail.status` | `ok`, `blocked`, `flagged_outside_authority`, `override_confirmed` |
| Participant `status` | `invited`, `active`, `declined` |
| Voice call `mode` | `live`, `recorded` |
| Voice call `status` | `initiated`, `completed`, `unconfirmed`, `failed` |

Meaning of the labels a client must show faithfully:

- `engine`: produced by deterministic code (the concession schedule or fallback).
- `llm_agent`: produced by the model and approved by the guardrail.
- `human_seller` / `human_buyer`: typed by a person.
- `voice_confirmed`: terms confirmed by read-back on a call. Check `voice_mode` to tell a live call from a `recorded` one.
- `flagged` offers are outside the author's authority and **do not count** until confirmed.

## 7. What each role can see

| Data | Buyer | Seller |
|---|---|---|
| Own RFQs | all of theirs | only RFQs they are invited to **and** the buyer has opened |
| RFQ budget, `buyer_limits` | yes (own) | never |
| Other suppliers' identities and offers | yes | never |
| Seller floors and pricing rules | never | own only, via `/seller/products` |
| Offers | all suppliers' | own thread only |
| Turns | whole thread | own thread only |
| Recommendation | yes | no (`403`) |
| `raw_llm_output`, `notes`, `guardrail_result.reasons` | on the buyer's own turns; blanked on sellers' | on their own turns; blanked on buyers' |

Why the redaction: reasons such as `price 250 below floor 295` would reveal the other side's limit.

## 8. Live updates

Two equivalent options, both scoped to the caller's role:

**Polling** `GET /rfqs/{id}/updates?since=<cursor>`
1. First call with no `since`: returns everything.
2. Store the returned `cursor`.
3. Next call: pass it as `since`. Only newer offers and turns come back.
4. If nothing is new, `offers` and `turns` are empty and the `cursor` is unchanged.

**Streaming** `GET /rfqs/{id}/stream?since=<cursor>` (`text/event-stream`)
- Each event is `data: <JSON>` with the same shape as `/updates`.
- Idle periods send `: keep-alive` comment lines.
- The stream closes after about 10 minutes. Reconnect with the last `cursor` as `since`.
- Browsers cannot set an `Authorization` header on `EventSource`. Use `fetch` with a streaming reader, or poll `/updates`.

## 9. Flows

### A. Run an auction in one call
1. `POST /auth/login` as a buyer.
2. `POST /rfqs/{id}/start` with `{ "run_all": true, "engine_only": true }`.
3. Render `recommendation.ranked` and `recommendation.rejected`.
4. `GET /rfqs/{id}/offers` and `/turns` for the evidence behind each number.

### B. Step through rounds
1. `POST /rfqs/{id}/start`, then poll `/updates`.
2. `POST /rfqs/{id}/rounds` once per round until `status` is `completed`.

### C. Seller takes over a negotiation
1. Seller: `GET /seller/rfqs`, open an RFQ, `POST /rfqs/{id}/handover` with `{ "controller": "human" }`. The engine stops moving this supplier's thread.
2. Seller: `POST /rfqs/{id}/turns` with a price. If in authority, the response includes the buyer agent's `reply`.
3. If the response has `guardrail.status: "flagged_outside_authority"`, show it as pending and ask for a reason, then `POST /rfqs/{id}/confirm`.
4. Seller: `POST /rfqs/{id}/handover` with `{ "controller": "agent" }` to hand back.

### D. Buyer takes over
1. Buyer: `POST /rfqs/{id}/handover` with `{ "controller": "human" }`.
2. Buyer: `POST /rfqs/{id}/turns` with `seller_id` and a price.
3. Bids above the buyer's ceiling are flagged, not blocked, and need confirmation.

### E. Seller adds a product
`POST /seller/products`, then `GET /seller/products` to show it.

## 10. Voice

The ElevenLabs agent plays the buyer's voice and a human on the phone is the supplier's rep. While a call is open, that supplier's side is put under human control and handed back when the call ends.

| Method | Path | Caller | Purpose |
|---|---|---|---|
| POST | `/rfqs/{id}/voice/session` | buyer (JWT) | Start a session (e.g. browser widget). Body `{ "seller_id": "co_sup_a" }` |
| POST | `/rfqs/{id}/voice/call` | buyer (JWT) | Place an outbound phone call. Body `{ "seller_id", "to_number" }`. `503` until ElevenLabs is configured |
| POST | `/rfqs/{id}/voice/recorded` | buyer (JWT) | Replay the pre-recorded demo call, labeled `recorded`. Body `{ "seller_id" }` |
| GET | `/rfqs/{id}/voice` | any | Calls with transcripts (a seller sees only their own) |
| POST | `/voice/tools/get_current_offer` | ElevenLabs | Server tool. Header `X-Voice-Session` |
| POST | `/voice/tools/propose_offer` | ElevenLabs | Server tool |
| POST | `/voice/tools/record_seller_offer` | ElevenLabs | Server tool |
| POST | `/voice/tools/confirm_terms` | ElevenLabs | Server tool |
| POST | `/voice/webhook` | ElevenLabs | Signed post-call webhook. Always answers `200` unless the signature is invalid |

`POST /rfqs/{id}/voice/session` response `201`
```json
{
  "call_id": "9f1c...",
  "session_token": "eyJ...",
  "dynamic_variables": {
    "session_token": "eyJ...", "call_id": "9f1c...", "rfq_id": "rfq_demo_1",
    "seller_id": "co_sup_a", "supplier_name": "Volt Components",
    "buyer_name": "Acme Robotics Pvt Ltd", "deadline_days": 14,
    "lines": "[{\"mpn\":\"BME280\",\"qty\":100}]"
  }
}
```
Pass `dynamic_variables` to the ElevenLabs widget or SDK when starting the conversation. The session token is not interchangeable with a login token.

Only a confirmed read-back becomes an offer. It is labeled `voice_confirmed`, and a confirmed in-authority price locks that line against further concessions.

## 11. Errors

All errors are `{ "detail": "<message>" }`, except `422` which returns FastAPI's validation list.

| Status | Meaning | Example `detail` |
|---|---|---|
| 401 | Missing, expired or invalid token; bad login | `missing bearer token` |
| 403 | Wrong role | `buyers only` |
| 404 | Not found, or not yours | `RFQ not found` |
| 409 | Wrong state | `RFQ is completed, not negotiating`; `agent-controlled; take over first` |
| 422 | Invalid body | blank confirm reason, floor above list, `since must be an ISO timestamp` |
| 502 | Voice provider refused the call | |
| 503 | Voice provider not configured | `not configured: ELEVENLABS_API_KEY` |

## 12. Demo accounts and data

Every account uses password `demo1234`.

| Buyer | Email | RFQ |
|---|---|---|
| Acme Robotics (`co_buy_01`) | `buyer@acme.test` | `rfq_demo_1` (the live demo; left in `draft`) |
| Nimbus IoT Labs | `buyer@nimbus.test` | `rfq_demo_2` (pre-run) |
| SkyForge Drones | `buyer@skyforge.test` | `rfq_demo_3` |
| PulseWear Devices | `buyer@pulsewear.test` | `rfq_demo_4` |
| AgriSense Systems | `buyer@agrisense.test` | `rfq_demo_5` |
| VoltCharge EV | `buyer@voltcharge.test` | `rfq_demo_6` |
| MakerKit India | `buyer@makerkit.test` | `rfq_demo_7` |
| Campus Embedded Lab | `buyer@campuslab.test` | `rfq_demo_8` |
| ControlWorks Industrial | `buyer@controlworks.test` | `rfq_demo_9` |

| Seller | Email | Character |
|---|---|---|
| Volt Components (`co_sup_a`) | `sales@volt.test` | Fast, reliable, mid-price |
| Circuit Bazaar (`co_sup_b`) | `sales@circuitbazaar.test` | Cheapest, slow on some parts |
| Silicon Mart (`co_sup_c`) | `sales@siliconmart.test` | Unverified, lower reliability |
| Hexa Electronics (`co_sup_d`) | `sales@hexa.test` | Premium, very reliable |
| QuickChip Traders (`co_sup_e`) | `sales@quickchip.test` | Aggressive concessions, high MOQ |
| Bharat Micro Supply (`co_sup_f`) | `sales@bharatmicro.test` | Broad catalog, one part missing |

Parts (illustrative INR prices, not from live listings): `ESP32-WROOM-32E`, `BME280`, `USB4105-GF-A`, `STM32F103C8T6`, `AMS1117-3.3`.

Expected result of `rfq_demo_1` with `engine_only: true` and no human intervention: Volt Components and Silicon Mart eligible, Circuit Bazaar rejected (`USB4105-GF-A: lead time 21d beyond deadline 14d`).

## 13. Configuration

| Variable | Purpose |
|---|---|
| `MONGODB_URI`, `MONGODB_DB` | Database (MongoDB Atlas recommended) |
| `JWT_SECRET` | Signs login and voice session tokens. Change it |
| `GROQ_API_KEY`, `GROQ_MODEL` | LLM negotiation. Unset means the engine runs and every offer is `engine` |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, `ELEVENLABS_PHONE_NUMBER_ID` | Outbound voice calls |
| `ELEVENLABS_WEBHOOK_SECRET` | Verifies the post-call webhook signature |
| `CORS_ORIGINS` | Comma-separated frontend origins |
| `TEST_MONGODB_URI` | Where `pytest` runs (default local MongoDB) |

## Notes for client authors

- Display `source` and `status` on every offer. The system never mixes simulated and real offers silently; the client should not either.
- `flagged` offers must be visibly pending. They do not count toward a recommendation until confirmed.
- A seller must never be shown a field they should not have; the API already omits them, so render only what is returned.
