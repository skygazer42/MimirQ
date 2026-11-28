"""Run enterprise ontology acceptance against the mounted API and a configured model."""

import json
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models.registry  # noqa: F401
from app.api.v1 import get_router
from app.infrastructure.config import settings
from app.infrastructure.database.connection import get_db
from app.models.identity.workspaces import Tenant, TenantMember
from app.models.knowledge_graph.enterprise_ontology import EnterpriseOntology, EnterpriseOntologyVersion

MODEL = """
schema_version: 1
ontology: maintenance
object_types:
  equipment:
    label: 设备
    key: [id]
    properties: {id: string}
  work_order:
    label: 工单
    key: [id]
    properties: {id: string}
relations:
  order_for_equipment:
    label: 工单归属于设备
    from: work_order
    to: equipment
    cardinality: many_to_one
"""
SAMPLE = "维修工单 WO-01 归属于设备 E-102。"


def main() -> None:
    settings.AUTH_MODE = "header"
    settings.LOCAL_DEV_TENANT_BOOTSTRAP_ENABLED = False
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (Tenant, TenantMember, EnterpriseOntology, EnterpriseOntologyVersion):
        model.__table__.create(engine)
    tenant_id = uuid4()
    headers = {"X-Tenant-ID": str(tenant_id), "X-User-ID": "ontology-smoke"}
    try:
        with Session(engine) as db:
            db.add(Tenant(id=tenant_id, name="ontology-smoke"))
            db.add(TenantMember(tenant_id=tenant_id, user_id="ontology-smoke", role="owner"))
            db.commit()

        def test_database():
            with Session(engine) as db:
                yield db

        app = FastAPI()
        app.include_router(get_router(), prefix="/api/v1")
        app.dependency_overrides[get_db] = test_database
        with TestClient(app) as client:
            base = "/api/v1/kg/ontologies"
            response = client.post(base + "/validate", json={"content": MODEL, "format": "yaml"}, headers=headers)
            response.raise_for_status()
            definition = response.json()
            response = client.post(base, json=definition, headers=headers)
            response.raise_for_status()
            workspace = response.json()
            response = client.post(
                base + "/" + workspace["id"] + "/versions",
                json={"expected_revision": workspace["draft_revision"]},
                headers=headers,
            )
            response.raise_for_status()
            version = response.json()
            assert version["definition"] == definition
            response = client.post(
                base + "/preview",
                json={"definition": version["definition"], "source": {"kind": "sample", "text": SAMPLE}},
                headers=headers,
            )
            response.raise_for_status()
            preview = response.json()[0]
            names = {item["id"]: item["name"] for item in preview["entities"]}
            assert any(
                relation["predicate"] == "order_for_equipment"
                and "WO-01" in names[relation["subject_id"]]
                and "E-102" in names[relation["object_id"]]
                and SAMPLE[relation["evidence"]["start_char"] : relation["evidence"]["end_char"]]
                == relation["evidence"]["quote"]
                for relation in preview["relations"]
            ), preview
            print(
                json.dumps(
                    {
                        "model": settings.LLM_MODEL,
                        "endpoint": base + "/preview",
                        "published_version": version["number"],
                        "entities": len(names),
                        "accepted_relations": len(preview["relations"]),
                        "result": "passed",
                    }
                )
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
