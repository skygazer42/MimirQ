import pytest

from app.services import table_tag_service as svc


def _single_table_columns() -> list[dict[str, str]]:
    return [
        {"name": "region", "dtype": "text"},
        {"name": "amount", "dtype": "integer"},
        {"name": "created_at", "dtype": "text"},
    ]


def _join_tables() -> list[dict[str, object]]:
    return [
        {
            "table_name": "orders",
            "columns": [
                {"name": "customer_id", "dtype": "integer"},
                {"name": "amount", "dtype": "numeric"},
            ],
            "row_count": 120,
            "sample_rows": [{"customer_id": 1, "amount": 10}],
        },
        {
            "table_name": "customers",
            "columns": [
                {"name": "id", "dtype": "integer"},
                {"name": "customer_name", "dtype": "text"},
                {"name": "region_id", "dtype": "integer"},
            ],
            "row_count": 20,
            "sample_rows": [{"id": 1, "customer_name": "Alice", "region_id": 9}],
        },
        {
            "table_name": "regions",
            "columns": [
                {"name": "id", "dtype": "integer"},
                {"name": "region_name", "dtype": "text"},
            ],
            "row_count": 5,
            "sample_rows": [{"id": 9, "region_name": "North"}],
        },
    ]


def test_quote_ident_escapes_embedded_quotes() -> None:
    assert svc._quote_ident('gross"amount') == '"gross""amount"'


def test_generate_deterministic_sql_preserves_filter_group_order_and_diagnostics() -> None:
    columns = [
        {"name": "amount", "dtype": "integer"},
        {"name": "region", "dtype": "text"},
        {"name": "created_at", "dtype": "text"},
    ]
    sql, planner = svc._generate_deterministic_sql_with_diagnostics(
        question='按 region 分组求 amount 的总和，region = "North" 前 7',
        sql_table="sales report",
        columns=columns,
        max_rows=20,
        sample_rows=[{"region": "North", "amount": 10}],
    )

    assert sql == (
        'SELECT "region", SUM("amount") AS total FROM "sales report" '
        'WHERE "region" = \'North\' GROUP BY "region" ORDER BY total DESC LIMIT 7'
    )
    assert planner == {
        "strategy": "deterministic_heuristic",
        "reason": "aggregation_group",
        "aggregation": "sum",
        "aggregation_column": "amount",
        "filter": {"column": "region", "operator": "=", "value": "North", "source": "explicit_predicate"},
        "group_by": "region",
        "order_by": {"column": "total", "direction": "desc"},
        "limit": 7,
        "selected_column": "amount",
    }


def test_generate_deterministic_sql_keeps_count_priority_over_sum() -> None:
    columns = [
        {"name": "amount", "dtype": "integer"},
        {"name": "region", "dtype": "text"},
        {"name": "created_at", "dtype": "text"},
    ]
    sql, planner = svc._generate_deterministic_sql_with_diagnostics(
        question="group by region count and sum amount",
        sql_table="sales",
        columns=columns,
        max_rows=20,
        sample_rows=None,
    )

    assert sql == (
        'SELECT "region", COUNT(*) AS count FROM "sales" '
        'GROUP BY "region" ORDER BY count DESC LIMIT 20'
    )
    assert planner["reason"] == "aggregation_group"
    assert planner["aggregation"] == "count"
    assert planner["aggregation_column"] is None
    assert planner["group_by"] == "region"
    assert planner["order_by"] == {"column": "count", "direction": "desc"}


def test_plan_join_query_prefers_multi_candidate_and_preserves_planner_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pair_candidate = {
        "candidate_id": "pair-1",
        "score": 0.8,
        "join": {
            "left_table": "orders",
            "left_column": "customer_id",
            "right_table": "customers",
            "right_column": "id",
            "left_row_count": 120,
            "right_row_count": 20,
        },
        "cost_signals": {
            "fanout_ratio": 2.0,
            "left_selectivity": 0.5,
            "right_selectivity": 0.25,
        },
    }
    multi_candidate = {
        "candidate_id": "multi-1",
        "score": 0.75,
        "selected_tables": ["orders", "customers", "regions"],
        "join": dict(pair_candidate["join"]),
        "joins": [
            dict(pair_candidate["join"]),
            {
                "left_table": "customers",
                "left_column": "region_id",
                "right_table": "regions",
                "right_column": "id",
            },
        ],
        "cost_signals": {
            "fanout_ratio": 2.0,
            "left_selectivity": 0.5,
            "right_selectivity": 0.25,
        },
    }

    monkeypatch.setattr(svc.settings, "TABLE_TAG_PLAN_CANDIDATES_TOP_N", 3, raising=False)
    monkeypatch.setattr(svc.settings, "TABLE_TAG_AMBIGUITY_SCORE_GAP", 0.03, raising=False)
    monkeypatch.setattr(svc.settings, "TABLE_TAG_AMBIGUITY_STRICT_ENABLED", True, raising=False)
    monkeypatch.setattr(svc.settings, "TABLE_QUERY_MAX_JOIN_TABLES", 4, raising=False)
    monkeypatch.setattr(svc.settings, "TABLE_TAG_PLAN_LOW_CONFIDENCE_THRESHOLD", 0.55, raising=False)
    monkeypatch.setattr(svc.settings, "TABLE_TAG_PLAN_LOW_CONFIDENCE_STRICT_ENABLED", False, raising=False)
    monkeypatch.setattr(
        svc,
        "score_join_plan_candidates",
        lambda **_kwargs: {
            "candidates": [pair_candidate],
            "selected": pair_candidate,
            "ambiguous": False,
            "ambiguity_gap": 0.02,
        },
        raising=True,
    )
    monkeypatch.setattr(
        svc,
        "score_multi_join_plan_candidates",
        lambda **_kwargs: {
            "candidates": [multi_candidate],
            "selected": multi_candidate,
            "ambiguous": False,
            "ambiguity_gap": 0.01,
        },
        raising=True,
    )
    monkeypatch.setattr(svc, "build_join_statistics_snapshot", lambda **_kwargs: {"snapshot": True}, raising=True)

    result = svc.plan_join_query_for_tables(
        question="sum amount by customer_name top 3",
        tables=_join_tables(),
        max_rows=10,
    )

    assert result["sql"] == (
        'SELECT t1."customer_name" AS "customer_name", SUM(t0."amount") AS total '
        'FROM "orders" AS t0 JOIN "customers" AS t1 ON t0."customer_id" = t1."id" '
        'GROUP BY t1."customer_name" ORDER BY total DESC LIMIT 3'
    )
    assert result["planner"]["planner_mode"] == "beam"
    assert result["planner"]["reason"] == "join_aggregation_group"
    assert result["planner"]["selected_tables"] == ["orders", "customers", "regions"]
    assert result["planner"]["selected_candidate_id"] == "multi-1"
    assert result["planner"]["aggregation"] == "sum"
    assert result["planner"]["aggregation_column"] == "amount"
    assert result["planner"]["group_by"] == {"table": "customers", "column": "customer_name"}
    assert result["planner"]["order_by"] == {"column": "total", "direction": "desc"}
    assert result["planner"]["strict_ambiguity"] is True
    assert result["planner"]["low_confidence"] is False
    assert result["planner"]["join_plan_risk"]["schema"] == "mimirq.tag_join_plan_risk.v1"
    assert result["planner"]["dry_run_cardinality"]["schema"] == "mimirq.tag_join_cardinality_dryrun.v1"
    assert result["planner"]["join_statistics_snapshot"] == {"snapshot": True}
    assert isinstance(result["planner"]["sql_fingerprint"], str)
    assert result["planner"]["sql_fingerprint"]


