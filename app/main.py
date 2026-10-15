from fastapi import FastAPI, HTTPException

from app.db import get_db

app = FastAPI(title="The Negotiator")


def _clean(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = doc.pop("_id")
    doc.pop("password_hash", None)
    return doc


@app.get("/health")
def health() -> dict:
    get_db().command("ping")
    return {"ok": True}


@app.get("/companies")
def list_companies(kind: str | None = None) -> list[dict]:
    query = {"kind": kind} if kind else {}
    return [_clean(d) for d in get_db().companies.find(query)]


@app.get("/companies/{company_id}/catalog")
def company_catalog(company_id: str) -> list[dict]:
    items = list(get_db().catalog_items.find({"company_id": company_id}, {"_id": 0}))
    if not items:
        raise HTTPException(404, "No catalog for company")
    return items


@app.get("/rfqs/{rfq_id}")
def get_rfq(rfq_id: str) -> dict:
    rfq = get_db().rfqs.find_one({"_id": rfq_id})
    if not rfq:
        raise HTTPException(404, "RFQ not found")
    return _clean(rfq)
