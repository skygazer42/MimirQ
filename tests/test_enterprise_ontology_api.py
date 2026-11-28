from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models.registry  # noqa: F401
from app.api.v1 import get_router
from app.api.v1.knowledge_graph import enterprise_ontology
from app.infrastructure.config import settings
from app.infrastructure.database.connection import get_db
from app.models.identity.workspaces import TenantMember
from tests.test_enterprise_ontology_definition import MAINTENANCE_YAML
from tests.test_enterprise_ontology_preview import MODEL, SOURCE, ScriptedClient


def test_enterprise_ontology_preview_uses_mounted_route_and_current_membership(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "header")
    monkeypatch.setattr(settings, "LOCAL_DEV_TENANT_BOOTSTRAP_ENABLED", False)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TenantMember.__table__.create(engine)
    tenant_id = uuid4()
    with Session(engine) as db:
        db.add(TenantMember(tenant_id=tenant_id, user_id="reviewer", role="owner"))
        db.commit()

    async def make_llm():
        class Client(ScriptedClient):
            async def aclose(self):
                pass

        return Client()

    monkeypatch.setattr(enterprise_ontology, "create_llm_client", make_llm)
    app = FastAPI()
    app.include_router(get_router(), prefix="/api/v1")

    def get_test_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    client = TestClient(app)
    headers = {"X-Tenant-ID": str(tenant_id), "X-User-ID": "reviewer"}
    base = "/api/v1/kg/ontologies"
    imported = client.post(base + "/validate", json={"content": MODEL, "format": "yaml"}, headers=headers)
    assert imported.status_code == 200, imported.text
    assert imported.json()["relations"]["order_for_equipment"]["from"] == "work_order"
    payload = {"definition": imported.json(), "source": {"kind": "sample", "text": SOURCE}}
    denied = client.post(base + "/preview", json=payload, headers={**headers, "X-User-ID": "outsider"})
    assert denied.status_code == 403
    result = client.post(base + "/preview", json=payload, headers=headers)
    assert result.status_code == 200, result.text
    assert [one["predicate"] for one in result.json()[0]["relations"]] == ["order_for_equipment"]

    quote = "维修工单状态为 OPEN 时属于未关闭工单。"

    class RuleClient:
        async def chat_with_schema(self, *_args, **_kwargs):
            rule = {
                "object_type": "work_order",
                "conditions": [{"property": "status", "operator": "eq", "value": "OPEN"}],
            }
            return {
                "rules": [
                    {"id": "open_order", "rule": rule, "quote": quote},
                    {"id": "ungrounded", "rule": rule, "quote": "This sentence is absent."},
                    {
                        "id": "unknown_field",
                        "rule": {
                            **rule,
                            "conditions": [{"property": "missing", "operator": "eq", "value": "OPEN"}],
                        },
                        "quote": quote,
                    },
                ]
            }

        async def aclose(self):
            pass

    async def rule_llm():
        return RuleClient()

    monkeypatch.setattr(enterprise_ontology, "create_llm_client", rule_llm)
    definition = client.post(base + "/validate", json={"content": MAINTENANCE_YAML, "format": "yaml"}, headers=headers)
    rules_payload = {"definition": definition.json(), "source": {"kind": "sample", "text": quote}}
    assert (
        client.post(
            base + "/preview/rules", json=rules_payload, headers={**headers, "X-User-ID": "outsider"}
        ).status_code
        == 403
    )
    rules = client.post(base + "/preview/rules", json=rules_payload, headers=headers)
    assert rules.status_code == 200, rules.text
    assert [item["id"] for item in rules.json()] == ["open_order"]
    evidence = rules.json()[0]["evidence"]
    assert quote[evidence["start_char"] : evidence["end_char"]] == evidence["quote"] == quote
