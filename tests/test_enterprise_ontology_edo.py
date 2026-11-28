import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

import httpx
import pytest
from sqlalchemy.orm import Session

from app.rag.kg.enterprise_ontology import edo_source
from app.rag.kg.enterprise_ontology.definition import OntologyDefinition, load_ontology_definition
from app.rag.kg.enterprise_ontology.edo_source import EdoSourceError, authorized_edo_table, edo_authorization
from app.rag.kg.enterprise_ontology.metrics import MetricQuery, evaluate_snapshot_metric
from app.rag.kg.enterprise_ontology.snapshots import preview_bindings
from tests.test_enterprise_ontology_definition import MAINTENANCE_YAML

TENANT_ID = UUID("60ffe107-e674-4107-b15b-5b2343905a4e")
SYNCED_AT = "2026-11-23T20:00:00Z"
COLUMNS = {"col_1": "STRING", "col_2": "STRING", "col_3": "DATETIME", "col_4": "STRING"}
ORDERS = [
    ("WO-01", "E-102", "2026-11-08T20:00:00Z", "PENDING"),
    ("WO-02", "E-102", "2026-11-10T20:00:00Z", "CLOSED"),
    ("WO-03", "E-102", "2026-11-29T20:00:00Z", "PENDING"),
    ("WO-04", "E-103", "2026-11-09T20:00:00Z", "PENDING"),
    ("WO-05", "E-102", "2026-11-09T20:00:00Z", "PENDING"),
]


@dataclass
class EdoContract:
    revision: int = 7
    columns: dict[str, str] = field(default_factory=lambda: COLUMNS.copy())
    requests: list[httpx.Request] = field(default_factory=list)
    sql_revision_conflict: bool = False
    reason: str | None = None
    truncate_result: bool = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.host == "edo.test"
        assert request.url.path.startswith("/api/ontology/workspaces/maintenance/capabilities/")
        auth = request.headers["Authorization"]
        assert auth in {"reader-token", "manager-token"}
        if request.method == "GET":
            assert request.url.path.endswith("/skill")
            if request.url.params["expectedWorkingRevision"] != str(self.revision):
                return self.revision_conflict()
            return self.success(
                {
                    "workingRevision": self.revision,
                    "files": [],
                    "tables": [
                        {
                            "name": "obj_1",
                            "kind": "OBJECT",
                            "columns": [{"name": name, "type": kind} for name, kind in self.columns.items()],
                        }
                    ],
                }
            )
        assert request.method == "POST" and request.url.path.endswith("/sql")
        payload = json.loads(request.content)
        assert payload["expectedWorkingRevision"] == self.revision
        [table] = payload["tables"]
        assert table["table"] == "obj_1"
        assert set(table["columns"]) <= self.columns.keys()
        if self.sql_revision_conflict:
            return self.revision_conflict()
        if self.reason is not None:
            return self.success(
                {
                    "requestId": "failed-request",
                    "status": "unsupported",
                    "reasonCode": self.reason,
                    "workingRevision": self.revision,
                    "projectionId": None,
                    "syncedAt": None,
                    "sourceDataIds": [],
                    "returnedCount": 0,
                    "truncated": False,
                    "data": {},
                }
            )
        visible = ORDERS[:-1] if auth == "reader-token" else ORDERS
        positions = [list(COLUMNS).index(column) for column in table["columns"]]
        fields = ", ".join(f"{column} TEXT" for column in table["columns"])
        placeholders = ", ".join("?" for _ in positions)
        with sqlite3.connect(":memory:") as db:
            db.execute(f"CREATE TABLE obj_1 ({fields})")
            db.executemany(
                f"INSERT INTO obj_1 VALUES ({placeholders})", (tuple(row[i] for i in positions) for row in visible)
            )
            db.execute("PRAGMA query_only = ON")
            cursor = db.execute(payload["sql"])
            columns = [column[0] for column in cursor.description]
            rows = [dict(zip(columns, row, strict=True)) for row in cursor]
        return self.success(
            {
                "requestId": "edo-request",
                "status": "partial" if self.truncate_result else ("success" if rows else "empty"),
                "reasonCode": "RESULT_TRUNCATED" if self.truncate_result else None,
                "workingRevision": self.revision,
                "projectionId": "projection-7",
                "syncedAt": SYNCED_AT,
                "sourceDataIds": ["maintenance-rows"],
                "returnedCount": len(rows),
                "truncated": self.truncate_result,
                "data": {
                    "columns": columns,
                    "rows": rows,
                    "tablesRead": ["obj_1"],
                    "truncated": False,
                    "loadedRowCount": len(visible),
                    "table": "obj_1",
                },
            }
        )

    @staticmethod
    def success(data: dict) -> httpx.Response:
        return httpx.Response(200, json={"code": "10000", "success": True, "data": data})

    @staticmethod
    def revision_conflict() -> httpx.Response:
        return httpx.Response(409, json={"code": "40000", "subCode": "ONTOLOGY_REVISION_CONFLICT", "success": False})


@pytest.fixture
def edo(monkeypatch) -> EdoContract:
    contract = EdoContract()
    client = httpx.Client
    monkeypatch.setattr(
        edo_source.httpx, "Client", lambda **options: client(transport=httpx.MockTransport(contract), **options)
    )
    monkeypatch.setattr(edo_source.settings, "ONTOLOGY_EDO_ENDPOINTS", {str(TENANT_ID): {"main": "https://edo.test"}})
    return contract


