from __future__ import annotations

from uuid import UUID, uuid4

import pytest


class _FakeQuery:
    def __init__(self, result):
        self._result = result
        self._limit = None
        self._order_by = []

    def filter(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def order_by(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self._order_by = [str(a) for a in args]
        return self

    def limit(self, *args, **kwargs):  # noqa: ANN002, ANN003
        if args:
            try:
                self._limit = int(args[0])
            except Exception:
                self._limit = None
        return self

    def all(self):
        if not isinstance(self._result, list):
            return []

        items = list(self._result)
        lowered = " ".join([str(x).lower() for x in (self._order_by or [])])
        if "updated_at" in lowered:
            def _ts(obj) -> float:
                raw = getattr(obj, "updated_at", None)
                if raw is None:
                    return 0.0
                if isinstance(raw, (int, float)):
                    return float(raw)
                try:
                    return float(raw.timestamp())
                except Exception:
                    return 0.0

            items.sort(key=_ts, reverse=True)
        elif ".id" in lowered or " id " in lowered:
            items.sort(key=lambda x: str(getattr(x, "id", "")))

        if self._limit is not None:
            items = items[: max(0, int(self._limit))]
        return items

    def first(self):
        if isinstance(self._result, list):
            return self._result[0] if self._result else None
        return self._result

    def delete(self, synchronize_session=False):  # noqa: ANN001
        return 0


class _FakeDB:
    def __init__(self, *, run, cases, document_rows=None, document_chunks=None):
        self._run = run
        self._cases = cases
        self._document_rows = list(document_rows or [])
        self._document_chunks = list(document_chunks or [])
        self.added = []
        self.commit_snapshots = []

    def query(self, *models):  # noqa: ANN002
        model = models[0] if models else None
        name = getattr(model, "__name__", str(model))
        if name == "RagasRegressionRun":
            return _FakeQuery(self._run)
        if name == "RagasRegressionCase":
            return _FakeQuery(self._cases)
        if name == "RagasRegressionItem":
            return _FakeQuery(None)
        if name == "DocumentChunk":
            return _FakeQuery(self._document_chunks)
        if any("Document." in str(model) for model in models):
            if models:
                width = max(1, len(models))
                rows = [
                    tuple(row[:width]) if isinstance(row, tuple) else row
                    for row in self._document_rows
                ]
                return _FakeQuery(rows)
            return _FakeQuery(self._document_rows)
        raise AssertionError(f"unexpected model in query(): {name}")

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    def commit(self) -> None:
        self.commit_snapshots.append(
            {
                "status": getattr(self._run, "status", None),
                "summary": dict(getattr(self._run, "summary", {}) or {}),
            }
        )
        return None

    def close(self) -> None:
        return None


class _FakeRun:
    def __init__(self):
        self.status = "pending"
        self.started_at = None
        self.finished_at = None
        self.metrics = ["faithfulness"]
        self.params = {}
        self.summary = {}
        self.error_message = None


class _FakeCase:
    def __init__(self, *, case_id: UUID, question: str):
        self.id = case_id
        self.question = question
        self.expected_answer = None
        self.reference_sources = []
        self.extra = {}
        self.updated_at = None
        self.dataset_id = None


class _FakeChunk:
    def __init__(self, *, chunk_id: UUID, document_id: UUID, content: str, doc_metadata: dict):
        self.id = chunk_id
        self.document_id = document_id
        self.content = content
        self.doc_metadata = doc_metadata


def test_regression_eval_supports_retrieval_only_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.evaluation import ragas as mod

    run = _FakeRun()
    case = _FakeCase(case_id=uuid4(), question="What is MimirQ?")
    fake_db = _FakeDB(run=run, cases=[case])

    # No real DB; inject a fake session.
    monkeypatch.setattr(mod, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(mod.DatasetService, "ensure_member", lambda *_args, **_kwargs: None)

    # Keep case scoping deterministic.
    dataset_id = uuid4()
    monkeypatch.setattr(mod, "_resolve_case_scope", lambda **_kwargs: ([], dataset_id))

    # We don't need real chunk materialization here; just ensure cases are evaluatable.
    monkeypatch.setattr(mod, "_extract_contexts", lambda **_kwargs: ["ctx"])

    # Inject deterministic retrieval meta (no ragas needed).
    def _fake_build_regression_sample(_case, _eval_item):
        assert _eval_item.get("citation_eval_limit") == 7
        return {}, {"retrieval_recall": 1.0, "retrieval_hit_at_10": True, "retrieval_hit_at_20": True, "abstain_triggered": False}

    monkeypatch.setattr(mod, "build_regression_sample", _fake_build_regression_sample)

    # Retrieval-only path should not call generation runner.
    import app.rag.graph as rag_graph

    monkeypatch.setattr(rag_graph, "run_rag_graph", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("run_rag_graph called")))

    # Stub out internal retrieval node so this test stays pure.
    import app.rag.pipelines.langgraph as langgraph

    monkeypatch.setattr(langgraph, "build_rag_state", lambda **kwargs: {"question": kwargs.get("question", "")})
    monkeypatch.setattr(langgraph, "_retrieve_node", lambda _state: {"citations": [{"chunk_id": str(uuid4())}], "metrics": {}})

    # If retrieval-only mode accidentally imports ragas, make it fail loudly.
    import builtins

    orig_import = builtins.__import__

    def _blocking_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        if name == "ragas" or str(name).startswith("ragas."):
            raise ImportError("blocked")
        return orig_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _blocking_import)

    mod.run_regression_ragas_evaluation(
        run_id=uuid4(),
        tenant_id=uuid4(),
        account_id="acct",
        case_ids=[case.id],
        dataset_id=dataset_id,
        metric_names=[],  # retrieval-only
        skip_empty_contexts=False,
        max_cases=10,
        rag_params={"top_k": 7},
    )

    assert run.status == "completed", run.error_message
    assert run.metrics == []
    assert run.summary.get("retrieval_recall") == pytest.approx(1.0)
    assert run.summary.get("retrieval_hit_at_10") == pytest.approx(1.0)
    assert run.summary.get("retrieval_hit_at_20") == pytest.approx(1.0)
    assert (run.params or {}).get("mode") == "retrieval_only"
    assert any(
        (snapshot.get("summary") or {}).get("progress") == {
            "mode": "retrieval_only",
            "processed_cases": 1,
            "total_cases": 1,
            "evaluable_items": 1,
            "percent": 1.0,
        }
        for snapshot in fake_db.commit_snapshots
    )


def test_regression_eval_retrieval_only_scores_plugin_expected_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.evaluation import ragas as mod

    run = _FakeRun()
    document_id = uuid4()
    chunk_id = uuid4()
    case = _FakeCase(case_id=uuid4(), question="Alpha onboarding requires what action?")
    case.expected_answer = "Complete identity proofing before activation."
    case.reference_sources = [
        {
            "document_id": str(document_id),
            "chunk_id": str(chunk_id),
            "quote": "Complete identity proofing before activation.",
        }
    ]
    case.extra = {
        "source": "plugin_golden_draft",
        "plugin_id": "demo-runtime-plugin",
        "plugin_ref": "plugin:demo-runtime-plugin@1.0.0:chunk",
        "expected_metadata": {
            "source_record_id": "record-1",
            "business_type": "demo_case",
            "chunk_kind": "demo_record_full",
        },
    }
    fake_db = _FakeDB(
        run=run,
        cases=[case],
        document_rows=[
            (
                document_id,
                "txt",
                "inherit",
                {"source_path": "fixtures/demo-runtime-records.txt"},
            )
        ],
    )

    monkeypatch.setattr(mod, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(mod.DatasetService, "ensure_member", lambda *_args, **_kwargs: None)

    dataset_id = uuid4()
    monkeypatch.setattr(mod, "_resolve_case_scope", lambda **_kwargs: ([], dataset_id))
    monkeypatch.setattr(mod, "_extract_contexts", lambda **_kwargs: ["Complete identity proofing before activation."])

    import app.rag.pipelines.langgraph as langgraph

    monkeypatch.setattr(langgraph, "build_rag_state", lambda **kwargs: {"question": kwargs.get("question", "")})
    monkeypatch.setattr(
        langgraph,
        "_retrieve_node",
        lambda _state: {
            "citations": [
                {
                    "document_id": str(document_id),
                    "chunk_id": str(chunk_id),
                    "metadata": {
                        "_evaluable_metadata": {
                            "source_record_id": "record-1",
                            "business_type": "demo_case",
                            "chunk_kind": "demo_record_full",
                        },
                    },
                }
            ],
            "metrics": {},
        },
    )

    mod.run_regression_ragas_evaluation(
        run_id=uuid4(),
        tenant_id=uuid4(),
        account_id="acct",
        case_ids=[case.id],
        dataset_id=dataset_id,
        metric_names=[],
        skip_empty_contexts=False,
        max_cases=10,
        rag_params={},
    )

    assert run.status == "completed", run.error_message
    assert run.summary["expected_metadata_hit_rate"] == pytest.approx(1.0)
    assert run.summary["expected_metadata_recall"] == pytest.approx(1.0)
    assert run.summary["expected_metadata_cases_total"] == 1
    assert run.summary["expected_metadata_fields_total"] == 3
    assert run.summary["expected_metadata_fields_matched"] == 3
    saved_items = [item for item in fake_db.added if getattr(item, "case_id", None) == case.id]
    assert len(saved_items) == 1
    assert saved_items[0].meta["expected_metadata_hit"] is True
    assert saved_items[0].meta["expected_metadata_missing_keys"] == []


def test_regression_eval_enriches_retrieved_chunk_metadata_for_plugin_expected_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.evaluation import ragas as mod

    run = _FakeRun()
    tenant_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()
    case = _FakeCase(case_id=uuid4(), question="Alpha onboarding requires what action?")
    case.expected_answer = "Complete identity proofing before activation."
    case.reference_sources = [
        {
            "document_id": str(document_id),
            "chunk_id": str(chunk_id),
            "quote": "Complete identity proofing before activation.",
        }
    ]
    case.extra = {
        "source": "plugin_golden_draft",
        "plugin_ref": "plugin:demo-runtime-plugin@1.0.0:chunk",
        "expected_metadata": {
            "source_record_id": "record-1",
            "business_type": "demo_case",
            "chunk_kind": "demo_record_full",
            "pipeline_hash": "hash-1",
        },
    }
    chunk = _FakeChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        content="Complete identity proofing before activation.",
        doc_metadata={
            "_evaluable_metadata": {
                "source_record_id": "record-1",
                "business_type": "demo_case",
                "chunk_kind": "demo_record_full",
            },
            "pipeline_hash": "hash-1",
            "plugin_private_fields": {
                "large_payload_that_should_not_be_required_for_scoring": ["x"] * 100,
            },
        },
    )
    dataset_id = uuid4()
    fake_db = _FakeDB(
        run=run,
        cases=[case],
        document_rows=[(document_id, dataset_id, "inherit", "acct")],
        document_chunks=[chunk],
    )

    monkeypatch.setattr(mod, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(mod.DatasetService, "ensure_member", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mod, "get_allowed_document_id_sets", lambda *_args, **_kwargs: ({document_id}, set()))

    monkeypatch.setattr(mod, "_resolve_case_scope", lambda **_kwargs: ([], dataset_id))

    import app.rag.pipelines.langgraph as langgraph

    monkeypatch.setattr(langgraph, "build_rag_state", lambda **kwargs: {"question": kwargs.get("question", "")})
    monkeypatch.setattr(
        langgraph,
        "_retrieve_node",
        lambda _state: {
            "citations": [
                {
                    "document_id": str(document_id),
                    "chunk_id": str(chunk_id),
                }
            ],
            "metrics": {},
        },
    )

    mod.run_regression_ragas_evaluation(
        run_id=uuid4(),
        tenant_id=tenant_id,
        account_id="acct",
        case_ids=[case.id],
        dataset_id=dataset_id,
        metric_names=[],
        skip_empty_contexts=False,
        max_cases=10,
        rag_params={},
    )

    assert run.status == "completed", run.error_message
    assert run.summary["expected_metadata_hit_rate"] == pytest.approx(1.0)
    assert run.summary["expected_metadata_recall"] == pytest.approx(1.0)
    assert run.summary["expected_metadata_fields_total"] == 4
    assert run.summary["expected_metadata_fields_matched"] == 4
    saved_items = [item for item in fake_db.added if getattr(item, "case_id", None) == case.id]
    assert len(saved_items) == 1
    saved_citation = saved_items[0].citations[0]
    assert saved_citation["metadata"]["source_record_id"] == "record-1"
    assert saved_citation["metadata"]["_evaluable_metadata"]["chunk_kind"] == "demo_record_full"
    assert "plugin_private_fields" not in saved_citation["metadata"]


def test_regression_eval_passes_extended_runtime_knobs_to_build_rag_state(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.evaluation import ragas as mod

    run = _FakeRun()
    case = _FakeCase(case_id=uuid4(), question="What is MimirQ?")
    fake_db = _FakeDB(run=run, cases=[case])

    monkeypatch.setattr(mod, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(mod.DatasetService, "ensure_member", lambda *_args, **_kwargs: None)

    dataset_id = uuid4()
    monkeypatch.setattr(mod, "_resolve_case_scope", lambda **_kwargs: ([], dataset_id))
    monkeypatch.setattr(mod, "_extract_contexts", lambda **_kwargs: ["ctx"])
    monkeypatch.setattr(
        mod,
        "build_regression_sample",
        lambda _case, _eval_item: ({}, {"retrieval_recall": 1.0, "retrieval_hit_at_20": True, "abstain_triggered": False}),
    )

    import app.rag.graph as rag_graph

    monkeypatch.setattr(rag_graph, "run_rag_graph", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("run_rag_graph called")))

    import app.rag.pipelines.langgraph as langgraph

    captured: list[dict] = []

    def _build_rag_state(**kwargs):  # noqa: ANN003
        captured.append(dict(kwargs))
        return {"question": kwargs.get("question", "")}

    monkeypatch.setattr(langgraph, "build_rag_state", _build_rag_state)
    monkeypatch.setattr(langgraph, "_retrieve_node", lambda _state: {"citations": [{"chunk_id": str(uuid4())}], "metrics": {}})

    mod.run_regression_ragas_evaluation(
        run_id=uuid4(),
        tenant_id=uuid4(),
        account_id="acct",
        case_ids=[case.id],
        dataset_id=dataset_id,
        metric_names=[],
        skip_empty_contexts=False,
        max_cases=10,
        rag_params={
            "retrieval_profile": "recall50",
            "enable_query_alias_expansion": True,
            "query_alias_max_queries": 5,
            "enable_multi_query": True,
            "multi_query_count": 3,
            "multi_query_temperature": 0.2,
            "multi_query_max_chars": 256,
            "enable_query_rewrite": True,
            "query_rewrite_strategy": "kb_followup.v2",
            "query_rewrite_temperature": 0.3,
            "query_rewrite_max_chars": 180,
            "enable_hierarchy_recall": True,
            "hierarchy_family_collapse": True,
            "hierarchy_family_aggregation": "combined",
            "hierarchy_tree_dedup": True,
            "hierarchy_parent_depth": 1,
            "hierarchy_sibling_window": 2,
            "hierarchy_overfetch_factor": 4,
            "sparse_retrieval_enabled": True,
            "sparse_retrieval_provider": "splade",
            "fusion_strategy": "weighted",
            "fusion_budgets": {"vector": 20, "bm25": 10},
            "fusion_min_scores": {"vector": 0.2},
            "fusion_weights": {"vector": 0.7, "bm25": 0.3},
        },
    )

    assert len(captured) == 1
    assert captured[0]["retrieval_profile"] == "recall50"
    assert captured[0]["enable_query_alias_expansion"] is True
    assert captured[0]["query_alias_max_queries"] == 5
    assert captured[0]["enable_multi_query"] is True
    assert captured[0]["multi_query_count"] == 3
    assert captured[0]["multi_query_temperature"] == pytest.approx(0.2)
    assert captured[0]["multi_query_max_chars"] == 256
    assert captured[0]["enable_query_rewrite"] is True
    assert captured[0]["query_rewrite_strategy"] == "kb_followup.v2"
    assert captured[0]["query_rewrite_temperature"] == pytest.approx(0.3)
    assert captured[0]["query_rewrite_max_chars"] == 180
    assert captured[0]["enable_hierarchy_recall"] is True
    assert captured[0]["hierarchy_family_collapse"] is True
    assert captured[0]["hierarchy_family_aggregation"] == "combined"
    assert captured[0]["hierarchy_tree_dedup"] is True
    assert captured[0]["hierarchy_parent_depth"] == 1
    assert captured[0]["hierarchy_sibling_window"] == 2
    assert captured[0]["hierarchy_overfetch_factor"] == 4
    assert captured[0]["sparse_retrieval_enabled"] is True
    assert captured[0]["sparse_retrieval_provider"] == "splade"
    assert captured[0]["fusion_strategy"] == "weighted"
    assert captured[0]["fusion_budgets"] == {"vector": 20, "bm25": 10}
    assert captured[0]["fusion_min_scores"] == {"vector": 0.2}
    assert captured[0]["fusion_weights"] == {"vector": 0.7, "bm25": 0.3}


def test_regression_eval_does_not_truncate_explicit_case_ids_and_orders_stably(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.evaluation import ragas as mod

    run = _FakeRun()
    # Intentionally pick UUIDs where lexicographic id order != caller-provided case_ids order.
    # The evaluator must preserve the explicit case_ids order to stay deterministic for CI/hourly runs.
    case_a = _FakeCase(case_id=UUID("00000000-0000-0000-0000-000000000002"), question="Case A")
    case_b = _FakeCase(case_id=UUID("00000000-0000-0000-0000-000000000001"), question="Case B")

    # Make updated_at ordering disagree with id ordering.
    case_a.updated_at = 1
    case_b.updated_at = 2

    # Intentionally provide cases in a non-id order; the evaluator must still preserve the
    # explicit case_ids order (not updated_at and not id sorting).
    fake_db = _FakeDB(run=run, cases=[case_b, case_a])
    monkeypatch.setattr(mod, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(mod.DatasetService, "ensure_member", lambda *_args, **_kwargs: None)

    dataset_id = uuid4()
    monkeypatch.setattr(mod, "_resolve_case_scope", lambda **_kwargs: ([], dataset_id))
    monkeypatch.setattr(mod, "_extract_contexts", lambda **_kwargs: ["ctx"])

    captured_case_ids: list[UUID] = []

    def _fake_build_regression_sample(_case, _eval_item):  # noqa: ANN001
        captured_case_ids.append(_case.id)
        return {}, {"retrieval_recall": 1.0, "retrieval_hit_at_20": True, "abstain_triggered": False}

    monkeypatch.setattr(mod, "build_regression_sample", _fake_build_regression_sample)

    import app.rag.graph as rag_graph

    monkeypatch.setattr(rag_graph, "run_rag_graph", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("run_rag_graph called")))

    import app.rag.pipelines.langgraph as langgraph

    monkeypatch.setattr(langgraph, "build_rag_state", lambda **kwargs: {"question": kwargs.get("question", "")})
    monkeypatch.setattr(langgraph, "_retrieve_node", lambda _state: {"citations": [{"chunk_id": str(uuid4())}], "metrics": {}})

    mod.run_regression_ragas_evaluation(
        run_id=uuid4(),
        tenant_id=uuid4(),
        account_id="acct",
        case_ids=[case_a.id, case_b.id],
        dataset_id=dataset_id,
        metric_names=[],  # retrieval-only
        skip_empty_contexts=False,
        max_cases=1,  # must not truncate explicit case_ids
        rag_params={},
    )

    assert run.status == "completed"
    assert captured_case_ids == [case_a.id, case_b.id]


def test_regression_eval_fails_when_explicit_case_ids_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    If callers provide explicit case_ids, the run must evaluate exactly that set.
    Missing ids should fail fast instead of silently evaluating a partial subset.
    """

    from app.rag.evaluation import ragas as mod

    run = _FakeRun()
    existing = _FakeCase(case_id=uuid4(), question="Existing case")
    missing = uuid4()

    fake_db = _FakeDB(run=run, cases=[existing])
    monkeypatch.setattr(mod, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(mod.DatasetService, "ensure_member", lambda *_args, **_kwargs: None)

    dataset_id = uuid4()
    monkeypatch.setattr(mod, "_resolve_case_scope", lambda **_kwargs: ([], dataset_id))
    monkeypatch.setattr(mod, "_extract_contexts", lambda **_kwargs: ["ctx"])
    monkeypatch.setattr(
        mod,
        "build_regression_sample",
        lambda _case, _eval_item: ({}, {"retrieval_recall": 1.0, "retrieval_hit_at_20": True, "abstain_triggered": False}),
    )

    import app.rag.pipelines.langgraph as langgraph

    monkeypatch.setattr(langgraph, "build_rag_state", lambda **kwargs: {"question": kwargs.get("question", "")})
    monkeypatch.setattr(langgraph, "_retrieve_node", lambda _state: {"citations": [{"chunk_id": str(uuid4())}], "metrics": {}})

    mod.run_regression_ragas_evaluation(
        run_id=uuid4(),
        tenant_id=uuid4(),
        account_id="acct",
        case_ids=[existing.id, missing],
        dataset_id=dataset_id,
        metric_names=[],
        skip_empty_contexts=False,
        max_cases=100,
        rag_params={},
    )

    assert run.status == "failed"
    assert run.error_message
