"""Illustrative seed data. Prices are INR and NOT sourced from live listings.

Deterministic: no randomness, so every run produces the same demo.
Spec keys carry their unit (flash_mb, iout_ma, temp_max_c).
"""
from datetime import datetime, timedelta, timezone
from math import ceil

TAX_RATE = 0.18
DEMO_PASSWORD = "demo1234"

# mpn -> description, illustrative base list price (INR), default specs, bulk part?
PRODUCTS = {
    "ESP32-WROOM-32E": dict(
        description="ESP32 Wi-Fi/BT module", base=360.0, bulk=False,
        specs={"flash_mb": 4, "interface": "UART", "temp_max_c": 85}),
    "BME280": dict(
        description="Temperature/humidity/pressure sensor", base=430.0, bulk=False,
        specs={"interface": "I2C", "supply_v_max": 3.6, "package": "LGA-8"}),
    "USB4105-GF-A": dict(
        description="USB Type-C 16-pin receptacle", base=19.0, bulk=True,
        specs={"pins": 16, "mount": "SMD", "current_a": 3}),
    "STM32F103C8T6": dict(
        description="Cortex-M3 microcontroller", base=190.0, bulk=False,
        specs={"flash_kb": 64, "core": "Cortex-M3", "package": "LQFP48"}),
    "AMS1117-3.3": dict(
        description="3.3V LDO regulator", base=9.0, bulk=True,
        specs={"vout_v": 3.3, "iout_ma": 1000, "package": "SOT-223"}),
}

# Seller personalities. price_mult scales base list; floor_ratio sets floor/list.
SELLERS = [
    dict(id="co_sup_a", slug="volt", name="Volt Components", location="Delhi", verified=True,
         reliability=90, price_mult=1.00, floor_ratio=0.82, step=0.25, lead=3, stock=600, moq=10),
    dict(id="co_sup_b", slug="circuitbazaar", name="Circuit Bazaar", location="Mumbai", verified=True,
         reliability=78, price_mult=0.94, floor_ratio=0.80, step=0.30, lead=5, stock=400, moq=25),
    dict(id="co_sup_c", slug="siliconmart", name="Silicon Mart", location="Chennai", verified=False,
         reliability=65, price_mult=1.04, floor_ratio=0.83, step=0.20, lead=4, stock=250, moq=5),
    dict(id="co_sup_d", slug="hexa", name="Hexa Electronics", location="Pune", verified=True,
         reliability=96, price_mult=1.12, floor_ratio=0.92, step=0.10, lead=2, stock=400, moq=10),
    dict(id="co_sup_e", slug="quickchip", name="QuickChip Traders", location="Ahmedabad", verified=True,
         reliability=72, price_mult=0.97, floor_ratio=0.74, step=0.40, lead=6, stock=800, moq=100),
    dict(id="co_sup_f", slug="bharatmicro", name="Bharat Micro Supply", location="Hyderabad", verified=True,
         reliability=84, price_mult=1.00, floor_ratio=0.85, step=0.20, lead=4, stock=500, moq=20),
]

# (seller_id, mpn) -> overrides on stock / lead / specs. Each one exists to
# produce a specific, explainable eligibility outcome in the demo.
OVERRIDES: dict[tuple[str, str], dict] = {
    ("co_sup_a", "ESP32-WROOM-32E"): dict(specs={"flash_mb": 8}),
    ("co_sup_d", "ESP32-WROOM-32E"): dict(specs={"flash_mb": 8, "temp_max_c": 105}),
    ("co_sup_b", "ESP32-WROOM-32E"): dict(specs={"temp_max_c": 70}),     # commercial grade
    ("co_sup_b", "USB4105-GF-A"): dict(lead=21),                          # slow connector
    ("co_sup_f", "ESP32-WROOM-32E"): dict(specs={"flash_mb": 8}),
    ("co_sup_c", "BME280"): dict(specs={"interface": "SPI"}),
    ("co_sup_e", "USB4105-GF-A"): dict(specs={"current_a": 1.5}),
    ("co_sup_e", "STM32F103C8T6"): dict(specs={"package": "UFQFPN48"}),
    ("co_sup_e", "AMS1117-3.3"): dict(specs={"iout_ma": 800}),
}

