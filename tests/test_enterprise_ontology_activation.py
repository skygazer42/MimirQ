import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import JSON, MetaData, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models.registry  # noqa: F401
from app.api.v1.knowledge_graph import enterprise_ontology as ontology_routes
from app.api.v1.knowledge_graph.enterprise_ontology import router
from app.infrastructure.config import settings
from app.infrastructure.database.connection import get_db
from app.infrastructure.exceptions import register_exception_handlers
from app.models.datasets.records import Dataset
from app.models.documents.records import Document, DocumentChunk
from app.models.identity.workspaces import Tenant, TenantMember
from app.models.knowledge_graph.enterprise_ontology import (
    EnterpriseOntology,
    EnterpriseOntologyDataset,
    EnterpriseOntologyDocument,
    EnterpriseOntologyVersion,
)
from app.rag.kg.enterprise_ontology.activation import active_version_id
from app.rag.kg.enterprise_ontology.definition import OntologyDefinition, load_ontology_definition
from app.rag.kg.enterprise_ontology.documents import save_document_evidence
from app.rag.kg.enterprise_ontology.metadata import GroundedValue
from app.rag.kg.enterprise_ontology.preview import ChunkPreview, PreviewEntity, PreviewRelation
from app.rag.kg.enterprise_ontology.versions import create_ontology, publish_version, update_draft
from app.rag.kg.extraction.evidence import EvidenceSpan
from tests.test_enterprise_ontology_preview import MODEL


@pytest.fixture
def activation(monkeypatch) -> Iterator[tuple[Session, TestClient, Dataset, EnterpriseOntology]]:
    monkeypatch.setattr(settings, "AUTH_MODE", "header")
    monkeypatch.setattr(settings, "LOCAL_DEV_TENANT_BOOTSTRAP_ENABLED", False)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    metadata = MetaData()
    for model in (Dataset, Document, DocumentChunk):
        model.__table__.to_metadata(metadata).c["metadata"].type = JSON()
    for model in (
        Tenant,
        TenantMember,
        EnterpriseOntology,
        EnterpriseOntologyVersion,
        EnterpriseOntologyDataset,
        EnterpriseOntologyDocument,
    ):
        model.__table__.to_metadata(metadata)
    metadata.create_all(engine)

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/kg/ontologies")
    register_exception_handlers(app)

    def get_test_db() -> Iterator[Session]:
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    with Session(engine, expire_on_commit=False) as db:
        tenant_id = uuid4()
        dataset = Dataset(tenant_id=tenant_id, owner_id="dataset-owner", name="evidence")
        db.add_all(
            [
                dataset,
                Tenant(id=tenant_id, name="maintenance"),
                TenantMember(tenant_id=tenant_id, user_id="reviewer", role="admin"),
            ]
        )
        db.commit()
        workspace = create_ontology(
            db, tenant_id, load_ontology_definition(MODEL, format="yaml"), account_id="reviewer"
        )
        with TestClient(app, headers={"X-Tenant-ID": str(tenant_id), "X-User-ID": "reviewer"}) as client:
            yield db, client, dataset, workspace


def _activate(client: TestClient, dataset: Dataset, version: EnterpriseOntologyVersion) -> Response:
    return client.put(f"/api/v1/kg/ontologies/{version.ontology_id}/versions/{version.id}/datasets/{dataset.id}")


def _document(db: Session, dataset: Dataset) -> Document:
    document = Document(
        tenant_id=dataset.tenant_id,
        dataset_id=dataset.id,
        filename="SLA.pdf",
        file_type="pdf",
        file_path="sla.pdf",
        file_size=123,
        doc_metadata={"active_pipeline_hash": "approved", "pipeline_hash": "historical"},
    )
    db.add(document)
    db.flush()
    return document


def _chunk(db: Session, document: Document, index: int, pipeline: str) -> DocumentChunk:
    chunk = DocumentChunk(
        id=uuid4(),
        tenant_id=document.tenant_id,
        document_id=document.id,
        chunk_index=index,
        content="SLA-2026-11",
        doc_metadata={"pipeline_hash": pipeline},
    )
    db.add(chunk)
    return chunk


