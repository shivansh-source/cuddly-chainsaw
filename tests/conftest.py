"""Tests run against a throwaway database, never the demo one."""
import os
from types import SimpleNamespace

import pytest

from app.config import settings

# Tests never touch the demo database or Atlas by default: they use a local
# MongoDB. Set TEST_MONGODB_URI to run them somewhere else (e.g. Atlas).
settings.mongodb_uri = os.environ.get("TEST_MONGODB_URI", "mongodb://localhost:27017")
settings.mongodb_db = "negotiator_test"
settings.groq_api_key = ""  # force the deterministic path unless a test injects an LLM
settings.jwt_secret = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import get_db  # noqa: E402

PASSWORD = "demo1234"


@pytest.fixture()
def seeded(capsys):
    from scripts.seed import main
    main()
    capsys.readouterr()
    return get_db()


def login(email: str) -> TestClient:
    from app.main import app
    client = TestClient(app)
    r = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return client


@pytest.fixture()
def api(seeded):
    """Authenticated clients: buyer (Acme), sellers a (Volt), b, c, plus another buyer."""
    from app.main import app
    app.dependency_overrides.clear()
    ns = SimpleNamespace(
        buyer=login("buyer@acme.test"), other_buyer=login("buyer@nimbus.test"),
        a=login("sales@volt.test"), b=login("sales@circuitbazaar.test"),
        c=login("sales@siliconmart.test"), d=login("sales@hexa.test"),
        anon=TestClient(app))
    yield ns
    app.dependency_overrides.clear()


def pytest_sessionfinish(session, exitstatus):
    try:
        get_db().client.drop_database("negotiator_test")
    except Exception:
        pass