# Seller -> mpns NOT carried (partial coverage).
NOT_CARRIED = {"co_sup_f": {"STM32F103C8T6"}}

TIERS = [
    {"min_qty": 50, "discount_pct": 0.02},
    {"min_qty": 100, "discount_pct": 0.05},
    {"min_qty": 500, "discount_pct": 0.08},
]


def _req(op: str, value) -> dict:
    return {"op": op, "value": value}


# (buyer_id, slug, name, location, deadline_days, rfq_title, invited sellers, lines)
BUYERS_AND_RFQS = [
    ("co_buy_01", "acme", "Acme Robotics Pvt Ltd", "Bengaluru", 14, "Sensor node batch",
     ["co_sup_a", "co_sup_b", "co_sup_c"],
     [("ESP32-WROOM-32E", 100, {"flash_mb": _req(">=", 4)}),
      ("BME280", 100, {}), ("USB4105-GF-A", 200, {})]),
    ("co_buy_02", "nimbus", "Nimbus IoT Labs", "Pune", 21, "Gateway pilot run",
     ["co_sup_a", "co_sup_d", "co_sup_e", "co_sup_f"],
     [("ESP32-WROOM-32E", 500, {"flash_mb": _req(">=", 8)}),
      ("BME280", 500, {}), ("AMS1117-3.3", 1000, {})]),
    ("co_buy_03", "skyforge", "SkyForge Drones", "Hyderabad", 10, "Flight controller rev B",
     ["co_sup_a", "co_sup_b", "co_sup_d", "co_sup_e"],
     [("STM32F103C8T6", 200, {"flash_kb": _req(">=", 64)}),
      ("BME280", 200, {}), ("USB4105-GF-A", 200, {})]),
    ("co_buy_04", "pulsewear", "PulseWear Devices", "Chennai", 12, "Wearable prototype lot",
     ["co_sup_a", "co_sup_b", "co_sup_c", "co_sup_d"],
     [("ESP32-WROOM-32E", 300, {"temp_max_c": _req(">=", 85)}), ("BME280", 300, {})]),
    ("co_buy_05", "agrisense", "AgriSense Systems", "Nagpur", 30, "Field sensor rollout",
     ["co_sup_a", "co_sup_c", "co_sup_e", "co_sup_f"],
     [("ESP32-WROOM-32E", 150, {}),
      ("BME280", 400, {"interface": _req("==", "I2C")}), ("AMS1117-3.3", 400, {})]),
    ("co_buy_06", "voltcharge", "VoltCharge EV", "Ahmedabad", 15, "Charger controller build",
     ["co_sup_a", "co_sup_b", "co_sup_d", "co_sup_e"],
     [("STM32F103C8T6", 300, {}), ("AMS1117-3.3", 600, {}), ("USB4105-GF-A", 600, {})]),
    ("co_buy_07", "makerkit", "MakerKit India", "Jaipur", 25, "Hobby kit batch",
     ["co_sup_a", "co_sup_b", "co_sup_e", "co_sup_f"],
     [("ESP32-WROOM-32E", 600, {}), ("USB4105-GF-A", 1000, {}), ("AMS1117-3.3", 1000, {})]),
    ("co_buy_08", "campuslab", "Campus Embedded Lab", "Kanpur", 20, "Teaching lab kits",
     ["co_sup_a", "co_sup_c", "co_sup_d", "co_sup_f"],
     [("BME280", 50, {}), ("STM32F103C8T6", 50, {}),
      ("ESP32-WROOM-32E", 50, {"flash_mb": _req(">=", 8)})]),
    ("co_buy_09", "controlworks", "ControlWorks Industrial", "Coimbatore", 18, "PLC IO module",
     ["co_sup_a", "co_sup_d", "co_sup_e", "co_sup_f"],
     [("STM32F103C8T6", 350, {"package": _req("==", "LQFP48")}),
      ("AMS1117-3.3", 350, {"iout_ma": _req(">=", 1000)}),
      ("USB4105-GF-A", 350, {"current_a": _req(">=", 3)})]),
]


