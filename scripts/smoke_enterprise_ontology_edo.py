"""Run the published ontology ask endpoint with a local EDO HTTP contract and its SQL runner."""

import argparse
import json
import runpy
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlsplit
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
from scripts.smoke_enterprise_ontology_bound_sources import SLA_TEXT
from scripts.smoke_enterprise_ontology_bound_sources import definition as maintenance_definition

ACCOUNT = "ontology-edo-fixture"
EDO_TOKEN = "edo-fixture-caller"
SYNCED_AT = "2026-11-23T20:00:00Z"
EDO_PATH = "/api/ontology/workspaces/maintenance/capabilities"
EDO_TABLES = {
    "obj_1": {"col_1": "STRING", "col_2": "STRING"},
    "obj_2": {"col_1": "STRING", "col_2": "STRING", "col_3": "DATETIME", "col_4": "STRING"},
}
EDO_ROWS = {
    "obj_1": [("E-102", "泵"), ("E-103", "泵")],
    "obj_2": [
        ("WO-01", "E-102", "2026-11-08T20:00:00Z", "OPEN"),
        ("WO-02", "E-102", "2026-11-10T20:00:00Z", "CLOSED"),
        ("WO-03", "E-102", "2026-11-29T20:00:00Z", "OPEN"),
        ("WO-04", "E-103", "2026-11-09T20:00:00Z", "OPEN"),
        ("WO-05", "E-102", "2026-11-09T20:00:00Z", "OPEN"),
    ],
}


@dataclass
class FixtureState:
    working_revision: int = 7
    sql_calls: int = 0


@contextmanager
def edo_fixture(sql_runner: Path):
    execute_sql = runpy.run_path(str(sql_runner))["execute"]
    state = FixtureState()

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status: int, data: object = None, *, error: str | None = None):
            payload = json.dumps(
                {"code": "10000", "success": True, "data": data}
                if error is None
                else {"code": "40000", "success": False, "subCode": error}
            ).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def authorize(self, revision: int) -> bool:
            if self.headers.get("Authorization") != EDO_TOKEN:
                self.respond(403, error="ONTOLOGY_ACCESS_DENIED")
                return False
            if revision != state.working_revision:
                self.respond(409, error="ONTOLOGY_REVISION_CONFLICT")
                return False
            return True

        def do_GET(self):
            url = urlsplit(self.path)
            assert url.path == EDO_PATH + "/skill"
            [revision] = parse_qs(url.query)["expectedWorkingRevision"]
            if self.authorize(int(revision)):
                self.respond(
                    200,
                    {
                        "workingRevision": state.working_revision,
                        "files": [],
                        "tables": [
                            {
                                "name": name,
                                "kind": "OBJECT",
                                "columns": [{"name": column, "type": kind} for column, kind in columns.items()],
                            }
                            for name, columns in EDO_TABLES.items()
                        ],
                    },
                )

        def do_POST(self):
            assert self.path == EDO_PATH + "/sql"
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if not self.authorize(request["expectedWorkingRevision"]):
                return
            [table] = request["tables"]
            name = table["table"]
            columns = EDO_TABLES[name]
            visible_rows = EDO_ROWS[name][:-1] if name == "obj_2" else EDO_ROWS[name]
            prepared = {
                "name": name,
                "columns": [{"name": column, "type": columns[column]} for column in table["columns"]],
                "rows": [
                    {column: item[column] for column in table["columns"]}
                    for row in visible_rows
                    for item in [dict(zip(columns, row, strict=True))]
                ],
            }
            result = execute_sql({"tables": [prepared], "sql": request["sql"]}, 4000)
            state.sql_calls += 1
            truncated = result["truncated"]
            self.respond(
                200,
                {
                    "requestId": str(uuid4()),
                    "status": "partial" if truncated else ("success" if result["rows"] else "empty"),
                    "reasonCode": "RESULT_TRUNCATED" if truncated else None,
                    "workingRevision": state.working_revision,
                    "projectionId": "fixture-projection-7",
                    "syncedAt": SYNCED_AT,
                    "sourceDataIds": ["fixture-equipment" if name == "obj_1" else "fixture-work-orders"],
                    "returnedCount": len(result["rows"]),
                    "truncated": truncated,
                    "data": {**result, "table": name, "loadedRowCount": len(visible_rows)},
                },
            )

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", state
        finally:
            server.shutdown()
            worker.join()


