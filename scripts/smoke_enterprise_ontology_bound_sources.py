"""Verify the published-ontology workflow against isolated PostgreSQL and MySQL fixtures."""

import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from threading import Thread
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

import pymysql
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.models.registry  # noqa: F401
from app.api.middleware.request_context import RequestContextMiddleware
from app.api.v1 import get_router
from app.infrastructure.config import settings
from app.infrastructure.database.connection import SessionLocal
from app.models.connectors.configs import ConnectorConfig
from app.models.datasets.catalog import DbCatalogColumn, DbCatalogTable
from app.models.datasets.records import Dataset
from app.models.documents.records import Document, DocumentChunk
from app.models.identity.workspaces import Tenant, TenantMember
from app.models.knowledge_graph.enterprise_ontology import EnterpriseOntologyActionRequest
from app.rag.kg.enterprise_ontology.actions import ActionTarget

SLA_TEXT = (
    "工单 WO-01 归属于设备 E-102。设备 E-102 的维修工单按记录的截止时间判定逾期。"
    "文号 SLA-2026-11，发布单位设备部。本制度于 2026-11-01 生效，有效至 2026-12-01。"
)


@contextmanager
def business_server():
    receipts = {}

    class BusinessTarget(BaseHTTPRequestHandler):
        def respond(self, status, data):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.headers.get("Authorization") != "Bearer fixture-caller":
                self.respond(403, {})
            elif self.path == "/authorize":
                self.respond(200, {"allowed": body["key"] == {"order_id": "WO-01"}})
            elif self.path == "/execute":
                key = self.headers.get("Idempotency-Key")
                assert key == body["request_id"] and key not in receipts
                reason = body["parameters"]["reason"]
                result = {
                    "request_id": key,
                    "receipt_id": "closed:" + key,
                    "status": "succeeded",
                    "sync_status": "pending",
                }
                if reason != "missing":
                    receipts[key] = result
                self.respond(200 if reason == "done" else 503, result if reason == "done" else {})
            else:
                self.respond(404, {})

        def do_GET(self):
            result = receipts.get(self.path.rsplit("/", 1)[-1])
            self.respond(200, {**result, "sync_status": "synced"}) if result else self.respond(404, {})

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), BusinessTarget)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def seed_mysql(port: int) -> None:
    connection = pymysql.connect(
        host="127.0.0.1",
        port=port,
        user="ontology_fixture",
        password="ontology_fixture_local",
        database="maintenance",
        autocommit=True,
    )
    try:
        with connection.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS equipment (id VARCHAR(30) PRIMARY KEY, name VARCHAR(100))")
            cur.execute(
                "CREATE TABLE IF NOT EXISTS work_orders (id VARCHAR(30) PRIMARY KEY, asset_id VARCHAR(30), "
                "deadline DATETIME, state VARCHAR(20), visible_to VARCHAR(80))"
            )
            cur.execute("INSERT IGNORE INTO equipment VALUES ('E-102', '泵'), ('E-103', '泵')")
            cur.executemany(
                "INSERT IGNORE INTO work_orders VALUES (%s,%s,%s,%s,%s)",
                [
                    ("WO-01", "E-102", "2026-11-08 20:00:00", "OPEN", "ontology-fixture"),
                    ("WO-02", "E-102", "2026-11-10 20:00:00", "CLOSED", "ontology-fixture"),
                    ("WO-03", "E-102", "2026-11-29 20:00:00", "OPEN", "ontology-fixture"),
                    ("WO-04", "E-103", "2026-11-09 20:00:00", "OPEN", "ontology-fixture"),
                    ("WO-05", "E-102", "2026-11-09 20:00:00", "OPEN", "other-account"),
                ],
            )
    finally:
        connection.close()