def companies() -> list[dict]:
    out = [
        {"_id": b[0], "name": b[2], "kind": "buyer", "location": b[3],
         "verified": True, "reliability_score": 0}
        for b in BUYERS_AND_RFQS
    ]
    out += [
        {"_id": s["id"], "name": s["name"], "kind": "supplier", "location": s["location"],
         "verified": s["verified"], "reliability_score": s["reliability"]}
        for s in SELLERS
    ]
    return out


def users() -> list[tuple[str, str, str]]:
    return (
        [(f"buyer@{b[1]}.test", "buyer", b[0]) for b in BUYERS_AND_RFQS]
        + [(f"sales@{s['slug']}.test", "seller", s["id"]) for s in SELLERS]
    )


def _supply():
    """Yield (seller, mpn, product, list_price, floor, stock, lead, moq, specs)."""
    for s in SELLERS:
        for mpn, p in PRODUCTS.items():
            if mpn in NOT_CARRIED.get(s["id"], set()):
                continue
            ov = OVERRIDES.get((s["id"], mpn), {})
            list_price = round(p["base"] * s["price_mult"] * 2) / 2
            floor = min(list_price, round(list_price * s["floor_ratio"] * 2) / 2)
            stock = ov.get("stock", s["stock"] * (4 if p["bulk"] else 1))
            specs = {**p["specs"], **ov.get("specs", {})}
            yield (s, mpn, p, list_price, floor, stock,
                   ov.get("lead", s["lead"]), s["moq"], specs)


def catalog_items() -> list[dict]:
    return [
        {"company_id": s["id"], "mpn": mpn, "description": p["description"],
         "specs": specs, "stock_qty": stock, "lead_time_days": lead,
         "moq": moq, "tax_rate": TAX_RATE}
        for s, mpn, p, _lp, _fp, stock, lead, moq, specs in _supply()
    ]


def pricing_rules() -> list[dict]:
    now = datetime.now(timezone.utc)
    return [
        {"company_id": s["id"], "mpn": mpn, "list_price": lp, "floor_price": fp,
         "tiers": TIERS, "concession_step_pct": s["step"], "max_rounds": 3,
         "valid_from": now, "valid_to": now + timedelta(days=90)}
        for s, mpn, _p, lp, fp, _stock, _lead, _moq, _specs in _supply()
    ]


def rfqs() -> list[dict]:
    now = datetime.now(timezone.utc)
    out = []
    for i, (cid, _slug, _name, _loc, days, title, invited, lines) in enumerate(BUYERS_AND_RFQS, 1):
        base_total = sum(PRODUCTS[m]["base"] * q for m, q, _ in lines)
        budget = ceil(base_total * (1 + TAX_RATE) * 0.95 / 1000) * 1000
        out.append({
            "_id": f"rfq_demo_{i}",
            "buyer_company_id": cid,
            "title": title,
            "budget": float(budget),
            "budget_basis": "landed_incl_tax",
            "currency": "INR",
            "deadline": now + timedelta(days=days),
            "deadline_days": days,
            "status": "draft",
            "round": 0,
            "lines": [
                {"mpn": m, "qty": q, "required_specs": rs, "mandatory": True}
                for m, q, rs in lines
            ],
            "participants": [
                {"company_id": cid, "side": "buyer", "controller": "agent", "status": "active"},
                *[{"company_id": sid, "side": "seller", "controller": "agent", "status": "invited"}
                  for sid in invited],
            ],
            "created_at": now,
        })
    return out