def test_plan_join_query_raises_ambiguous_join_plan_when_pairwise_choice_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = {
        "candidate_id": "pair-ambiguous",
        "score": 0.9,
        "join": {
            "left_table": "orders",
            "left_column": "customer_id",
            "right_table": "customers",
            "right_column": "id",
        },
    }

    monkeypatch.setattr(svc.settings, "TABLE_TAG_PLAN_CANDIDATES_TOP_N", 3, raising=False)
    monkeypatch.setattr(svc.settings, "TABLE_TAG_AMBIGUITY_SCORE_GAP", 0.03, raising=False)
    monkeypatch.setattr(svc.settings, "TABLE_TAG_AMBIGUITY_STRICT_ENABLED", True, raising=False)
    monkeypatch.setattr(svc.settings, "TABLE_QUERY_MAX_JOIN_TABLES", 4, raising=False)
    monkeypatch.setattr(svc.settings, "TABLE_TAG_PLAN_LOW_CONFIDENCE_STRICT_ENABLED", False, raising=False)
    monkeypatch.setattr(
        svc,
        "score_join_plan_candidates",
        lambda **_kwargs: {
            "candidates": [candidate],
            "selected": candidate,
            "ambiguous": True,
            "ambiguity_gap": 0.0,
        },
        raising=True,
    )
    monkeypatch.setattr(
        svc,
        "score_multi_join_plan_candidates",
        lambda **_kwargs: {"candidates": [], "selected": None, "ambiguous": False, "ambiguity_gap": None},
        raising=True,
    )

    with pytest.raises(ValueError, match="ambiguous_join_plan"):
        svc.plan_join_query_for_tables(question="show customers", tables=_join_tables()[:2], max_rows=10)


def test_plan_join_query_raises_low_confidence_join_plan_when_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = {
        "candidate_id": "pair-low-confidence",
        "score": 0.3,
        "join": {
            "left_table": "orders",
            "left_column": "customer_id",
            "right_table": "customers",
            "right_column": "id",
        },
    }

    monkeypatch.setattr(svc.settings, "TABLE_TAG_PLAN_CANDIDATES_TOP_N", 3, raising=False)
    monkeypatch.setattr(svc.settings, "TABLE_TAG_AMBIGUITY_SCORE_GAP", 0.03, raising=False)
    monkeypatch.setattr(svc.settings, "TABLE_TAG_AMBIGUITY_STRICT_ENABLED", True, raising=False)
    monkeypatch.setattr(svc.settings, "TABLE_QUERY_MAX_JOIN_TABLES", 4, raising=False)
    monkeypatch.setattr(svc.settings, "TABLE_TAG_PLAN_LOW_CONFIDENCE_THRESHOLD", 0.55, raising=False)
    monkeypatch.setattr(svc.settings, "TABLE_TAG_PLAN_LOW_CONFIDENCE_STRICT_ENABLED", True, raising=False)
    monkeypatch.setattr(
        svc,
        "score_join_plan_candidates",
        lambda **_kwargs: {
            "candidates": [candidate],
            "selected": candidate,
            "ambiguous": False,
            "ambiguity_gap": 0.02,
        },
        raising=True,
    )
    monkeypatch.setattr(
        svc,
        "score_multi_join_plan_candidates",
        lambda **_kwargs: {"candidates": [], "selected": None, "ambiguous": False, "ambiguity_gap": None},
        raising=True,
    )

    with pytest.raises(ValueError, match="low_confidence_join_plan"):
        svc.plan_join_query_for_tables(question="show customers", tables=_join_tables()[:2], max_rows=10)