def seed_fixture(tenant_id: UUID, dataset_id: UUID, document_id: UUID) -> None:
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="edo-ontology-" + str(tenant_id)))
        db.flush()
        db.add(TenantMember(tenant_id=tenant_id, user_id=ACCOUNT, role="owner"))
        db.add(Dataset(id=dataset_id, tenant_id=tenant_id, name="维修制度", owner_id=ACCOUNT))
        db.flush()
        db.add(
            Document(
                id=document_id,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                owner_id=ACCOUNT,
                filename="SLA-2026-11",
                file_type="txt",
                file_size=len(SLA_TEXT),
                file_path="fixture-edo-sla.txt",
                status="completed",
                publication_status="published",
                doc_metadata={
                    "pipeline_hash": "edo-fixture-v1",
                    "active_pipeline_hash": "edo-fixture-v1",
                    "effective_at": "2026-11-01",
                    "expires_at": "2026-12-01",
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
                doc_metadata={"pipeline_hash": "edo-fixture-v1"},
            )
        )
        db.commit()


def definition() -> dict:
    model = maintenance_definition({"equipment": "edo:equipment", "work_orders": "edo:work_orders"})
    model["actions"] = {}
    model["document_metadata"] = {}
    for binding, table, mapping in zip(
        model["bindings"],
        EDO_TABLES,
        (
            {"equipment_id": "col_1", "name": "col_2"},
            {"order_id": "col_1", "equipment_id": "col_2", "due_at": "col_3", "status": "col_4"},
        ),
        strict=True,
    ):
        binding.update(
            edo_binding={
                "endpoint": "local_fixture",
                "ontology_id": "maintenance",
                "working_revision": 7,
                "table": table,
            },
            row_access_column=None,
            identity_columns=["col_1"],
            columns=mapping,
        )
    model["relation_bindings"]["order_for_equipment"] = {"source_columns": ["col_2"], "target_columns": ["col_1"]}
    return model


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edo-sql-runner", type=Path, required=True)
    args = parser.parse_args()
    assert settings.DATABASE_URL.endswith("/ontology_fixture"), "Load the isolated PostgreSQL ontology fixture"
    settings.AUTH_MODE = "header"
    tenant_id, dataset_id, document_id = uuid4(), uuid4(), uuid4()
    seed_fixture(tenant_id, dataset_id, document_id)
    headers = {"X-Tenant-ID": str(tenant_id), "X-User-ID": ACCOUNT, "X-EDO-Authorization": EDO_TOKEN}
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.include_router(get_router(), prefix="/api/v1")

    with edo_fixture(args.edo_sql_runner) as (endpoint, state), TestClient(app) as client:
        settings.ONTOLOGY_EDO_ENDPOINTS = {str(tenant_id): {"local_fixture": endpoint}}
        base = "/api/v1/kg/ontologies"

        def request(method: str, path: str, payload: dict | None = None):
            response = client.request(method, base + path, json=payload, headers=headers)
            assert response.is_success, (method, path, response.status_code, response.text[:800])
            return response.json()

        model = definition()
        previews = request("POST", "/binding-preview", model)
        assert all(not preview["issues"] and preview["edo"]["working_revision"] == 7 for preview in previews), previews
        assert {row["order_id"] for row in previews[1]["sample"]} == {"WO-01", "WO-02", "WO-03", "WO-04"}, previews
        workspace = request("POST", "", model)
        version = request("POST", f"/{workspace['id']}/versions", {"expected_revision": 1})
        prefix = f"/{workspace['id']}/versions/{version['id']}"
        extracted = request("POST", prefix + "/documents", {"document_id": str(document_id)})
        assert extracted["chunk_count"] == 1, extracted
        activated = request("PUT", prefix + f"/datasets/{dataset_id}")
        assert activated["version_id"] == version["id"], activated
        question = {
            "question": "设备 E-102 本月到期且现在逾期的工单有几张，依据哪版维修制度？引用对应原文。",
            "dataset_ids": [str(dataset_id)],
            "observed_at": "2026-11-23T12:00:00-08:00",
        }
        mixed = request("POST", prefix + "/ask", question)
        metric = mixed["metric"]
        assert metric and metric["value"] == 1 and metric["complete"], mixed
        evidence = metric["edo"]
        assert evidence["projection_id"] == "fixture-projection-7", evidence
        assert evidence["source_data_ids"] == ["fixture-work-orders"], evidence
        assert evidence["synced_at"] == SYNCED_AT, evidence
        [citation] = mixed["citations"]
        assert citation["filename"] == "SLA-2026-11" and citation["page"] == 3, mixed
        original = citation["evidence"]
        assert SLA_TEXT[original["start_char"] : original["end_char"]] == original["quote"]

        state.working_revision = 8
        sql_calls = state.sql_calls
        drifted = request("POST", prefix + "/ask", question)
        assert drifted["metric"] is None and any("待复核" in item for item in drifted["unavailable"]), drifted
        assert drifted["citations"] == mixed["citations"], drifted
        assert state.sql_calls == sql_calls
        print(
            json.dumps(
                {
                    "model": settings.LLM_MODEL,
                    "metric": 1,
                    "citation": "SLA-2026-11 p3",
                    "source": "isolated EDO HTTP contract with the EDO skill_sql.py runner",
                    "working_revision": 7,
                    "drifted_revision": 8,
                    "drift": "blocked structured reads and retained citation",
                    "result": "passed",
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
