"""Create collections (with validators/indexes) and load demo data. Idempotent."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import seed_data as sd  # noqa: E402
from app.db import ALL_COLLECTIONS, ensure_schema, get_db  # noqa: E402
from app.security import hash_password  # noqa: E402


def main() -> None:
    db = get_db()
    ensure_schema(db)
    for name in ALL_COLLECTIONS:
        db[name].delete_many({})

    db.companies.insert_many(sd.COMPANIES)
    db.users.insert_many(
        [{"email": e, "role": r, "company_id": c, "password_hash": hash_password(sd.DEMO_PASSWORD)}
         for e, r, c in sd.USERS]
    )
    db.catalog_items.insert_many(sd.catalog_items())
    db.pricing_rules.insert_many(sd.pricing_rules())
    db.rfqs.insert_one(sd.sample_rfq())

    for name in ALL_COLLECTIONS:
        print(f"{name:16s} {db[name].count_documents({})}")


if __name__ == "__main__":
    main()
