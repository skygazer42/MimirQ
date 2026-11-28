import sqlite3
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.infrastructure.config import settings
from app.rag.kg.enterprise_ontology import metrics
from app.rag.kg.enterprise_ontology.definition import OntologyDefinition, load_ontology_definition
from app.rag.kg.enterprise_ontology.metrics import MetricQuery, compile_snapshot_metric, evaluate_snapshot_metric
from tests.test_enterprise_ontology_definition import MAINTENANCE_YAML


def test_query_filters_authorized_rows_before_counting_business_ids():
    payload = load_ontology_definition(MAINTENANCE_YAML, format="yaml").model_dump(mode="json", by_alias=True)
    payload["bindings"][1]["row_access_column"] = "visible_to"
    payload["metrics"] = {
        "overdue": {
            "object_type": "work_order",
            "property": "order_id",
            "aggregate": "count_distinct",
            "time_property": "due_at",
            "allowed_filters": ["equipment_id"],
            "required_filters": {"status": "OPEN"},
            "before_observation": True,
        }
    }
    definition = OntologyDefinition.model_validate(payload)
    query = MetricQuery(
        filters={"equipment_id": "E-102"},
        start=datetime.fromisoformat("2026-11-01T00:00:00-07:00"),
        end=datetime.fromisoformat("2026-12-01T00:00:00-08:00"),
        observed_at=datetime.fromisoformat("2026-11-23T12:00:00-08:00"),
    )
    sql, parameters = compile_snapshot_metric(definition, "overdue", "sheet_0", query, account_id="reader")
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE sheet_0 (id TEXT, asset_id TEXT, deadline TEXT, state TEXT, visible_to TEXT)")
        db.executemany(
            "INSERT INTO sheet_0 VALUES (?, ?, ?, ?, ?)",
            [
                ("WO-01", "E-102", "2026-11-08T12:00:00-08:00", "OPEN", "reader"),
                ("WO-02", "E-102", "2026-11-10T12:00:00-08:00", "CLOSED", "reader"),
                ("WO-03", "E-102", "2026-11-29T12:00:00-08:00", "OPEN", "reader"),
                ("WO-04", "E-103", "2026-11-09T12:00:00-08:00", "OPEN", "reader"),
                ("WO-05", "E-102", "2026-11-09T12:00:00-08:00", "OPEN", "someone-else"),
            ],
        )
        assert db.execute(sql, parameters).fetchone() == (1,)


@pytest.fixture
def grouped_definition():
    payload = load_ontology_definition(MAINTENANCE_YAML, format="yaml").model_dump(mode="json", by_alias=True)
    payload["object_types"]["work_order"]["properties"]["factory_id"] = {"type": "string", "label": "工厂"}
    binding = payload["bindings"][1]
    binding["row_access_column"] = "visible_to"
    binding["columns"]["factory_id"] = {"column": "site", "values": {"n1": "NORTH", "n2": "NORTH", "s1": "SOUTH"}}
    payload["metrics"] = {
        "work_order_count": {
            "object_type": "work_order",
            "property": "order_id",
            "aggregate": "count_distinct",
            "required_filters": {"status": "OPEN"},
            "dimensions": ["factory_id", "status"],
        },
    }
    return OntologyDefinition.model_validate(payload)


def test_grouped_metric_aggregates_mapped_dimensions_after_row_scope(grouped_definition):
    query = MetricQuery(group_by=["factory_id", "status"])
    sql, parameters = compile_snapshot_metric(
        grouped_definition, "work_order_count", "sheet_0", query, account_id="reader"
    )
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE sheet_0 (id TEXT, site TEXT, state TEXT, visible_to TEXT)")
        db.executemany(
            "INSERT INTO sheet_0 VALUES (?, ?, ?, ?)",
            [
                ("WO-01", "n1", "OPEN", "reader"),
                ("WO-01", "n2", "OPEN", "reader"),
                ("WO-02", "s1", "OPEN", "reader"),
                ("WO-03", "n1", "CLOSED", "reader"),
                ("WO-04", "n2", "OPEN", "other"),
            ],
        )
        assert db.execute(sql, parameters).fetchall() == [("NORTH", "OPEN", 1), ("SOUTH", "OPEN", 1)]


