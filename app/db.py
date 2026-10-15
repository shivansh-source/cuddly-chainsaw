"""MongoDB connection, schema validation and indexes.

Validators live in the database so bad data is rejected even if application
code is bypassed (seed scripts, voice webhook, future services).
"""
from pymongo import ASCENDING, MongoClient
from pymongo.database import Database

from app.config import settings

_client: MongoClient | None = None


def get_db() -> Database:
    global _client
    if _client is None:
        _client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=8000)
    return _client[settings.mongodb_db]


def _num(minimum: float | None = None) -> dict:
    spec: dict = {"bsonType": ["double", "int", "long", "decimal"]}
    if minimum is not None:
        spec["minimum"] = minimum
    return spec


VALIDATORS: dict[str, dict] = {
    "users": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["email", "role", "company_id", "password_hash"],
            "properties": {
                "email": {"bsonType": "string"},
                "role": {"enum": ["buyer", "seller"]},
                "company_id": {"bsonType": "string"},
                "password_hash": {"bsonType": "string"},
            },
        }
    },
    "companies": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["name", "kind"],
            "properties": {
                "name": {"bsonType": "string"},
                "kind": {"enum": ["buyer", "supplier"]},
                "verified": {"bsonType": "bool"},
                "reliability_score": _num(0) | {"maximum": 100},
            },
        }
    },
    "catalog_items": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["company_id", "mpn", "stock_qty", "lead_time_days", "moq", "tax_rate"],
            "properties": {
                "company_id": {"bsonType": "string"},
                "mpn": {"bsonType": "string"},
                "stock_qty": _num(0),
                "lead_time_days": _num(0),
                "moq": _num(1),
                "tax_rate": _num(0) | {"maximum": 1},
            },
        }
    },
    "pricing_rules": {
        "$and": [
            {
                "$jsonSchema": {
                    "bsonType": "object",
                    "required": [
                        "company_id", "mpn", "list_price", "floor_price",
                        "tiers", "concession_step_pct", "max_rounds",
                    ],
                    "properties": {
                        "company_id": {"bsonType": "string"},
                        "mpn": {"bsonType": "string"},
                        "list_price": _num(0),
                        "floor_price": _num(0),
                        "concession_step_pct": _num(0) | {"maximum": 1},
                        "max_rounds": {"bsonType": ["int", "long"], "minimum": 1},
                        "tiers": {
                            "bsonType": "array",
                            "items": {
                                "bsonType": "object",
                                "required": ["min_qty", "discount_pct"],
                                "properties": {
                                    "min_qty": _num(1),
                                    "discount_pct": _num(0) | {"maximum": 1},
                                },
                            },
                        },
                    },
                }
            },
            # A seller's floor can never exceed its list price.
            {"$expr": {"$lte": ["$floor_price", "$list_price"]}},
        ]
    },
    "rfqs": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["buyer_company_id", "title", "budget", "currency", "status", "round", "lines"],
            "properties": {
                "budget": _num(0),
                "currency": {"bsonType": "string"},
                "status": {"enum": ["draft", "open", "negotiating", "completed", "cancelled"]},
                "round": {"bsonType": ["int", "long"], "minimum": 0},
                "lines": {"bsonType": "array", "minItems": 1},
            },
        }
    },
    "offers": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": [
                "rfq_id", "company_id", "round", "version", "unit_price",
                "qty", "source", "status",
            ],
            "properties": {
                "unit_price": _num(0),
                "qty": _num(1),
                "round": {"bsonType": ["int", "long"], "minimum": 0},
                "version": {"bsonType": ["int", "long"], "minimum": 1},
                "source": {
                    "enum": [
                        "engine", "llm_agent", "human_seller", "human_buyer",
                        "voice_confirmed", "seeded",
                    ]
                },
                "status": {"enum": ["proposed", "countered", "accepted", "rejected", "confirmed", "flagged"]},
            },
        }
    },
}

INDEXES: dict[str, list[tuple[list[tuple[str, int]], dict]]] = {
    "users": [([("email", ASCENDING)], {"unique": True})],
    "catalog_items": [
        ([("company_id", ASCENDING), ("mpn", ASCENDING)], {"unique": True}),
        ([("mpn", ASCENDING)], {}),
    ],
    "pricing_rules": [([("company_id", ASCENDING), ("mpn", ASCENDING)], {"unique": True})],
    "rfqs": [([("buyer_company_id", ASCENDING), ("status", ASCENDING)], {})],
    "turns": [([("rfq_id", ASCENDING), ("created_at", ASCENDING)], {})],
    "offers": [([("rfq_id", ASCENDING), ("round", ASCENDING)], {})],
    "recommendations": [([("rfq_id", ASCENDING), ("created_at", ASCENDING)], {})],
}

ALL_COLLECTIONS = [
    "users", "companies", "catalog_items", "pricing_rules",
    "rfqs", "turns", "offers", "recommendations",
]


def ensure_schema(db: Database) -> None:
    """Create collections with validators and indexes. Safe to re-run."""
    existing = set(db.list_collection_names())
    for name in ALL_COLLECTIONS:
        validator = VALIDATORS.get(name)
        if name not in existing:
            if validator:
                db.create_collection(name, validator=validator, validationLevel="strict")
            else:
                db.create_collection(name)
        elif validator:
            db.command("collMod", name, validator=validator, validationLevel="strict")
        for keys, opts in INDEXES.get(name, []):
            db[name].create_index(keys, **opts)
