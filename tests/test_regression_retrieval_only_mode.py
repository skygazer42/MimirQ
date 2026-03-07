from __future__ import annotations

from uuid import UUID, uuid4

import pytest


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def order_by(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def limit(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def all(self):
        return list(self._result) if isinstance(self._result, list) else []

    def first(self):
        if isinstance(self._result, list):
            return self._result[0] if self._result else None
        return self._result

    def delete(self, synchronize_session=False):  # noqa: ANN001
        return 0


class _FakeDB:
    def __init__(self, *, run, cases):
        self._run = run
        self._cases = cases
        self.added = []

    def query(self, model):  # noqa: ANN001
        name = getattr(model, "__name__", str(model))
        if name == "RagasRegressionRun":
            return _FakeQuery(self._run)
        if name == "RagasRegressionCase":
            return _FakeQuery(self._cases)
        if name == "RagasRegressionItem":
            return _FakeQuery(None)
        raise AssertionError(f"unexpected model in query(): {name}")

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    def commit(self) -> None:
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
        self.updated_at = None
        self.dataset_id = None


def test_regression_eval_supports_retrieval_only_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.evaluation import ragas as mod

    run = _FakeRun()
    case = _FakeCase(case_id=uuid4(), question="What is MimirQ?")
    fake_db = _FakeDB(run=run, cases=[case])

    # No real DB; inject a fake session.
    monkeypatch.setattr(mod, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(mod.DatasetService, "ensure_member", lambda *args, **kwargs: None)

    # Keep case scoping deterministic.
    dataset_id = uuid4()
    monkeypatch.setattr(mod, "_resolve_case_scope", lambda **kwargs: ([], dataset_id))

    # We don't need real chunk materialization here; just ensure cases are evaluatable.
    monkeypatch.setattr(mod, "_extract_contexts", lambda **kwargs: ["ctx"])

    # Inject deterministic retrieval meta (no ragas needed).
    def _fake_build_regression_sample(_case, _eval_item):
        return {}, {"retrieval_recall": 1.0, "retrieval_hit_at_10": True, "retrieval_hit_at_20": True, "abstain_triggered": False}

    monkeypatch.setattr(mod, "build_regression_sample", _fake_build_regression_sample)

    # Retrieval-only path should not call generation runner.
    import app.rag.graph as rag_graph

    monkeypatch.setattr(rag_graph, "run_rag_graph", lambda **kwargs: (_ for _ in ()).throw(AssertionError("run_rag_graph called")))

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
        rag_params={},
    )

    assert run.status == "completed"
    assert run.metrics == []
    assert run.summary.get("retrieval_recall") == 1.0
    assert run.summary.get("retrieval_hit_at_10") == 1.0
    assert run.summary.get("retrieval_hit_at_20") == 1.0
    assert (run.params or {}).get("mode") == "retrieval_only"


def test_regression_eval_passes_extended_runtime_knobs_to_build_rag_state(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.evaluation import ragas as mod

    run = _FakeRun()
    case = _FakeCase(case_id=uuid4(), question="What is MimirQ?")
    fake_db = _FakeDB(run=run, cases=[case])

    monkeypatch.setattr(mod, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(mod.DatasetService, "ensure_member", lambda *args, **kwargs: None)

    dataset_id = uuid4()
    monkeypatch.setattr(mod, "_resolve_case_scope", lambda **kwargs: ([], dataset_id))
    monkeypatch.setattr(mod, "_extract_contexts", lambda **kwargs: ["ctx"])
    monkeypatch.setattr(
        mod,
        "build_regression_sample",
        lambda _case, _eval_item: ({}, {"retrieval_recall": 1.0, "retrieval_hit_at_20": True, "abstain_triggered": False}),
    )

    import app.rag.graph as rag_graph

    monkeypatch.setattr(rag_graph, "run_rag_graph", lambda **kwargs: (_ for _ in ()).throw(AssertionError("run_rag_graph called")))

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
    assert captured[0]["multi_query_temperature"] == 0.2
    assert captured[0]["multi_query_max_chars"] == 256
    assert captured[0]["enable_query_rewrite"] is True
    assert captured[0]["query_rewrite_strategy"] == "kb_followup.v2"
    assert captured[0]["query_rewrite_temperature"] == 0.3
    assert captured[0]["query_rewrite_max_chars"] == 180
    assert captured[0]["sparse_retrieval_enabled"] is True
    assert captured[0]["sparse_retrieval_provider"] == "splade"
    assert captured[0]["fusion_strategy"] == "weighted"
    assert captured[0]["fusion_budgets"] == {"vector": 20, "bm25": 10}
    assert captured[0]["fusion_min_scores"] == {"vector": 0.2}
    assert captured[0]["fusion_weights"] == {"vector": 0.7, "bm25": 0.3}