def seed_assets(mysql_port: int, tenant_id, dataset_id, document_id) -> dict[str, str]:
    with SessionLocal() as db:
        account = "ontology-fixture"
        db.add(Tenant(id=tenant_id, name="ontology-" + str(tenant_id)))
        db.flush()
        db.add(TenantMember(tenant_id=tenant_id, user_id=account, role="owner"))
        db.add(Dataset(id=dataset_id, tenant_id=tenant_id, name="维修制度", owner_id=account))
        db.flush()
        connector = ConnectorConfig(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            connector_id="mysql_catalog",
            name="工单验收数据",
            config={
                "host": "127.0.0.1",
                "port": mysql_port,
                "database": "maintenance",
                "username": "ontology_fixture",
                "password": "ontology_fixture_local",
            },
        )
        db.add(connector)
        db.flush()
        assets = {}
        for table_name, names in (
            ("equipment", ["id", "name"]),
            ("work_orders", ["id", "asset_id", "deadline", "state", "visible_to"]),
        ):
            table = DbCatalogTable(
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                connector_config_id=connector.id,
                engine="mysql",
                db_name="maintenance",
                table_name=table_name,
                fingerprint=table_name,
                columns=[DbCatalogColumn(name=name, ordinal=index) for index, name in enumerate(names)],
            )
            db.add(table)
            db.flush()
            assets[table_name] = "catalog:" + str(table.id)
        db.add(
            Document(
                id=document_id,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                owner_id=account,
                filename="SLA-2026-11",
                file_type="txt",
                file_size=len(SLA_TEXT),
                file_path="fixture-sla.txt",
                status="completed",
                publication_status="published",
                doc_metadata={
                    "pipeline_hash": "fixture-v1",
                    "active_pipeline_hash": "fixture-v1",
                    "effective_at": "2026-11-01",
                },
            )
        )
        db.flush()
        db.add(
            DocumentChunk(
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_index=0,
                content=SLA_TEXT,
                page_number=3,
                doc_metadata={"pipeline_hash": "fixture-v1"},
            )
        )
        db.commit()
    return assets


def definition(assets: dict[str, str]) -> dict:
    return {
        "schema_version": 1,
        "ontology": "maintenance",
        "object_types": {
            "equipment": {
                "label": "设备",
                "key": ["equipment_id"],
                "properties": {"equipment_id": "string", "name": "string"},
            },
            "work_order": {
                "label": "维修工单",
                "key": ["order_id"],
                "properties": {
                    "order_id": "string",
                    "equipment_id": "string",
                    "due_at": "datetime",
                    "status": {"type": "string", "enum": ["OPEN", "CLOSED"]},
                },
            },
        },
        "relations": {
            "order_for_equipment": {
                "label": "工单归属于设备",
                "from": "work_order",
                "to": "equipment",
                "cardinality": "many_to_one",
            }
        },
        "bindings": [
            {
                "object_type": "equipment",
                "role": "primary",
                "asset_id": assets["equipment"],
                "identity_columns": ["id"],
                "columns": {"equipment_id": "id", "name": "name"},
            },
            {
                "object_type": "work_order",
                "role": "primary",
                "asset_id": assets["work_orders"],
                "identity_columns": ["id"],
                "row_access_column": "visible_to",
                "columns": {"order_id": "id", "equipment_id": "asset_id", "due_at": "deadline", "status": "state"},
            },
        ],
        "relation_bindings": {"order_for_equipment": {"source_columns": ["asset_id"], "target_columns": ["id"]}},
        "metrics": {
            "overdue_work_orders": {
                "object_type": "work_order",
                "property": "order_id",
                "aggregate": "count_distinct",
                "time_property": "due_at",
                "timezone": "America/Los_Angeles",
                "allowed_filters": ["equipment_id"],
                "required_filters": {
                    "status": "OPEN",
                },
                "before_observation": True,
                "label": "逾期工单数",
                "unit": "张",
            },
        },
        "document_templates": {
            "rectification": {
                "title": "整改说明",
                "fields": {
                    "equipment": {"label": "设备", "source": "object_key"},
                    "overdue": {"label": "逾期数量", "source": "metric"},
                    "authority": {"label": "依据", "source": "citations"},
                    "decision": {"label": "处置意见", "source": "manual"},
                },
            },
        },
        "document_metadata": {
            "document_number": {"type": "string", "label": "文号"},
            "issuing_org": {"type": "string", "label": "发布单位"},
            "effective_at": {"type": "date", "label": "生效日期"},
            "expires_at": {"type": "date", "label": "失效日期"},
        },
        "rules": {
            "overdue": {
                "object_type": "work_order",
                "label": "逾期规则",
                "conditions": [
                    {"property": "due_at", "operator": "lt", "operand": "observed_at"},
                    {"property": "status", "operator": "eq", "value": "OPEN"},
                ],
            },
        },
        "functions": {"calculate_overdue": {"metric": "overdue_work_orders", "label": "计算逾期数量"}},
        "actions": {
            "close_order": {
                "object_type": "work_order",
                "target": "maintenance",
                "label": "关闭维修工单",
                "parameters": {"reason": {"type": "string", "required": True}},
                "preconditions": ["overdue"],
                "approval_required": True,
            },
        },
    }


