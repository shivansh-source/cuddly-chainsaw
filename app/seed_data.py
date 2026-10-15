"""Illustrative seed data. Prices are INR and NOT sourced from live listings."""
from datetime import datetime, timedelta, timezone

BUYER_ID = "co_buyer_acme"

MPNS = {
    "ESP32-WROOM-32E": "ESP32 Wi-Fi/BT module, 4MB flash",
    "BME280": "Temperature/humidity/pressure sensor, I2C/SPI",
    "USB4105-GF-A": "USB Type-C 16-pin receptacle, SMD",
}

COMPANIES = [
    {"_id": BUYER_ID, "name": "Acme Robotics Pvt Ltd", "kind": "buyer", "location": "Bengaluru",
     "verified": True, "reliability_score": 0},
    {"_id": "co_sup_a", "name": "Volt Components", "kind": "supplier", "location": "Delhi",
     "verified": True, "reliability_score": 90},
    {"_id": "co_sup_b", "name": "Circuit Bazaar", "kind": "supplier", "location": "Mumbai",
     "verified": True, "reliability_score": 78},
    {"_id": "co_sup_c", "name": "Silicon Mart", "kind": "supplier", "location": "Chennai",
     "verified": False, "reliability_score": 65},
]

# company -> mpn -> (list, floor, stock, lead_days, moq, step)
# Designed so the demo has: a clear winner (A), a cheap-but-slow supplier (B,
# fails the lead-time deadline on USB-C), and a short-stock supplier (C).
SUPPLY = {
    "co_sup_a": {
        "ESP32-WROOM-32E": (360, 295, 500, 3, 10, 0.25),
        "BME280": (430, 350, 400, 3, 10, 0.25),
        "USB4105-GF-A": (19, 13.5, 2000, 3, 50, 0.25),
    },
    "co_sup_b": {
        "ESP32-WROOM-32E": (340, 270, 300, 5, 25, 0.30),
        "BME280": (410, 320, 300, 5, 25, 0.30),
        "USB4105-GF-A": (17, 11.5, 1000, 21, 100, 0.30),
    },
    "co_sup_c": {
        "ESP32-WROOM-32E": (375, 310, 250, 4, 5, 0.20),
        "BME280": (445, 365, 250, 4, 5, 0.20),
        "USB4105-GF-A": (20, 14.5, 120, 4, 20, 0.20),
    },
}

TIERS = [
    {"min_qty": 50, "discount_pct": 0.02},
    {"min_qty": 100, "discount_pct": 0.05},
    {"min_qty": 500, "discount_pct": 0.08},
]

BOM = [
    {"mpn": "ESP32-WROOM-32E", "qty": 100, "required_specs": {}, "mandatory": True},
    {"mpn": "BME280", "qty": 100, "required_specs": {}, "mandatory": True},
    {"mpn": "USB4105-GF-A", "qty": 200, "required_specs": {}, "mandatory": True},
]

DEMO_PASSWORD = "demo1234"
USERS = [
    ("buyer@acme.test", "buyer", BUYER_ID),
    ("sales@volt.test", "seller", "co_sup_a"),
    ("sales@circuitbazaar.test", "seller", "co_sup_b"),
    ("sales@siliconmart.test", "seller", "co_sup_c"),
]


def catalog_items() -> list[dict]:
    out = []
    for company_id, items in SUPPLY.items():
        for mpn, (_lp, _fp, stock, lead, moq, _s) in items.items():
            out.append({
                "company_id": company_id, "mpn": mpn, "description": MPNS[mpn],
                "specs": {}, "stock_qty": stock, "lead_time_days": lead,
                "moq": moq, "tax_rate": 0.18,
            })
    return out


def pricing_rules() -> list[dict]:
    now = datetime.now(timezone.utc)
    out = []
    for company_id, items in SUPPLY.items():
        for mpn, (lp, fp, _stock, _lead, _moq, step) in items.items():
            out.append({
                "company_id": company_id, "mpn": mpn,
                "list_price": float(lp), "floor_price": float(fp),
                "tiers": TIERS, "concession_step_pct": step, "max_rounds": 3,
                "valid_from": now, "valid_to": now + timedelta(days=90),
            })
    return out


def sample_rfq() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "_id": "rfq_demo_1",
        "buyer_company_id": BUYER_ID,
        "title": "Sensor node batch - 100 units",
        "budget": 90000.0,
        "currency": "INR",
        "deadline": now + timedelta(days=14),
        "status": "draft",
        "round": 0,
        "lines": BOM,
        "participants": [
            {"company_id": BUYER_ID, "side": "buyer", "controller": "agent", "status": "active"},
            *[
                {"company_id": cid, "side": "seller", "controller": "agent", "status": "invited"}
                for cid in SUPPLY
            ],
        ],
        "created_at": now,
    }
