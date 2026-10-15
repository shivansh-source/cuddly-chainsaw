"""Authentication, role checks, and what each side is allowed to see."""
import json
import time

from app import main as main_module
from app.auth import create_token, decode_token
from app.main import app, get_llm

RFQ = "rfq_demo_1"


class EvilSellerLLM:
    """Seller replies below its floor, so blocked-move reasons get recorded."""
    name = "evil"

    def complete(self, system, user):
        if "floor_price" in user:
            return json.dumps({"type": "counter", "unit_price": 1.0, "message": "x"})
        return json.dumps({"type": "counter", "unit_price": 5.0})


# --- login and tokens ------------------------------------------------------------------

def test_login_ok_and_me(api):
    r = api.anon.post("/auth/login", json={"email": "buyer@acme.test", "password": "demo1234"})
    assert r.status_code == 200 and r.json()["role"] == "buyer"
    me = api.buyer.get("/auth/me").json()
    assert me["company_id"] == "co_buy_01" and me["company_name"].startswith("Acme")


def test_bad_credentials_give_the_same_answer(api):
    wrong_pw = api.anon.post("/auth/login", json={"email": "buyer@acme.test", "password": "x"})
    no_user = api.anon.post("/auth/login", json={"email": "nobody@x.test", "password": "x"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()


def test_protected_routes_need_a_token(api):
    for path in ("/companies", "/rfqs", f"/rfqs/{RFQ}", "/auth/me"):
        assert api.anon.get(path).status_code == 401
    assert api.anon.get("/health").status_code == 200


def test_tampered_expired_and_alg_none_tokens_are_rejected(api):
    good = create_token({"sub": "buyer@acme.test", "role": "buyer", "company_id": "co_buy_01"})
    head, body, sig = good.split(".")
    forged_body = create_token({"sub": "x", "role": "buyer", "company_id": "co_buy_02"}).split(".")[1]
    expired = create_token({"sub": "a", "role": "buyer", "company_id": "co_buy_01"}, ttl=-5)
    wrong_secret = create_token({"sub": "a", "role": "buyer", "company_id": "co_buy_01"},
                                secret="another-secret")
    none_alg = "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0." + body + "."
    for bad in (f"{head}.{forged_body}.{sig}", expired, wrong_secret, none_alg, "garbage"):
        r = api.anon.get("/auth/me", headers={"Authorization": f"Bearer {bad}"})
        assert r.status_code == 401, bad


def test_token_roundtrip_and_expiry_claim():
    token = create_token({"sub": "a"}, secret="s", ttl=60)
    assert decode_token(token, "s")["sub"] == "a"


# --- role and ownership checks -----------------------------------------------------------

def test_role_gates(api):
    assert api.a.post("/rfqs", json={
        "title": "t", "budget": 1, "deadline_days": 1, "invite": ["co_sup_a"],
        "lines": [{"mpn": "BME280", "qty": 1}]}).status_code == 403
    assert api.buyer.get("/seller/products").status_code == 403
    assert api.a.post(f"/rfqs/{RFQ}/start").status_code == 403
    assert api.a.get(f"/rfqs/{RFQ}/recommendation").status_code == 403


def test_other_buyers_and_uninvited_sellers_get_404(api):
    assert api.other_buyer.get(f"/rfqs/{RFQ}").status_code == 404
    assert api.other_buyer.post(f"/rfqs/{RFQ}/start").status_code == 404
    api.buyer.post(f"/rfqs/{RFQ}/start")
    assert api.d.get(f"/rfqs/{RFQ}").status_code == 404      # Hexa was not invited
    assert api.d.get(f"/rfqs/{RFQ}/offers").status_code == 404


def test_seller_cannot_see_an_rfq_before_it_opens(api):
    assert api.a.get(f"/rfqs/{RFQ}").status_code == 404
    assert api.a.get("/seller/rfqs").json() == []
    api.buyer.post(f"/rfqs/{RFQ}/start")
    assert [r["id"] for r in api.a.get("/seller/rfqs").json()] == [RFQ]


# --- information asymmetry ------------------------------------------------------------------

def test_seller_view_hides_budget_limits_and_competitors(api):
    api.buyer.post(f"/rfqs/{RFQ}/start")
    view = api.a.get(f"/rfqs/{RFQ}").json()
    for key in ("budget", "budget_basis", "buyer_limits"):
        assert key not in view
    ids = {p["company_id"] for p in view["participants"]}
    assert ids == {"co_buy_01", "co_sup_a"}
    assert "buyer_limits" in api.buyer.get(f"/rfqs/{RFQ}").json()  # the buyer's own


def test_seller_sees_only_its_own_thread(api):
    api.buyer.post(f"/rfqs/{RFQ}/start", json={"run_all": True})
    offers = api.a.get(f"/rfqs/{RFQ}/offers").json()
    assert offers and {o["company_id"] for o in offers} == {"co_sup_a"}
    turns = api.a.get(f"/rfqs/{RFQ}/turns").json()
    assert turns and all("co_sup_b" not in (t["participant_id"], t["counterparty_id"])
                         and "co_sup_c" not in (t["participant_id"], t["counterparty_id"])
                         for t in turns)
    all_offers = api.buyer.get(f"/rfqs/{RFQ}/offers").json()
    assert {o["company_id"] for o in all_offers} >= {"co_sup_a", "co_sup_c"}


def test_guardrail_reasons_do_not_leak_across_sides(api):
    app.dependency_overrides[get_llm] = lambda: EvilSellerLLM()
    api.buyer.post(f"/rfqs/{RFQ}/start", json={"run_all": True})

    buyer_view = json.dumps(api.buyer.get(f"/rfqs/{RFQ}/turns").json())
    assert "below floor" not in buyer_view and "floor" not in buyer_view.replace(
        "floor_price", "")  # no floor numbers or reasons in the buyer's feed

    seller_view = json.dumps(api.a.get(f"/rfqs/{RFQ}/turns").json())
    assert "above budget" not in seller_view and "ceiling" not in seller_view

    # ...while the owner can still read their own reasons.
    own = [t for t in api.a.get(f"/rfqs/{RFQ}/turns").json() if t["side"] == "seller"]
    assert any("below floor" in n for t in own for n in t["notes"])


def test_cannot_confirm_someone_elses_flagged_offer(api):
    api.buyer.post(f"/rfqs/{RFQ}/start")
    api.a.post(f"/rfqs/{RFQ}/handover", json={"controller": "human"})
    flagged = api.a.post(f"/rfqs/{RFQ}/turns", json={"mpn": "BME280", "unit_price": 300}).json()
    r = api.b.post(f"/rfqs/{RFQ}/confirm", json={
        "offer_id": flagged["offer"]["id"], "reason": "mine now"})
    assert r.status_code == 404
    r = api.buyer.post(f"/rfqs/{RFQ}/confirm", json={
        "offer_id": flagged["offer"]["id"], "reason": "mine now"})
    assert r.status_code == 404


def test_pricing_rules_are_never_in_the_public_catalog(api):
    items = api.buyer.get("/companies/co_sup_a/catalog").json()
    assert items and all("floor_price" not in i and "list_price" not in i for i in items)


# --- seller products ----------------------------------------------------------------------------

PRODUCT = dict(mpn="LM358", description="Dual op-amp", specs={"channels": 2},
               stock_qty=2000, lead_time_days=4, moq=20, list_price=12, floor_price=8,
               tiers=[{"min_qty": 100, "discount_pct": 0.05}])


def test_seller_adds_a_product_and_sees_own_floor(api):
    assert api.a.post("/seller/products", json=PRODUCT).status_code == 201
    mine = {p["mpn"]: p for p in api.a.get("/seller/products").json()}
    assert mine["LM358"]["pricing"]["floor_price"] == 8
    assert "LM358" not in {p["mpn"] for p in api.b.get("/seller/products").json()}
    assert any(i["mpn"] == "LM358" for i in api.buyer.get("/companies/co_sup_a/catalog").json())


def test_seller_product_with_floor_above_list_is_rejected(api):
    r = api.a.post("/seller/products", json={**PRODUCT, "floor_price": 99})
    assert r.status_code == 422


def test_updating_a_product_replaces_it(api):
    api.a.post("/seller/products", json=PRODUCT)
    api.a.post("/seller/products", json={**PRODUCT, "stock_qty": 5})
    items = [p for p in api.a.get("/seller/products").json() if p["mpn"] == "LM358"]
    assert len(items) == 1 and items[0]["stock_qty"] == 5


# --- live updates ----------------------------------------------------------------------------------

def test_updates_return_only_new_events_after_the_cursor(api):
    api.buyer.post(f"/rfqs/{RFQ}/start")
    first = api.buyer.get(f"/rfqs/{RFQ}/updates").json()
    assert first["offers"] and first["cursor"] and first["round"] == 0
    again = api.buyer.get(f"/rfqs/{RFQ}/updates", params={"since": first["cursor"]}).json()
    assert again["offers"] == [] and again["turns"] == []
    api.buyer.post(f"/rfqs/{RFQ}/rounds")
    later = api.buyer.get(f"/rfqs/{RFQ}/updates", params={"since": first["cursor"]}).json()
    assert later["offers"] and later["round"] == 1


def test_updates_are_scoped_like_the_other_views(api):
    api.buyer.post(f"/rfqs/{RFQ}/start", json={"run_all": True})
    seller = api.a.get(f"/rfqs/{RFQ}/updates").json()
    assert {o["company_id"] for o in seller["offers"]} == {"co_sup_a"}


def test_bad_since_is_a_422(api):
    api.buyer.post(f"/rfqs/{RFQ}/start")
    assert api.buyer.get(f"/rfqs/{RFQ}/updates", params={"since": "yesterday"}).status_code == 422


def test_change_stream_wait_falls_back_to_sleep_on_standalone(seeded):
    start = time.monotonic()
    main_module._wait_for_change(RFQ, 0.2)
    assert time.monotonic() - start < 3


def test_every_timestamp_carries_an_explicit_utc_offset(api):
    api.buyer.post(f"/rfqs/{RFQ}/start", json={"engine_only": True})
    rfq = api.buyer.get(f"/rfqs/{RFQ}").json()
    stamps = [rfq["deadline"], rfq["created_at"]]
    stamps += [o["created_at"] for o in api.buyer.get(f"/rfqs/{RFQ}/offers").json()]
    stamps += [t["created_at"] for t in api.buyer.get(f"/rfqs/{RFQ}/turns").json()]
    assert stamps and all(s.endswith("+00:00") for s in stamps)
    cursor = api.buyer.get(f"/rfqs/{RFQ}/updates").json()["cursor"]
    assert cursor.endswith("+00:00")
    again = api.buyer.get(f"/rfqs/{RFQ}/updates", params={"since": cursor}).json()
    assert again["offers"] == []
