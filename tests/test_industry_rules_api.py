from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app() -> FastAPI:
    from app.api.v1.industry_rules import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/industry-rules")
    return app


def test_industry_rules_router_is_included_in_api_v1() -> None:
    import langchain

    if not hasattr(langchain, "debug"):
        langchain.debug = False
    if not hasattr(langchain, "verbose"):
        langchain.verbose = False
    if not hasattr(langchain, "llm_cache"):
        langchain.llm_cache = None

    from app.api.v1 import get_router

    router = get_router()
    paths = {route.path for route in router.routes}
    assert "/industry-rules/rulesets" in paths
    assert "/industry-rules/rulesets/{name}" in paths
    assert "/industry-rules/rulesets/{name}/glossary" in paths
    assert "/industry-rules/rulesets/{name}/patterns" in paths
    assert "/industry-rules/rulesets/{name}/intents" in paths
    assert "/industry-rules/preview-rewrite" in paths


def test_list_rulesets_endpoint_exposes_available_rulesets() -> None:
    client = TestClient(_app())

    res = client.get("/api/v1/industry-rules/rulesets")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["schema"] == "mimirq.industry_rules_index.v1"
    assert body["count"] >= 1
    assert any(str(item.get("name") or "") == "industrial_control" for item in body["rulesets"])


def test_get_ruleset_endpoint_returns_normalized_ruleset_details() -> None:
    client = TestClient(_app())

    res = client.get("/api/v1/industry-rules/rulesets/industrial_control")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["schema"] == "mimirq.industry_rules_ruleset.v1"
    assert body["ruleset"]["name"] == "industrial_control"
    assert body["ruleset"]["glossary_count"] >= 1
    assert "485" in body["ruleset"]["glossary"]


def test_get_ruleset_endpoint_returns_404_for_unknown_ruleset() -> None:
    client = TestClient(_app())

    res = client.get("/api/v1/industry-rules/rulesets/does-not-exist")

    assert res.status_code == 404


def test_preview_rewrite_endpoint_expands_query_with_glossary_aliases() -> None:
    client = TestClient(_app())

    res = client.post(
        "/api/v1/industry-rules/preview-rewrite",
        json={"ruleset": "industrial_control", "query": "485 没数据"},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["schema"] == "mimirq.industry_rules_preview.v1"
    assert body["ruleset"] == "industrial_control"
    assert body["original_query"] == "485 没数据"
    assert body["expanded_query"] != body["original_query"]
    assert "RS-485" in body["expanded_query"]
