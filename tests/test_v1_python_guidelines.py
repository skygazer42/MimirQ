import asyncio
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException


class BrokenNumber:
    def __int__(self):
        raise RuntimeError("numeric implementation failed")

    def __float__(self):
        raise RuntimeError("numeric implementation failed")


@pytest.mark.parametrize(
    "module_name,helper_name",
    [
        ("app.api.v1.conversations.feedback", "_coerce_int"),
        ("app.rag.ingestion.parsing.utils.scalars", "coerce_int"),
        ("app.rag.ingestion.parsing.utils.scalars", "coerce_float"),
    ],
)
def test_numeric_input_boundary_does_not_swallow_implementation_failure(module_name, helper_name):
    helper = getattr(import_module(module_name), helper_name)
    with pytest.raises(RuntimeError, match="numeric implementation failed"):
        helper(BrokenNumber())


def test_lotus_masks_fail_closed(monkeypatch):
    from app.api.v1.datasets import tables as dataset_tables

    def fail_mask(*_args, **_kwargs):
        raise RuntimeError("FLS policy unavailable")

    monkeypatch.setattr(dataset_tables, "build_fls_column_mask_map", fail_mask)
    frame = SimpleNamespace(columns=["secret"])
    with pytest.raises(RuntimeError, match="FLS policy unavailable"):
        dataset_tables._apply_lotus_dataframe_fls(frame, fls_policy=object(), fls_ctx=object())


def test_lotus_schema_failure_does_not_fall_back_to_all_columns():
    from app.api.v1.datasets.tables import _lotus_select_query

    connection = MagicMock()
    connection.execute.side_effect = RuntimeError("table schema unavailable")
    with pytest.raises(RuntimeError, match="table schema unavailable"):
        _lotus_select_query(connection, sql_table_q='"table"', max_in_rows=10, max_in_cols=2)


@pytest.mark.parametrize(
    "module_name,helper_name",
    [
        ("app.api.v1.documents.preview", "_load_preview_metadata"),
        ("app.api.v1.documents.chunk_preview", "_resolve_preview_dataset_meta"),
    ],
)
def test_preview_keeps_selected_dataset_policy_failure_visible(monkeypatch, module_name, helper_name):
    module = import_module(module_name)

    def fail_lookup(*_args):
        raise RuntimeError("dataset policy unavailable")

    monkeypatch.setattr(module.dataset_service, "get_dataset", fail_lookup)
    monkeypatch.setattr(module.dataset_service, "ensure_member", lambda *_args: None)
    helper = getattr(module, helper_name)

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    if helper_name == "_load_preview_metadata":
        monkeypatch.setattr(module, "SessionLocal", Session)

    def load(dataset_id):
        scope = dict(tenant_id=uuid4(), account_id="member", dataset_id=dataset_id)
        return helper(**scope) if helper_name == "_load_preview_metadata" else helper(db=object(), **scope)

    with pytest.raises(RuntimeError, match="dataset policy unavailable"):
        load(str(uuid4()))
    assert load(None) == {}


def test_category_query_failure_is_not_a_successful_empty_tree(monkeypatch):
    from app.api.v1.datasets import categories as dataset_categories

    monkeypatch.setattr(
        dataset_categories.dataset_category_service.dataset_service, "ensure_member", lambda *_args: None
    )
    session = MagicMock()
    query = session.query.return_value
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.side_effect = RuntimeError("category count unavailable")
    with pytest.raises(RuntimeError, match="category count unavailable"):
        dataset_categories.list_dataset_categories(db=session, tenant_id=uuid4(), account_id="member")


def test_dataset_category_query_failure_does_not_remove_the_requested_filter():
    from app.api.v1.datasets.routes import _apply_dataset_category_filter

    session = MagicMock()
    session.query.return_value.filter.return_value.all.side_effect = RuntimeError("category lookup failed")
    with pytest.raises(RuntimeError, match="category lookup failed"):
        _apply_dataset_category_filter(
            MagicMock(), db=session, tenant_id=uuid4(), category_id=uuid4(), include_descendants=True
        )