@pytest.mark.parametrize("hops", [2, 3, 4])
def test_dataset_ask_follows_relation_path_by_business_key_and_readable_evidence(activation, monkeypatch, hops):
    db, client, dataset, workspace = activation
    definition = OntologyDefinition.model_validate(
        {
            "schema_version": 1,
            "ontology": "maintenance",
            "object_types": {
                "work_order": {"label": "工单", "key": ["id"], "properties": {"id": "string"}},
                "equipment": {"label": "设备", "key": ["id"], "properties": {"id": "string"}},
                "production_line": {"label": "产线", "key": ["id"], "properties": {"id": "string"}},
                "factory": {"label": "工厂", "key": ["id"], "properties": {"id": "string"}},
                "region": {"label": "园区", "key": ["id"], "properties": {"id": "string"}},
            },
            "relations": {
                "order_for_equipment": {"from": "work_order", "to": "equipment", "cardinality": "many_to_one"},
                "equipment_on_line": {"from": "equipment", "to": "production_line", "cardinality": "many_to_one"},
                "line_in_factory": {"from": "production_line", "to": "factory", "cardinality": "many_to_one"},
                "factory_in_region": {"from": "factory", "to": "region", "cardinality": "many_to_one"},
            },
        }
    )
    version = publish_version(db, workspace, expected_revision=1, account_id="reviewer", frozen_definition=definition)
    path = ["order_for_equipment", "equipment_on_line", "line_in_factory", "factory_in_region"][:hops]
    live = os.environ.get("MIMIRQ_ONTOLOGY_GRAPH_LIVE") == "1"

    if not live:

        class Client:
            async def chat_with_schema(self, *_args, **_kwargs):
                return {"object_type": "work_order", "business_key": "WO-01", "relation_path": path}

            async def aclose(self):
                pass

        async def create_client():
            return Client()

        monkeypatch.setattr(ontology_routes, "create_llm_client", create_client)

    def prepare(filename, content, predicate, ends):
        document = _document(db, dataset)
        document.filename = filename
        document.owner_id = "other-owner"
        document.status = "completed"
        document.doc_metadata = {**document.doc_metadata, "effective_at": "2025-01-01"}
        chunk = _chunk(db, document, 0, "approved")
        chunk.content = content
        chunk.page_number = 1
        db.commit()
        if live:
            response = client.post(
                f"/api/v1/kg/ontologies/{workspace.id}/versions/{version.id}/documents",
                json={"document_id": str(document.id)},
            )
            assert response.is_success, response.text
            return document

        def span(quote):
            start = content.index(quote)
            return EvidenceSpan(quote=quote, start_char=start, end_char=start + len(quote), source="quote")

        entities = [
            PreviewEntity(
                id=str(index),
                name=name,
                object_type=kind,
                evidence=span(quote),
                key_fields=["id"],
                attributes={"id": [GroundedValue(value=key, value_type="string", evidence=span(key))]},
            )
            for index, (kind, name, key, quote) in enumerate(ends)
        ]
        save_document_evidence(
            db,
            tenant_id=dataset.tenant_id,
            document=document,
            version_id=version.id,
            pipeline_hash="approved",
            previews=[
                ChunkPreview(
                    document_id=document.id,
                    chunk_id=chunk.id,
                    page=1,
                    entities=entities,
                    relations=[
                        PreviewRelation(subject_id="0", predicate=predicate, object_id="1", evidence=span(content))
                    ],
                )
            ],
        )
        return document

    first = prepare(
        "维修工单.pdf",
        "工单 WO-01 关联设备泵 E-102。",
        path[0],
        [("work_order", "WO-01", "WO-01", "工单 WO-01"), ("equipment", "泵", "E-102", "设备泵 E-102")],
    )
    second = prepare(
        "产线台账.pdf",
        "设备泵 E-102 安装在产线 LINE-A。",
        path[1],
        [("equipment", "泵", "E-102", "设备泵 E-102"), ("production_line", "LINE-A", "LINE-A", "产线 LINE-A")],
    )
    decoy = prepare(
        "同名设备.pdf",
        "设备泵 E-103 安装在产线 LINE-B。",
        path[1],
        [("equipment", "泵", "E-103", "设备泵 E-103"), ("production_line", "LINE-B", "LINE-B", "产线 LINE-B")],
    )
    expected = [first, second]
    if hops >= 3:
        expected.append(
            prepare(
                "工厂台账.pdf",
                "产线 LINE-A 归属于工厂 FACTORY-A。",
                path[2],
                [
                    ("production_line", "LINE-A", "LINE-A", "产线 LINE-A"),
                    ("factory", "FACTORY-A", "FACTORY-A", "工厂 FACTORY-A"),
                ],
            )
        )
    if hops == 4:
        expected.append(
            prepare(
                "园区台账.pdf",
                "工厂 FACTORY-A 位于园区 REGION-A。",
                path[3],
                [
                    ("factory", "FACTORY-A", "FACTORY-A", "工厂 FACTORY-A"),
                    ("region", "REGION-A", "REGION-A", "园区 REGION-A"),
                ],
            )
        )
    assert _activate(client, dataset, version).is_success
    ask_url = f"/api/v1/kg/ontologies/datasets/{dataset.id}/ask"
    question = {
        "question": ("从工单 WO-01 沿 " + " → ".join(path) + " 追溯至最终对象，逐步引用原文。"),
        "observed_at": "2026-11-23T12:00:00Z",
    }

    def ask(**scope):
        response = client.post(ask_url, json={**question, **scope})
        assert response.is_success, response.text
        return response.json()

    result = ask()
    assert result["plan"]["relation_path"] == path
    assert [quote["document_id"] for quote in result["citations"]] == [str(document.id) for document in expected]
    assert "LINE-A" in result["answer"] and "LINE-B" not in result["answer"]
    partial = ask(document_ids=[str(first.id), str(decoy.id)])
    assert partial["citations"] == [] and "原文依据" in partial["answer"]
    second.doc_metadata = {**second.doc_metadata, "expires_at": "2026-11-01"}
    db.commit()
    assert ask()["citations"] == []
    second.doc_metadata = {key: value for key, value in second.doc_metadata.items() if key != "expires_at"}
    second.access_mode = "only_me"
    db.commit()
    restricted = ask()
    assert restricted["citations"] == [] and second.filename not in restricted["answer"]
    if not live:
        path.reverse()
        invalid = ask()
        assert invalid["citations"] == [] and "方向" in invalid["answer"]