def test_period_comparison_uses_the_same_metric_scope(grouped_definition, monkeypatch):
    payload = grouped_definition.model_dump(mode="json", by_alias=True)
    payload["metrics"]["work_order_count"]["time_property"] = "due_at"
    definition = OntologyDefinition.model_validate(payload)
    table = SimpleNamespace(table_id="table_1", sql_table="sheet_0", truncated=False)
    document = SimpleNamespace(dataset_id=uuid4(), updated_at=None)
    columns = {"id", "state", "visible_to", "deadline"}
    monkeypatch.setattr(metrics, "authorized_snapshot", lambda *_args, **_kwargs: (document, table, columns))
    windows = []
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE sheet_0 (id TEXT, state TEXT, visible_to TEXT, deadline TEXT)")
        db.executemany(
            "INSERT INTO sheet_0 VALUES (?, ?, ?, ?)",
            [
                ("WO-01", "OPEN", "reader", "2026-10-03T00:00:00Z"),
                ("WO-02", "OPEN", "reader", "2026-11-03T00:00:00Z"),
                ("WO-03", "OPEN", "reader", "2026-11-07T00:00:00Z"),
                ("WO-04", "OPEN", "other", "2026-11-04T00:00:00Z"),
                ("WO-05", "CLOSED", "reader", "2026-11-04T00:00:00Z"),
            ],
        )

        def select_rows(**kwargs):
            windows.append(kwargs["parameters"])
            return {"rows": db.execute(kwargs["sql"], kwargs["parameters"]).fetchall(), "truncated": False}

        monkeypatch.setattr(metrics, "run_table_query", select_rows)
        query = MetricQuery.model_validate(
            {
                "start": "2026-11-01T00:00:00Z",
                "end": "2026-12-01T00:00:00Z",
                "comparison": {"start": "2026-10-01T00:00:00Z", "end": "2026-11-01T00:00:00Z"},
            }
        )
        result = evaluate_snapshot_metric(
            None,
            definition=definition,
            metric_id="work_order_count",
            query=query,
            tenant_id=uuid4(),
            account_id="reader",
        )
    assert result.value == 2
    assert result.comparison.value == 1
    assert result.comparison.change == 1 and result.comparison.change_percent == 100
    assert len(windows) == 2 and all(tuple(args[:2]) == ("reader", "OPEN") for args in windows)


def test_grouped_metric_requires_a_declared_and_readable_dimension(grouped_definition, monkeypatch):
    tenant_id = uuid4()
    table = SimpleNamespace(table_id="table_1", sql_table="sheet_0", truncated=False)
    document = SimpleNamespace(dataset_id=uuid4(), updated_at=None)
    columns = {"id", "state", "visible_to"}
    monkeypatch.setattr(metrics, "authorized_snapshot", lambda *_args, **_kwargs: (document, table, columns))

    def unexpected_query(**_kwargs):
        pytest.fail("Unavailable grouping dimensions must fail before the query")

    monkeypatch.setattr(metrics, "run_table_query", unexpected_query)

    def evaluate(group_by):
        return evaluate_snapshot_metric(
            None,
            definition=grouped_definition,
            metric_id="work_order_count",
            query=MetricQuery(group_by=group_by),
            tenant_id=tenant_id,
            account_id="reader",
        )

    with pytest.raises(ValueError, match="declared"):
        evaluate(["equipment_id"])
    with pytest.raises(PermissionError):
        evaluate(["factory_id"])
    columns.add("site")
    monkeypatch.setattr(metrics, "run_table_query", lambda **_args: {"rows": [["NORTH", 1]], "truncated": False})
    result = evaluate(["factory_id"])
    assert result.complete and result.value is None
    [group] = result.groups
    assert group.dimensions == {"factory_id": "NORTH"}
    assert group.value == 1

    monkeypatch.setattr(metrics, "run_table_query", lambda **_args: {"rows": [], "truncated": False})
    empty = evaluate(["factory_id"])
    assert empty.groups == [] and empty.complete

    monkeypatch.setattr(settings, "TABLE_QUERY_MAX_ROWS", 2)

    def capped_query(**kwargs):
        assert kwargs["max_rows"] == 2
        return {"rows": [["NORTH", 1], ["SOUTH", 1]], "truncated": False}

    monkeypatch.setattr(metrics, "run_table_query", capped_query)
    capped = evaluate(["factory_id"])
    assert len(capped.groups) == 2 and not capped.complete and capped.reason == "group_limit_reached"


def test_derived_metric_reads_both_authorized_sources_and_marks_zero_denominator(grouped_definition, monkeypatch):
    payload = grouped_definition.model_dump(mode="json", by_alias=True)
    payload["metrics"].update(
        {
            "equipment_count": {"object_type": "equipment", "property": "equipment_id", "aggregate": "count_distinct"},
            "orders_per_device": {
                "object_type": "work_order",
                "property": "order_id",
                "aggregate": "count_distinct",
                "required_filters": {"status": "OPEN"},
                "formula": {"operation": "ratio", "metric": "equipment_count"},
            },
        }
    )
    definition = OntologyDefinition.model_validate(payload)
    table_values = {"work_orders": 6, "equipment": 3}
    sources = []

    def authorized(_db, *, asset_id, account_id, **_):
        assert account_id == "reader"
        name = asset_id.split(".")[-1]
        sources.append(name)
        document = SimpleNamespace(dataset_id=uuid4(), updated_at=None)
        table = SimpleNamespace(table_id=name, sql_table=name, truncated=False)
        return document, table, {"id", "state", "visible_to"}

    monkeypatch.setattr(metrics, "authorized_snapshot", authorized)
    monkeypatch.setattr(
        metrics,
        "run_table_query",
        lambda **kwargs: {
            "rows": [[table_values[kwargs["table_id"]]]],
            "truncated": False,
        },
    )

    def read_metric():
        return evaluate_snapshot_metric(
            None,
            definition=definition,
            metric_id="orders_per_device",
            query=MetricQuery(),
            tenant_id=uuid4(),
            account_id="reader",
        )

    result = read_metric()
    assert result.value == 2 and sources == ["work_orders", "equipment"]
    assert result.formula.reference_asset_id == "equipment" and result.formula.reference_value == 3
    table_values["equipment"] = 0
    result = read_metric()
    assert result.value is None and not result.complete and result.reason == "zero_formula_denominator"