def test_synthetic_cases_commit_failure_propagates_after_rollback(monkeypatch):
    from app.api.schemas.evaluation.regression import SyntheticHardcaseGenerateRequest
    from app.api.v1.evaluation import routes as evaluations

    monkeypatch.setattr(evaluations.settings, "KG_ENABLED", True)
    monkeypatch.setattr(evaluations.dataset_service, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(evaluations.dataset_service, "get_dataset", lambda *_args: object())
    monkeypatch.setattr(evaluations.dataset_service, "assert_dataset_writable", lambda *_args: None)
    monkeypatch.setattr(evaluations, "_validate_regression_case_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(evaluations, "_load_synthetic_base_cases", lambda *_args, **_kwargs: (0, []))
    monkeypatch.setattr(evaluations, "_load_existing_synthetic_question_keys", lambda *_args, **_kwargs: set())
    session = MagicMock()
    session.commit.side_effect = RuntimeError("synthetic commit unavailable")
    payload = SyntheticHardcaseGenerateRequest(dataset_id=uuid4(), dry_run=False)
    with pytest.raises(RuntimeError, match="synthetic commit unavailable"):
        evaluations.generate_synthetic_hardcases(payload=payload, db=session, tenant_id=uuid4(), account_id="member")
    session.rollback.assert_called_once()


@pytest.mark.parametrize("failure", [HTTPException(503, "lease unavailable"), asyncio.CancelledError()])
def test_dify_cache_preparation_failure_rejects_leader_and_cleans_up(monkeypatch, failure):
    from app.api.v1.integrations import dify as integrations_dify

    ctx = SimpleNamespace(
        dataset_ids=[],
        metadata_anchor_dataset_ids=[],
        distributed_singleflight_lease_task=None,
        distributed_singleflight_lease=None,
    )
    calls = []
    monkeypatch.setattr(integrations_dify, "_build_dify_external_retrieval_context", lambda **_kwargs: ctx)

    async def trace_worker(_func, **_kwargs):
        return None

    monkeypatch.setattr(integrations_dify, "run_blocking_call_with_managed_session", trace_worker)

    async def prepare(_ctx):
        raise failure

    async def cleanup(task, lease):
        assert task is None and lease is None
        calls.append("cleanup")

    monkeypatch.setattr(integrations_dify, "_maybe_return_cached_or_inflight_dify_response", prepare)
    monkeypatch.setattr(integrations_dify, "_cleanup_distributed_dify_response_lease", cleanup)
    monkeypatch.setattr(integrations_dify, "_reject_dify_inflight_response", lambda _ctx, _exc: calls.append("reject"))
    with pytest.raises(type(failure)):
        asyncio.run(integrations_dify._retrieve_external_knowledge(request=None, body=None, actor=None, db=None))
    assert calls == ["reject", "cleanup"]


def test_network_analysis_keeps_explicit_zero_edge_weight():
    from app.api.v1.knowledge_graph.network import EdgeIn, _adjacency

    graph = _adjacency([EdgeIn(source="a", target="b", weight=0.0)])
    assert graph["a"]["b"] == 0.0


@pytest.mark.parametrize("helper_name", ["_load_version_signatures", "_load_version_chunk_ids"])
@pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
def test_version_query_failure_is_not_retried_without_its_filter(helper_name, dialect):
    from app.api.v1.documents import versions as document_versions

    session = MagicMock()
    session.get_bind.return_value.dialect.name = dialect
    query = session.query.return_value
    query.filter.return_value = query
    query.add_columns.return_value = query
    query.execution_options.return_value = query
    query.enable_eagerloads.return_value = query
    query.all.side_effect = RuntimeError("version query unavailable")
    with pytest.raises(RuntimeError, match="version query unavailable"):
        getattr(document_versions, helper_name)(
            db=session, tenant_id=uuid4(), document_id=uuid4(), target_key="version"
        )
    session.query.assert_called_once()