def _prepare(
    db: Session,
    document: Document,
    version: EnterpriseOntologyVersion,
    pipeline: str,
    chunks: list[DocumentChunk],
) -> None:
    save_document_evidence(
        db,
        tenant_id=document.tenant_id,
        document=document,
        version_id=version.id,
        pipeline_hash=pipeline,
        previews=[ChunkPreview(document_id=document.id, chunk_id=chunk.id, page=None) for chunk in chunks],
    )


def test_dataset_activation_requires_enabled_current_chunks_and_preserves_active_version(activation):
    db, client, dataset, workspace = activation
    active = publish_version(db, workspace, expected_revision=1, account_id="reviewer")
    assert _activate(client, dataset, active).json()["version_id"] == str(active.id)
    assert active_version_id(db, uuid4(), dataset.id) is None

    update_draft(db, workspace, load_ontology_definition(MODEL, format="yaml"), expected_revision=1)
    target = publish_version(db, workspace, expected_revision=2, account_id="reviewer")
    document = _document(db, dataset)
    prepared = _chunk(db, document, 0, "approved")
    missing = [_chunk(db, document, index, "approved") for index in (1, 2)]
    disabled = _chunk(db, document, 3, "approved")
    disabled.disabled_at = datetime.now(UTC)
    historical = _chunk(db, document, 4, "historical")
    _prepare(db, document, target, "historical", [historical])
    _prepare(db, document, target, "approved", [prepared])

    response = _activate(client, dataset, target)
    assert response.status_code == 409, response.text
    message = response.json()["message"]
    assert document.filename in message
    assert str(document.id) in message
    assert all(str(chunk.id) in message for chunk in missing)
    assert all(str(chunk.id) not in message for chunk in (prepared, disabled, historical))
    assert active_version_id(db, dataset.tenant_id, dataset.id) == active.id

    _prepare(db, document, target, "approved", [prepared, *missing])
    assert _activate(client, dataset, target).json()["version_id"] == str(target.id)


def test_dataset_activation_reports_document_with_no_usable_chunks(activation):
    db, client, dataset, workspace = activation
    version = publish_version(db, workspace, expected_revision=1, account_id="reviewer")
    document = _document(db, dataset)
    disabled = _chunk(db, document, 0, "approved")
    disabled.disabled_at = datetime.now(UTC)
    _prepare(db, document, version, "approved", [disabled])

    response = _activate(client, dataset, version)
    assert response.status_code == 409, response.text
    message = response.json()["message"]
    assert document.filename in message
    assert "no enabled chunks" in message
    assert active_version_id(db, dataset.tenant_id, dataset.id) is None


def test_dataset_activation_trims_document_and_chunk_details_by_acl(activation):
    db, client, dataset, workspace = activation
    version = publish_version(db, workspace, expected_revision=1, account_id="reviewer")
    document = _document(db, dataset)
    chunk = _chunk(db, document, 0, "approved")
    document.access_mode = "only_me"
    document.owner_id = "other-user"
    db.commit()

    response = _activate(client, dataset, version)
    assert response.status_code == 409, response.text
    assert document.filename not in response.text
    assert str(document.id) not in response.text
    assert str(chunk.id) not in response.text
    assert "evidence" in response.json()["message"]
    assert active_version_id(db, dataset.tenant_id, dataset.id) is None


def test_dataset_activation_ignores_unpublished_archived_and_other_dataset_documents(activation):
    db, client, dataset, workspace = activation
    version = publish_version(db, workspace, expected_revision=1, account_id="reviewer")
    draft = _document(db, dataset)
    draft.publication_status = "draft"
    archived = _document(db, dataset)
    archived.archived_at = datetime.now(UTC)
    other_dataset = Dataset(tenant_id=dataset.tenant_id, owner_id="reviewer", name="other")
    db.add(other_dataset)
    db.flush()
    _document(db, other_dataset)
    db.commit()

    assert _activate(client, dataset, version).json()["version_id"] == str(version.id)
