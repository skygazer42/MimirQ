from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.rag.preprocessing.rule_packs import GOVERNANCE_RULE_PACKS, list_governance_rule_packs
from app.rag.preprocessing.rules import build_governance_rules


def test_list_governance_rule_packs_includes_new_packs():  # noqa: ANN001
    packs = list_governance_rule_packs()
    assert "pdf_header_footer_cn" in packs
    assert "chat_export_noise" in packs
    assert "email_disclaimer" in packs
    assert "markdown_export_noise" in packs
    assert "confluence_jira_noise" in packs
    assert "notion_export_noise" in packs
    assert "feishu_lark_noise" in packs
    assert "wechat_mp_noise" in packs
    assert "cn_finance_report_artifacts" in packs
    assert "cn_gov_redhead_artifacts" in packs
    assert "cn_medical_record_artifacts" in packs


def test_build_governance_rules_expands_rule_packs():  # noqa: ANN001
    for key in [
        "pdf_header_footer_cn",
        "chat_export_noise",
        "email_disclaimer",
        "markdown_export_noise",
        "confluence_jira_noise",
        "notion_export_noise",
        "feishu_lark_noise",
        "wechat_mp_noise",
        "cn_finance_report_artifacts",
        "cn_gov_redhead_artifacts",
        "cn_medical_record_artifacts",
    ]:
        rules = build_governance_rules(rule_packs=[key])
        patterns = {r.pattern for r in rules}
        for rr in GOVERNANCE_RULE_PACKS[key]:
            assert rr.pattern in patterns


def test_governance_rule_packs_api_lists_items(monkeypatch):  # noqa: ANN001
    import app.api.v1.governance as governance_module
    from app.api.dependencies.auth import get_current_account_id
    from app.api.dependencies.tenant import get_tenant_id
    from app.core.database import get_db
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()

    class _DummyDB:
        pass

    def _override_get_db():  # noqa: ANN202
        yield _DummyDB()

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(governance_module.router, prefix="/api/v1/governance")
    client = TestClient(app)

    res = client.get("/api/v1/governance/rule-packs")
    assert res.status_code == 200, res.text
    body = res.json()
    assert isinstance(body.get("items"), list)
    assert "pdf_header_footer_cn" in body["items"]
    assert "chat_export_noise" in body["items"]
    assert "email_disclaimer" in body["items"]
    assert "markdown_export_noise" in body["items"]
    assert "confluence_jira_noise" in body["items"]
    assert "notion_export_noise" in body["items"]
    assert "feishu_lark_noise" in body["items"]
    assert "wechat_mp_noise" in body["items"]
    assert "cn_finance_report_artifacts" in body["items"]
    assert "cn_gov_redhead_artifacts" in body["items"]
    assert "cn_medical_record_artifacts" in body["items"]
