"""Exercise registered Table Store sources and version switching with a live model."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.models.registry  # noqa: F401
from app.api.middleware.request_context import RequestContextMiddleware
from app.api.v1 import get_router
from app.infrastructure.config import settings
from app.infrastructure.database.connection import SessionLocal
from app.models.datasets.records import Dataset
from app.models.documents.records import Document, DocumentChunk
from app.models.identity.workspaces import Tenant, TenantMember
from app.services.tables.store import import_table_document
from scripts.smoke_enterprise_ontology_bound_sources import SLA_TEXT, definition

ACCOUNT = "ontology-fixture"
OBSERVED = "2026-11-23T12:00:00-08:00"
HISTORICAL = "2026-11-10T08:00:00Z"


def _seed_snapshot(db, *, tenant_id: UUID, dataset_id: UUID, temp_dir: Path, name: str, content: str) -> str:
    document_id = uuid4()
    path = temp_dir / name
    path.write_text(content, encoding="utf-8")
    [asset] = import_table_document(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_id=document_id,
        file_path=path,
        max_rows=20,
        max_cols=8,
        sample_rows=5,
    )
    table = asdict(asset)
    table.pop("document_id")
    db.add(
        Document(
            id=document_id,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            owner_id=ACCOUNT,
            filename=name,
            file_type="csv",
            file_path=str(path),
            file_size=len(content),
            status="completed",
            publication_status="published",
            doc_metadata={"table_store": {"tables": [table]}},
        )
    )
    return asset.table_id


def _seed_data(temp_dir: Path, tenant: UUID, source: UUID, knowledge: UUID, alternative: UUID, doc: UUID) -> dict:
    with SessionLocal() as db:
        db.add(Tenant(id=tenant, name="snapshot-" + str(tenant)))
        db.flush()
        db.add(TenantMember(tenant_id=tenant, user_id=ACCOUNT, role="owner"))
        for dataset_id, title in ((source, "维修快照"), (knowledge, "维修制度"), (alternative, "备选知识库")):
            db.add(Dataset(id=dataset_id, tenant_id=tenant, name=title, owner_id=ACCOUNT))
        db.flush()
        assets = {
            "equipment": _seed_snapshot(
                db,
                tenant_id=tenant,
                dataset_id=source,
                temp_dir=temp_dir,
                name="equipment.csv",
                content="id,name,threshold\nE-102,泵,1\nE-103,泵,1\n",
            ),
            "work_orders": _seed_snapshot(
                db,
                tenant_id=tenant,
                dataset_id=source,
                temp_dir=temp_dir,
                name="work_orders.csv",
                content=(
                    "id,asset_id,deadline,state,visible_to\n"
                    "WO-01,E-102,2026-11-08T20:00:00Z,OPEN,ontology-fixture\n"
                    "WO-02,E-102,2026-11-10T20:00:00Z,CLOSED,ontology-fixture\n"
                    "WO-03,E-102,2026-11-29T20:00:00Z,OPEN,ontology-fixture\n"
                    "WO-04,E-103,2026-11-09T20:00:00Z,OPEN,ontology-fixture\n"
                    "WO-05,E-102,2026-11-09T20:00:00Z,OPEN,other-account\n"
                ),
            ),
        }
        db.add(
            Document(
                id=doc,
                tenant_id=tenant,
                dataset_id=knowledge,
                owner_id=ACCOUNT,
                filename="SLA-2026-11",
                file_type="txt",
                file_path="fixture.txt",
                file_size=len(SLA_TEXT),
                status="completed",
                publication_status="published",
                doc_metadata={
                    "pipeline_hash": "fixture-v1",
                    "active_pipeline_hash": "fixture-v1",
                    "effective_at": "2026-11-01",
                    "expires_at": "2026-12-01",
                },
            )
        )
        db.flush()
        db.add(
            DocumentChunk(
                tenant_id=tenant,
                document_id=doc,
                content=SLA_TEXT,
                chunk_index=0,
                page_number=3,
                doc_metadata={"pipeline_hash": "fixture-v1"},
            )
        )
        db.commit()
    return assets


def main() -> None:
    assert settings.DATABASE_URL.endswith("/ontology_fixture")
    settings.AUTH_MODE = "header"
    settings.KG_ENABLED = True
    tenant, source, knowledge, alternative, doc = (uuid4() for _ in range(5))
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.include_router(get_router(), prefix="/api/v1")
    headers = {"X-Tenant-ID": str(tenant), "X-User-ID": ACCOUNT}
    with TemporaryDirectory(prefix="mimirq-ontology-tables-") as temp, TestClient(app) as client:
        settings.TABLE_STORE_DIR = temp
        assets = _seed_data(Path(temp), tenant, source, knowledge, alternative, doc)
        base = "/api/v1/kg/ontologies"

        def request(method, path, body=None, status=None):
            response = client.request(method, base + path, json=body, headers=headers)
            assert response.status_code == status if status else response.is_success, (path, response.text[:1000])
            return response.json()

        available = request("GET", f"/assets?dataset_id={source}")
        assert set(assets.values()) <= {item["id"] for item in available}
        suggestion = request(
            "POST",
            "/suggest",
            {
                "ontology": "maintenance",
                "dataset_id": str(source),
                "asset_ids": [assets["equipment"]],
                "sample": "仅建立设备对象 equipment，业务主键 id。源表的 id 是设备编号，name 是设备名称。",
            },
        )
        assert suggestion["definition"]["ontology"] == "maintenance" and suggestion["definition"]["object_types"]
        assert suggestion["sources"][0]["id"] == assets["equipment"], suggestion
        draft = definition(assets)
        draft.pop("actions")
        draft["document_metadata"] = {
            "sla_hours": {"type": "integer", "label": "维修时限", "method": "manual", "compare_across_documents": True},
        }
        draft["object_types"]["equipment"]["properties"]["threshold"] = "integer"
        draft["bindings"][0]["columns"]["threshold"] = "threshold"
        draft["bindings"][1]["snapshot_observed_at"] = HISTORICAL
        draft["rules"]["aggregate_check"] = {
            "label": "逾期数量和设备限额相同",
            "object_type": "equipment",
            "conditions": [
                {
                    "property": "threshold",
                    "operator": "eq",
                    "operand": "function",
                    "function": "calculate_overdue",
                    "function_filters": {"equipment_id": "equipment_id"},
                }
            ],
        }
        workspace = "/" + request("POST", "", draft)["id"]
        first = request("POST", workspace + "/versions", {"expected_revision": 1})
        v1 = workspace + "/versions/" + first["id"]
        assert all(item["asset_revision"] for item in first["definition"]["bindings"])
        assert request("POST", v1 + "/documents", {"document_id": str(doc)})["chunk_count"] == 1
        request("PUT", v1 + f"/datasets/{knowledge}")
        kg = client.post(f"/api/v1/kg/documents/{doc}/extract?async=false", headers=headers)
        assert kg.is_success and kg.json()["ontology_version_id"] == first["id"], kg.text[:500]
        assert request("GET", v1 + f"/documents/{doc}/evidence")[0]["entities"]
        question = {
            "question": "设备 E-102 本月到期且现在逾期的工单有几张，依据哪版维修制度？引用对应原文。",
            "observed_at": OBSERVED,
        }
        mixed = request("POST", f"/datasets/{knowledge}/ask", question)
        assert mixed["metric"]["value"] == 1 and mixed["metric"]["complete"], mixed
        assert mixed["citations"][0]["page"] == 3, mixed
        historical_question = "截至 2026 年 11 月 10 日，设备 E-102 的 overdue_work_orders 是多少？依据哪版维修制度？"
        historical = request("POST", f"/datasets/{knowledge}/ask", {"question": historical_question})
        assert datetime.fromisoformat(historical["metric"]["query"]["observed_at"]) == datetime.fromisoformat(HISTORICAL)
        assert historical["metric"]["value"] == 1 and historical["metric"]["complete"], historical
        assert historical["citations"][0]["filename"] == "SLA-2026-11" and historical["citations"][0]["page"] == 3
        gap = request("POST", f"/datasets/{knowledge}/ask", {"question": historical_question.replace("10 日", "11 日")})
        assert gap["metric"]["value"] is None and gap["metric"]["reason"] == "historical_state_unavailable", gap
        assert gap["citations"][0]["filename"] == "SLA-2026-11", gap
        no_history = request(
            "POST",
            v1 + "/metrics/overdue_work_orders",
            {
                "observed_at": OBSERVED,
                "filters": {"equipment_id": "E-102"},
                "historical_state": True,
            },
        )
        assert no_history["value"] is None and not no_history["complete"], no_history
        choices = request("POST", f"/datasets/{knowledge}/ask", {"question": "显示名为泵的设备有哪些同名对象？"})
        assert {item["key"]["equipment_id"] for item in choices["object_choices"]} == {"E-102", "E-103"}, choices
        rule = request(
            "POST",
            f"/datasets/{knowledge}/ask",
            {
                "question": "对设备 E-102 运行 aggregate_check 规则，核验逾期数量与设备限额是否相同。",
                "observed_at": OBSERVED,
            },
        )["rule"]
        assert rule and rule["outcome"] == "true" and rule["functions"][0]["value"] == 1, rule

        draft["object_types"]["equipment"]["label"] = "维修设备"
        request("PUT", workspace + "/draft", {"expected_revision": 1, "definition": draft})
        second = request("POST", workspace + "/versions", {"expected_revision": 2})
        v2 = workspace + "/versions/" + second["id"]
        request("PUT", v2 + f"/datasets/{knowledge}", status=409)
        assert request("GET", f"/datasets/{knowledge}/active")["version_id"] == first["id"]
        request("PUT", v2 + f"/datasets/{alternative}")
        question["dataset_ids"] = [str(knowledge), str(alternative)]
        unresolved = request("POST", "/ask", question, status=409)
        assert {item["version_id"] for item in unresolved["detail"]["versions"]} == {first["id"], second["id"]}
        mixed = request("POST", f"/datasets/{knowledge}/ask", question)
        assert mixed["ontology_version_id"] == first["id"] and mixed["citations"], mixed
        assert "知识库的本体版本不可用" in mixed["unavailable"]
        request("POST", v2 + "/documents", {"document_id": str(doc)})
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(request, "PUT", v2 + f"/datasets/{knowledge}") for _ in range(2)]
            assert all(task.result()["version_id"] == second["id"] for task in futures)
        request("PUT", v1 + f"/datasets/{knowledge}")
        assert request("GET", f"/datasets/{knowledge}/active")["version_id"] == first["id"]
        with SessionLocal() as db:
            source_dataset = db.get(Dataset, source)
            original = source_dataset.dataset_metadata
            source_dataset.dataset_metadata = {
                **original,
                "fls_policy": {
                    "rules": [
                        {
                            "id": "fixture_denied_deadline",
                            "name": "收回截止时间权限",
                            "sources": ["table_store"],
                            "column_name_regex": "^deadline$",
                            "allow_account_ids": ["other-account"],
                        }
                    ]
                },
            }
            db.commit()
        partial = request("POST", f"/datasets/{knowledge}/ask", question)
        assert partial["metric"] is None and partial["citations"], partial
        with SessionLocal() as db:
            source_dataset = db.get(Dataset, source)
            source_dataset.dataset_metadata = original
            db.commit()
        revision_docs = []
        with SessionLocal() as db:
            for number, hours, expires in (
                ("A", 48, "2026-12-01"),
                ("B", 72, "2026-12-01"),
                ("expired", 24, "2026-11-01"),
            ):
                doc_id, chunk_id = uuid4(), uuid4()
                content = f"设备 E-102 的维修时限为 {hours} 小时。"
                db.add(
                    Document(
                        id=doc_id,
                        tenant_id=tenant,
                        dataset_id=knowledge,
                        owner_id=ACCOUNT,
                        filename=f"policy-{number}",
                        file_type="txt",
                        file_path="fixture.txt",
                        file_size=len(content),
                        status="completed",
                        publication_status="published",
                        doc_metadata={
                            "pipeline_hash": "fixture-v1",
                            "active_pipeline_hash": "fixture-v1",
                            "effective_at": "2026-10-01",
                            "expires_at": expires,
                        },
                    )
                )
                db.flush()
                db.add(
                    DocumentChunk(
                        id=chunk_id,
                        tenant_id=tenant,
                        document_id=doc_id,
                        content=content,
                        chunk_index=0,
                        page_number=1,
                        doc_metadata={"pipeline_hash": "fixture-v1"},
                    )
                )
                revision_docs.append((doc_id, chunk_id, content.index(str(hours))))
            db.commit()
        for doc_id, chunk_id, start in revision_docs:
            request("POST", v1 + "/documents", {"document_id": str(doc_id)})
            metadata = request(
                "PUT",
                v1 + f"/documents/{doc_id}/metadata",
                {
                    "field": "sla_hours",
                    "manual_values": [
                        {"chunk_id": str(chunk_id), "start_char": start, "end_char": start + 2},
                    ],
                },
            )
            assert metadata["sla_hours"]["state"] == "confirmed"
        conflict = request("POST", f"/datasets/{knowledge}/ask", question)
        assert conflict["conflicts"] == ["sla_hours"], conflict
        assert {item["filename"] for item in conflict["citations"]} == {"policy-A", "policy-B", "SLA-2026-11"}, conflict
        print(
            json.dumps(
                {
                    "model": settings.LLM_MODEL,
                    "result": "passed",
                    "source": "CSV through Table Store",
                    "metric": 1,
                    "citation": "SLA-2026-11 p3",
                    "same_name_choices": ["E-102", "E-103"],
                    "versions": "candidate, concurrent activation, rollback and cross-dataset selection",
                    "historical": "Chinese date uses Los Angeles midnight; matched and missing snapshots cite SLA-2026-11 p3",
                    "permissions": "FLS preserves authorized documents without a metric",
                    "conflict": "concurrent policies preserved, expired source excluded",
                    "function_rule": "rule uses the authorized named metric function",
                    "suggestion": "authorized asset-backed draft",
                    "extraction": "normal KG entry",
                }
            )
        )


if __name__ == "__main__":
    main()
