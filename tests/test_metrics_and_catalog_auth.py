import hashlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.v1 import connectors_catalog, industry_rules, pipeline, retrieval_profiles
from app.api.v1 import metrics as metrics_module
from app.core.config import settings
from app.rag.kg.api import routes as kg_routes


def test_metrics_requires_matching_bearer_token_when_configured(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(metrics_module.router)
    monkeypatch.setattr(settings, "METRICS_BEARER_TOKEN", "metrics-secret", raising=False)

    client = TestClient(app)

    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401

    response = client.get("/metrics", headers={"Authorization": "Bearer metrics-secret"})

    assert response.status_code == 200
    assert response.text


def test_metrics_accepts_sha256_bearer_digest(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(metrics_module.router)
    digest = hashlib.sha256(b"metrics-secret").hexdigest()
    monkeypatch.setattr(settings, "METRICS_BEARER_TOKEN", f"sha256:{digest}", raising=False)

    client = TestClient(app)

    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer metrics-secret"}).status_code == 200


def test_metrics_falls_back_to_application_auth_when_token_unset(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(metrics_module.router)
    monkeypatch.setattr(settings, "METRICS_BEARER_TOKEN", "", raising=False)
    async def _fake_current_account_id(**_kwargs) -> str:
        return "acct-1"

    monkeypatch.setattr(metrics_module, "get_current_account_id", _fake_current_account_id, raising=True)

    client = TestClient(app)
    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.text


def test_retrieval_profiles_require_authenticated_account() -> None:
    app = FastAPI()
    app.include_router(retrieval_profiles.router, prefix="/api/v1/retrieval")

    client = TestClient(app)
    assert client.get("/api/v1/retrieval/profiles").status_code == 401

    app.dependency_overrides[get_current_account_id] = lambda: "acct-1"
    response = client.get("/api/v1/retrieval/profiles")

    assert response.status_code == 200
    assert response.json()["version_hash"]


def test_connectors_catalog_requires_authenticated_account() -> None:
    app = FastAPI()
    app.include_router(connectors_catalog.router, prefix="/api/v1/connectors")

    client = TestClient(app)
    assert client.get("/api/v1/connectors").status_code == 401

    app.dependency_overrides[get_current_account_id] = lambda: "acct-1"
    response = client.get("/api/v1/connectors")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_industry_rules_read_and_preview_require_authenticated_account() -> None:
    app = FastAPI()
    app.include_router(industry_rules.router, prefix="/api/v1/industry-rules")
    client = TestClient(app)

    assert client.get("/api/v1/industry-rules/rulesets").status_code == 401
    assert client.get("/api/v1/industry-rules/rulesets/default").status_code == 401
    assert (
        client.post(
            "/api/v1/industry-rules/preview-rewrite",
            json={"ruleset": "default", "query": "test"},
        ).status_code
        == 401
    )


def test_pipeline_plugin_catalog_requires_authenticated_account() -> None:
    app = FastAPI()
    app.include_router(pipeline.router, prefix="/api/v1/pipeline")

    assert TestClient(app).get("/api/v1/pipeline/plugins").status_code == 401


def test_kg_snapshot_diff_requires_authenticated_account() -> None:
    app = FastAPI()
    app.include_router(kg_routes.router, prefix="/api/v1/kg")

    response = TestClient(app).post(
        "/api/v1/kg/snapshots/diff",
        json={"snapshot_a": {}, "snapshot_b": {}},
    )

    assert response.status_code == 401
