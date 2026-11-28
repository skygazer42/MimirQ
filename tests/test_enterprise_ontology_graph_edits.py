import os
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import JSON, MetaData, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models.registry  # noqa: F401
from app.api.v1 import get_router
from app.api.v1.knowledge_graph import enterprise_ontology
from app.infrastructure.config import settings
from app.infrastructure.database.connection import get_db
from app.models.audit_log import AuditLog
from app.models.datasets.records import Dataset
from app.models.documents.records import Document, DocumentChunk
from app.models.identity.workspaces import Tenant, TenantMember
from app.models.knowledge_graph.enterprise_ontology import (
    EnterpriseOntology,
    EnterpriseOntologyDataset,
    EnterpriseOntologyDocument,
    EnterpriseOntologyVersion,
)
from app.models.knowledge_graph.entities import KgSourceEvent
from tests.test_enterprise_ontology_preview import MODEL, SOURCE, ScriptedClient


def test_graph_correction_survives_reextraction_and_changes_answers(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "header")
    monkeypatch.setattr(settings, "LOCAL_DEV_TENANT_BOOTSTRAP_ENABLED", False)
    monkeypatch.setattr(settings, "KG_ENABLED", True)
    if os.environ.get("MIMIRQ_ONTOLOGY_GRAPH_LIVE") != "1":

        class Client(ScriptedClient):
            async def chat_with_schema(self, messages, **kwargs):
                if "business_key" in kwargs["response_schema"]["properties"]:
                    return {"object_type": "work_order", "business_key": "WO-01"}
                return await super().chat_with_schema(messages, **kwargs)

            async def aclose(self):
                pass

        async def create_client():
            return Client()

        monkeypatch.setattr(enterprise_ontology, "create_llm_client", create_client)

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    metadata = MetaData()
    for model in (
        Tenant,
        TenantMember,
        Dataset,
        Document,
        DocumentChunk,
        AuditLog,
        EnterpriseOntology,
        EnterpriseOntologyVersion,
        EnterpriseOntologyDataset,
        EnterpriseOntologyDocument,
        KgSourceEvent,
    ):
        table = model.__table__.to_metadata(metadata)
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    metadata.create_all(engine)
    tenant_id, dataset_id, document_id, chunk_id = (uuid4() for _ in range(4))
    with Session(engine) as db:
        db.add_all(
            [
                Tenant(id=tenant_id, name="graph-test"),
                TenantMember(tenant_id=tenant_id, user_id="owner", role="owner"),
                TenantMember(tenant_id=tenant_id, user_id="reader", role="readonly"),
                Dataset(id=dataset_id, tenant_id=tenant_id, name="维修", owner_id="owner"),
                Document(
                    id=document_id,
                    tenant_id=tenant_id,
                    dataset_id=dataset_id,
                    filename="SLA.pdf",
                    owner_id="owner",
                    file_type="pdf",
                    file_path="test.pdf",
                    file_size=100,
                    status="completed",
                    publication_status="published",
                    doc_metadata={"active_pipeline_hash": "test-pipeline", "effective_at": "2025-01-01"},
                ),
                DocumentChunk(
                    id=chunk_id,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    chunk_index=0,
                    page_number=3,
                    content=SOURCE,
                    doc_metadata={"pipeline_hash": "test-pipeline"},
                ),
            ]
        )
        db.commit()

    def get_test_db():
        with Session(engine) as db:
            yield db

    app = FastAPI()
    app.include_router(get_router(), prefix="/api/v1")
    app.dependency_overrides[get_db] = get_test_db
    api = "/api/v1/kg/ontologies"
    graph = f"/datasets/{dataset_id}/documents/{document_id}/graph"

    def span(quote):
        start = SOURCE.index(quote)
        return {"quote": quote, "start_char": start, "end_char": start + len(quote), "source": "quote"}

    with TestClient(app) as client:

        def request(method, path, body=None, *, user="owner", status=200, base=api):
            response = client.request(
                method,
                base + path,
                json=body,
                headers={"X-Tenant-ID": str(tenant_id), "X-User-ID": user},
            )
            assert response.status_code == status, (path, response.text)
            return response.json()

        definition = request("POST", "/validate", {"content": MODEL, "format": "yaml"})
        workspace = request("POST", "", definition, status=201)
        version = request("POST", f"/{workspace['id']}/versions", {"expected_revision": 1}, status=201)
        prefix = f"/{workspace['id']}/versions/{version['id']}"
        prepare = {"document_id": str(document_id)}
        request("POST", prefix + "/documents", prepare)
        request("PUT", prefix + f"/datasets/{dataset_id}")
        scope = f"dataset_id={dataset_id}&document_ids={document_id}&prefer_ontology=true"
        canvas = request("GET", f"/graph?{scope}", base="/api/v1/kg")
        assert canvas["stats"]["ontology_version_id"] == version["id"]
        assert {node["label"] for node in canvas["nodes"]} >= {"WO-01", "E-102"}
        assert all(node["meta"]["chunk_id"] == str(chunk_id) for node in canvas["nodes"])
        [edge] = [link for link in canvas["links"] if link["meta"]["predicate"] == "order_for_equipment"]
        assert edge["meta"]["evidence"]["quote"] in SOURCE
        capped = request("GET", f"/graph?{scope}&max_entities=1", base="/api/v1/kg")
        assert len(capped["nodes"]) == 1 and capped["links"] == []
        historical = request("GET", f"/graph?{scope}&pipeline_hash=test-pipeline", base="/api/v1/kg")
        assert "ontology_version_id" not in historical["stats"]
        original = request("GET", graph)
        assert original["can_edit"] and not original["corrected"]
        assert not request("GET", graph, user="reader")["can_edit"]
        edit = {
            "version_id": version["id"],
            "expected_revision": original["revision"],
            "graph": {
                "entities": [
                    {"id": "order", "name": "WO-01", "object_type": "work_order", "evidence": span("工单 WO-01")},
                    {
                        "id": "equipment",
                        "name": "设备",
                        "object_type": "equipment",
                        "evidence": span("设备 E-102"),
                        "attributes": {
                            "id": [{"value": "E-102", "value_type": "string", "evidence": span("设备 E-102")}],
                        },
                    },
                ],
                "relations": [
                    {
                        "subject_id": "order",
                        "predicate": "order_for_equipment",
                        "object_id": "equipment",
                        "evidence": span("工单 WO-01 归属设备 E-102。"),
                    }
                ],
            },
        }
        write = graph + f"/{chunk_id}"
        request("PUT", write, edit, user="reader", status=403)
        request("PUT", write, {**edit, "version_id": str(uuid4())}, status=409)
        invalid = {**edit["graph"], "relations": [{**edit["graph"]["relations"][0], "subject_id": "equipment"}]}
        request("PUT", write, {**edit, "graph": invalid}, status=422)
        changed = request("PUT", write, edit)
        assert changed["corrected"] and changed["chunk"]["entities"][1]["business_key"] == {"id": "E-102"}
        updated_canvas = request("GET", f"/graph?{scope}", base="/api/v1/kg")
        [equipment_node] = [item for item in updated_canvas["nodes"] if item["meta"]["ontology_entity_id"] == "equipment"]
        assert equipment_node["label"] == "设备"
        request("PUT", write, edit, status=409)
        request("POST", prefix + "/documents", prepare)
        reloaded = request("GET", graph)
        assert reloaded["revision"] == changed["revision"]
        assert reloaded["chunk"]["relations"] == changed["chunk"]["relations"]

        question = {
            "question": "引用原文说明工单 WO-01 的 order_for_equipment 归属关系。",
            "observed_at": "2026-11-23T12:00:00Z",
        }
        ask = f"/datasets/{dataset_id}/ask"
        answer = request("POST", ask, question)
        assert len(answer["citations"]) == 1, answer
        [citation] = answer["citations"]
        assert citation["evidence"]["quote"] == edit["graph"]["relations"][0]["evidence"]["quote"]
        removed = request(
            "PUT",
            write,
            {
                **edit,
                "expected_revision": reloaded["revision"],
                "graph": {**edit["graph"], "relations": []},
            },
        )
        assert removed["chunk"]["relations"] == []
        assert request("GET", f"/graph?{scope}", base="/api/v1/kg")["links"] == []
        assert request("POST", ask, question)["citations"] == []
        exported = client.get(
            f"/api/v1/kg/graph/export?{scope}",
            headers={"X-Tenant-ID": str(tenant_id), "X-User-ID": "owner"},
        )
        assert exported.is_success and ">设备</data>" in exported.text and "<edge " not in exported.text
        restored = request(
            "PUT",
            write,
            {
                **edit,
                "expected_revision": removed["revision"],
                "graph": None,
            },
        )
        assert not restored["corrected"]
        with Session(engine) as db:
            audit = list(db.scalars(select(AuditLog).where(AuditLog.action == "kg.ontology.graph.correct")))
            assert len(audit) == 3 and all(row.actor_id == "owner" for row in audit)
    engine.dispose()