def main() -> None:
    mysql_port = int(os.environ["MIMIRQ_ONTOLOGY_FIXTURE_MYSQL_PORT"])
    assert settings.DATABASE_URL.endswith("/ontology_fixture")
    settings.AUTH_MODE = "header"
    settings.CHAT_STREAM_PERSIST_IN_BACKGROUND = False
    seed_mysql(mysql_port)
    tenant_id, dataset_id, document_id = uuid4(), uuid4(), uuid4()
    assets = seed_assets(mysql_port, tenant_id, dataset_id, document_id)
    headers = {"X-Tenant-ID": str(tenant_id), "X-User-ID": "ontology-fixture", "Authorization": "Bearer fixture-caller"}
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.include_router(get_router(), prefix="/api/v1")

    with business_server() as target, TestClient(app) as client:
        settings.ONTOLOGY_ACTION_TARGETS = {str(tenant_id): {"maintenance": f"http://127.0.0.1:{target.server_port}"}}

        def request(method, path, payload=None):
            response = client.request(method, "/api/v1/kg/ontologies" + path, json=payload, headers=headers)
            if not response.is_success:
                raise AssertionError(f"{method} {path} -> {response.status_code}: {response.text[:900]}")
            return response.json()

        model = definition(assets)
        assert all(not item["issues"] for item in request("POST", "/binding-preview", model))
        workspace = request("POST", "", model)
        version = request("POST", "/" + workspace["id"] + "/versions", {"expected_revision": 1})
        prefix = "/" + workspace["id"] + "/versions/" + version["id"]
        extracted = request("POST", prefix + "/documents", {"document_id": str(document_id)})
        assert extracted["chunk_count"] == 1
        metadata_path = prefix + "/documents/" + str(document_id) + "/metadata"
        verified_metadata = request("GET", metadata_path)
        for field, value in {
            "document_number": "SLA-2026-11",
            "issuing_org": "设备部",
            "effective_at": "2026-11-01",
            "expires_at": "2026-12-01",
        }.items():
            candidates = verified_metadata[field]["candidates"]
            assert verified_metadata[field]["state"] == "pending", verified_metadata
            selected = next((item for item in candidates if item["value"] == value), None)
            assert selected and selected["page"] == 3, (field, candidates)
            assert (
                SLA_TEXT[selected["evidence"]["start_char"] : selected["evidence"]["end_char"]]
                == selected["evidence"]["quote"]
            )
            reviewed = request("PUT", metadata_path, {"field": field, "candidate_ids": [selected["id"]]})
            assert reviewed[field]["state"] == "confirmed"
        activated = request("PUT", prefix + "/datasets/" + str(dataset_id))
        assert activated["version_id"] == version["id"]
        observed = datetime.fromisoformat("2026-11-23T12:00:00-08:00").isoformat()
        known = request(
            "POST",
            prefix + "/metrics/overdue_work_orders",
            {
                "filters": {"equipment_id": "E-102"},
                "start": "2026-11-01T00:00:00-07:00",
                "end": "2026-12-01T00:00:00-08:00",
                "observed_at": observed,
            },
        )
        assert known["value"] == 1 and known["complete"], known
        related = request(
            "POST",
            prefix + "/relations/order_for_equipment/from/equipment",
            {"key": {"equipment_id": "E-102"}},
        )
        assert {row["key"]["order_id"] for row in related["objects"]} == {"WO-01", "WO-02", "WO-03"}, related
        function = request("POST", prefix + "/functions/calculate_overdue", known["query"])
        assert function["result"]["value"] == 1, function
        rule = request("POST", prefix + "/rules/overdue", {"key": {"order_id": "WO-01"}, "observed_at": observed})
        assert rule["outcome"] == "true", rule
        unreadable = client.post(
            "/api/v1/kg/ontologies" + prefix + "/rules/overdue",
            json={"key": {"order_id": "WO-05"}, "observed_at": observed},
            headers=headers,
        )
        assert unreadable.status_code == 404
        question = {
            "question": "设备 E-102 本月到期且现在逾期的工单有几张，依据哪版维修制度？引用对应原文。",
            "dataset_ids": [str(dataset_id)],
            "observed_at": observed,
        }
        answer = request("POST", prefix + "/ask", question)
        assert (answer.get("metric") or {}).get("value") == 1 and any(
            citation["page"] == 3 and citation["filename"] == "SLA-2026-11" for citation in answer["citations"]
        ), answer
        assert answer["metric"]["query"]["start"] == "2026-11-01T00:00:00-07:00", answer
        object_answer = request(
            "POST",
            prefix + "/ask",
            {
                "question": "沿 order_for_equipment 关系查询设备 E-102 的所有工单，列出这些工单。",
            },
        )
        assert object_answer["related"], object_answer
        assert {row["key"]["order_id"] for row in object_answer["related"]["objects"]} == {
            "WO-01",
            "WO-02",
            "WO-03",
        }, object_answer
        rule_answer = request(
            "POST",
            prefix + "/ask",
            {
                "question": "用逾期规则 overdue 判断维修工单 WO-01 是否逾期。",
                "observed_at": observed,
            },
        )
        assert (rule_answer["rule"] or {}).get("outcome") == "true", rule_answer
        function_answer = request(
            "POST",
            prefix + "/ask",
            {
                "question": "调用 calculate_overdue 函数计算设备 E-102 本月逾期的工单数量。",
                "observed_at": observed,
            },
        )
        assert ((function_answer["function"] or {}).get("result") or {}).get("value") == 1, function_answer
        proposal = request(
            "POST",
            prefix + "/ask",
            {
                "question": "预演动作 close_order 关闭维修工单 WO-01，关闭原因是 done。",
            },
        )["plan"]
        assert proposal["action_id"] == "close_order" and proposal["business_key"] == "WO-01", proposal
        assert proposal["action_parameters"] == {"reason": "done"}, proposal
        for reason, state in (("done", "succeeded"), ("recover", "succeeded"), ("missing", "manual_review")):
            request_id = str(uuid4())
            inputs = {
                "request_id": request_id,
                "key": {"order_id": proposal["business_key"]},
                "parameters": {"reason": reason},
            }
            prepare = prefix + "/actions/close_order/prepare"
            action = prefix + "/action-requests/" + request_id
            preview = request("POST", prepare, inputs)
            assert preview["state"] == "awaiting_approval"
            assert client.post("/api/v1/kg/ontologies" + action + "/execute", headers=headers).status_code == 409
            assert request("POST", action + "/approve")["state"] == "ready"
            receipt = request("POST", action + "/execute")
            assert request("POST", action + "/execute") == receipt
            assert receipt["state"] == ("succeeded" if reason == "done" else "unknown")
            assert request("POST", prepare, inputs) == receipt
            conflict = client.post(
                "/api/v1/kg/ontologies" + prepare,
                headers=headers,
                json={**inputs, "parameters": {"reason": "changed"}},
            )
            assert conflict.status_code == 409
            settled = request("POST", action + "/receipt")
            assert settled["state"] == state, settled
            if state == "succeeded":
                assert settled["receipt"]["sync_status"] == "synced", settled

        interrupted_id = uuid4()
        interrupted_path = prefix + "/action-requests/" + str(interrupted_id)
        request("POST", prepare, {
            "request_id": str(interrupted_id),
            "key": {"order_id": proposal["business_key"]},
            "parameters": {"reason": "missing"},
        })
        assert request("POST", interrupted_path + "/approve")["state"] == "ready"
        send = ActionTarget.request
        dispatches = []

        def interrupt(target, method, path, **kwargs):
            response = send(target, method, path, **kwargs)
            if path == "execute":
                dispatches.append(kwargs["headers"]["Idempotency-Key"])
                raise RuntimeError("fixture dispatch interrupted")
            return response

        with patch.object(ActionTarget, "request", interrupt):
            try:
                request("POST", interrupted_path + "/execute")
            except RuntimeError as exc:
                assert str(exc) == "fixture dispatch interrupted"
            else:
                raise AssertionError("fixture dispatch did not interrupt")
            assert request("POST", interrupted_path + "/receipt")["state"] == "dispatching"
            with SessionLocal() as db:
                row = db.get(EnterpriseOntologyActionRequest, (tenant_id, interrupted_id))
                assert row.dispatch_started_at is not None
                row.dispatch_started_at = datetime.now(UTC) - timedelta(seconds=61)
                db.commit()
            review = request("POST", interrupted_path + "/receipt")
            assert review["state"] == "manual_review" and review["receipt"] is None
            assert request("POST", interrupted_path + "/execute") == review
        assert dispatches == [str(interrupted_id)]

        draft = request("POST", prefix + "/draft-documents", {"template_id": "rectification", "question": question})
        assert draft["missing_required"] == ["decision"], draft
        draft_path = prefix + "/draft-documents/" + draft["id"]
        reopened = request("GET", draft_path)
        assert reopened == draft, (draft, reopened)

        def export() -> str:
            res = client.get("/api/v1/kg/ontologies" + draft_path + "/docx", headers=headers)
            assert res.is_success, (res.status_code, res.text[:500])
            with ZipFile(BytesIO(res.content)) as archive:
                return archive.read("word/document.xml").decode()

        assert "SLA-2026-11" in export()
        chat = client.post(
            "/api/v1/chat",
            headers=headers,
            json={
                "message": question["question"],
                "dataset_id": str(dataset_id),
                "structured_output": True,
            },
        )
        assert chat.is_success, (chat.status_code, chat.text[:800])
        chat_answer = chat.json()
        assert chat_answer["structured_data"]["metric"]["value"] == 1, chat_answer
        assert chat_answer["citations"][0]["page_number"] == 3
        conversation_id = chat_answer["conversation_id"]
        history_path = f"/api/v1/chat/conversations/{conversation_id}/messages"
        history = client.get(history_path, headers=headers).json()["messages"]
        assert "SLA-2026-11" in history[-1]["content"] and history[-1]["citations"], history
        stream = client.post(
            "/api/v1/chat/stream",
            headers=headers,
            json={
                "threadId": str(uuid4()),
                "runId": str(uuid4()),
                "state": {},
                "tools": [],
                "context": [],
                "messages": [{"id": str(uuid4()), "role": "user", "content": question["question"]}],
                "forwardedProps": {"dataset_id": str(dataset_id)},
            },
        )
        assert stream.is_success and "SLA-2026-11" in stream.text and "enterprise_ontology" in stream.text, stream.text[
            :850
        ]
        final = client.get("/api/v1/kg/ontologies" + draft_path + "/docx?final=true", headers=headers)
        assert final.status_code == 409
        with SessionLocal() as db:
            doc = db.get(Document, document_id)
            doc.publication_status = "draft"
            db.commit()
        restricted = request("GET", draft_path)
        assert set(restricted["missing_required"]) == {"authority", "decision"}, restricted
        assert "SLA-2026-11" not in restricted["markdown"] + export()
        reopened_history = client.get(history_path, headers=headers).json()["messages"]
        assert "SLA-2026-11" not in reopened_history[-1]["content"] and not reopened_history[-1]["citations"]
        conversation_export = client.get(
            f"/api/v1/chat/conversations/{conversation_id}/export",
            headers=headers,
            params={"fmt": "json"},
        )
        assert conversation_export.is_success and "SLA-2026-11" not in conversation_export.text
        print(
            json.dumps(
                {
                    "model": settings.LLM_MODEL,
                    "metric": 1,
                    "citation": "SLA-2026-11 p3",
                    "metadata": "document number, issuing unit and both date boundaries grounded and confirmed",
                    "source": "MySQL catalog",
                    "docx": "readback, draft export and publication revocation passed",
                    "behavior": "rule, function, approval, dispatch, replay and receipt lookup passed",
                    "chat": "standard and streaming, history and export reauthorization passed",
                    "result": "passed",
                }
            )
        )


if __name__ == "__main__":
    main()