@pytest.fixture
def definition() -> OntologyDefinition:
    payload = load_ontology_definition(MAINTENANCE_YAML, format="yaml").model_dump(mode="json", by_alias=True)
    source = payload["bindings"][1]
    source.update(
        asset_id="edo:maintenance:work_orders",
        edo_binding={"endpoint": "main", "ontology_id": "maintenance", "working_revision": 7, "table": "obj_1"},
        identity_columns=["col_1"],
        columns={
            "order_id": "col_1",
            "equipment_id": "col_2",
            "due_at": "col_3",
            "status": {"column": "col_4", "values": {"PENDING": "OPEN"}},
        },
    )
    payload["bindings"] = [source]
    payload["relation_bindings"] = {}
    payload["metrics"] = {
        "overdue": {
            "object_type": "work_order",
            "property": "order_id",
            "aggregate": "count_distinct",
            "time_property": "due_at",
            "allowed_filters": ["equipment_id"],
            "required_filters": {"status": "OPEN"},
            "before_observation": True,
        },
    }
    return OntologyDefinition.model_validate(payload)


@pytest.fixture
def query() -> MetricQuery:
    return MetricQuery(
        filters={"equipment_id": "E-102"},
        start=datetime.fromisoformat("2026-11-01T00:00:00-07:00"),
        end=datetime.fromisoformat("2026-12-01T00:00:00-08:00"),
        observed_at=datetime.fromisoformat("2026-11-23T12:00:00-08:00"),
    )


def metric(definition, query, token="reader-token"):
    with Session() as db, edo_authorization(token):
        return evaluate_snapshot_metric(
            db,
            definition=definition,
            metric_id="overdue",
            query=query,
            tenant_id=TENANT_ID,
            account_id="reader",
        )


def test_edo_reads_under_the_current_callers_authorization(edo, definition, query):
    reader = metric(definition, query)
    manager = metric(definition, query, "manager-token")
    assert reader.value == 1 and manager.value == 2
    assert reader.complete and manager.complete
    assert reader.source_updated_at == datetime.fromisoformat(SYNCED_AT)
    assert reader.edo.projection_id == "projection-7"
    assert reader.edo.source_data_ids == ["maintenance-rows"]
    assert reader.edo.working_revision == 7
    assert len(edo.requests) == 4
    with pytest.raises(EdoSourceError, match="edo_authorization_required"):
        authorized_edo_table(tenant_id=TENANT_ID, binding=definition.bindings[0])
    with edo_authorization("reader-token"), pytest.raises(EdoSourceError, match="edo_endpoint_unavailable"):
        authorized_edo_table(tenant_id=UUID(int=0), binding=definition.bindings[0])
    assert len(edo.requests) == 4


def test_edo_metric_carries_partial_results_and_does_not_invent_counts(edo, definition, query):
    edo.truncate_result = True
    result = metric(definition, query)
    assert result.value == 1
    assert not result.complete and result.reason == "RESULT_TRUNCATED"
    assert result.edo.status == "partial"
    edo.reason = "SKILL_DATA_LIMIT"
    result = metric(definition, query)
    assert result.value is None
    assert not result.complete and result.reason == "SKILL_DATA_LIMIT"


@pytest.mark.parametrize("during_sql", [False, True])
def test_edo_revision_drift_requires_review(edo, definition, query, during_sql):
    if during_sql:
        edo.sql_revision_conflict = True
    else:
        edo.revision = 8
    with pytest.raises(EdoSourceError, match="edo_revision_drift") as error:
        metric(definition, query)
    assert error.value.status_code == 409
    with Session() as db, edo_authorization("reader-token"):
        [preview] = preview_bindings(db, tenant_id=TENANT_ID, account_id="reader", definition=definition)
    assert [issue.code for issue in preview.issues] == ["edo_revision_drift"]


def test_edo_binding_preview_checks_skill_contract_and_does_not_post_invalid_columns(edo, definition):
    with Session() as db, edo_authorization("reader-token"):
        [preview] = preview_bindings(db, tenant_id=TENANT_ID, account_id="reader", definition=definition)
        assert preview.issues == []
        assert preview.row_count == 4
        assert preview.edo.projection_id == "projection-7"
        assert [row["order_id"] for row in preview.sample] == ["WO-01", "WO-02", "WO-03", "WO-04"]
        assert preview.sample[0]["status"] == "OPEN"
        edo.columns["col_3"] = "STRING"
        del edo.columns["col_4"]
        [preview] = preview_bindings(db, tenant_id=TENANT_ID, account_id="reader", definition=definition)
    assert {(issue.code, issue.field) for issue in preview.issues} == {
        ("edo_column_type_mismatch", "due_at"),
        ("unavailable_column", "col_4"),
    }
    assert edo.requests[-1].method == "GET"


def test_edo_known_coverage_and_historical_state(edo, definition, query):
    definition.bindings[0].coverage_start = datetime.fromisoformat("2026-11-03T00:00:00Z")
    result = metric(definition, query)
    assert result.value == 1 and not result.complete
    assert result.reason == "source_window_incomplete"
    query.historical_state = True
    result = metric(definition, query)
    assert result.value is None and not result.complete
    assert result.reason == "historical_state_unavailable"
    assert edo.requests[-1].method == "GET"


def test_edo_quotes_filter_values_and_rejects_invalid_filters_before_query(edo, definition, query):
    query.filters["equipment_id"] = "O'Brien?"
    assert metric(definition, query).value == 0
    query.filters["status"] = "WRONG"
    calls = len(edo.requests)
    with pytest.raises(ValueError, match="outside its declared scope"):
        metric(definition, query)
    assert len(edo.requests) == calls
