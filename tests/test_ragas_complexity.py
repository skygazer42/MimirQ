
import datetime as _datetime
import sys
from datetime import timezone
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest

if not hasattr(_datetime, "UTC"):
    _datetime.UTC = timezone.utc

import app.rag.evaluation.ragas as ragas_module
from app.rag.pipeline_plugins.contracts import DISPLAY_METADATA_KEY


class _ListQuery:
    def __init__(self, rows: list[object], events: list[str] | None = None) -> None:
        self._rows = rows
        self._events = events

    def filter(self, *_args: object, **_kwargs: object) -> "_ListQuery":
        return self

    def order_by(self, *_args: object, **_kwargs: object) -> "_ListQuery":
        return self

    def limit(self, _limit: int) -> "_ListQuery":
        return self

    def distinct(self) -> "_ListQuery":
        return self

    def all(self) -> list[object]:
        return list(self._rows)

    def first(self) -> object | None:
        return self._rows[0] if self._rows else None

    def delete(self, *, synchronize_session: bool) -> None:
        assert synchronize_session is False
        if self._events is not None:
            self._events.append("delete")


class _ContextDB:
    def __init__(self, *, chunks: list[object], dataset_rows: list[tuple[object, object]]) -> None:
        self._chunks = chunks
        self._dataset_rows = dataset_rows

    def query(self, *args: object) -> _ListQuery:
        if args and args[0] is ragas_module.DocumentChunk:
            return _ListQuery(self._chunks)
        if len(args) == 2 and args[0] is ragas_module.DBDocument.id:
            return _ListQuery(list(self._dataset_rows))
        raise AssertionError(f"unexpected query args: {args!r}")


class _RunDB:
    def __init__(self, run: object, *, item_model: object) -> None:
        self._run = run
        self._item_model = item_model
        self.added: list[object] = []
        self.events: list[str] = []

    def query(self, model: object) -> _ListQuery:
        if model is self._item_model:
            return _ListQuery([], self.events)
        if model is ragas_module.RagasEvaluationRun or model is ragas_module.RagasRegressionRun:
            return _ListQuery([self._run], self.events)
        raise AssertionError(f"unexpected model query: {model!r}")

    def add(self, row: object) -> None:
        self.added.append(row)
        self.events.append("add")

    def commit(self) -> None:
        self.events.append("commit")

    def close(self) -> None:
        self.events.append("close")


def test_build_selected_deterministic_scores_keeps_bool_aliases_and_fallbacks() -> None:
    scores = ragas_module.build_selected_deterministic_scores(
        [
            "refusal_correctness",
            "multihop_chain_hit_rate",
            "expected_metadata_hit_rate",
            "atomic_faithfulness",
            "hallucination_rate",
            "citation_accuracy",
        ],
        {
            "refusal_correct": True,
            "multihop_chain_hit": False,
            "expected_metadata_hit": True,
            "faithfulness_det": 0.75,
            "citation_accuracy": 0.9,
        },
    )

    assert scores == {
        "refusal_correctness": 1.0,
        "multihop_chain_hit_rate": 0.0,
        "expected_metadata_hit_rate": 1.0,
        "atomic_faithfulness": 0.75,
        "hallucination_rate": 0.25,
        "citation_accuracy": 0.9,
    }


def test_extract_contexts_enforces_allowed_documents_and_dataset_scope() -> None:
    tenant_id = uuid4()
    allowed_document_id = uuid4()
    filtered_document_id = uuid4()
    dataset_id = uuid4()
    other_dataset_id = uuid4()
    allowed_chunk_id = uuid4()
    filtered_chunk_id = uuid4()
    db = _ContextDB(
        chunks=[
            SimpleNamespace(id=allowed_chunk_id, document_id=allowed_document_id, content="allowed chunk text"),
            SimpleNamespace(id=filtered_chunk_id, document_id=filtered_document_id, content="filtered chunk text"),
        ],
        dataset_rows=[
            (allowed_document_id, dataset_id),
            (filtered_document_id, other_dataset_id),
        ],
    )

    contexts = ragas_module._extract_contexts(
        db=db,
        tenant_id=tenant_id,
        account_id="acct-1",
        citations=[
            {"chunk_id": str(allowed_chunk_id), "document_id": str(allowed_document_id)},
            {"document_id": str(allowed_document_id), "text": "fallback evidence"},
            {"chunk_id": str(filtered_chunk_id), "document_id": str(filtered_document_id)},
            {"chunk_id": str(allowed_chunk_id), "document_id": str(allowed_document_id)},
            {"text": "no document id should fail closed"},
        ],
        allowed_document_ids=[allowed_document_id, filtered_document_id],
        dataset_id=dataset_id,
    )

    assert contexts == ["allowed chunk text", "fallback evidence"]


def test_enrich_citations_with_chunk_metadata_uses_dataset_scope_and_preserves_existing_values() -> None:
    tenant_id = uuid4()
    allowed_document_id = uuid4()
    filtered_document_id = uuid4()
    dataset_id = uuid4()
    other_dataset_id = uuid4()
    allowed_chunk_id = uuid4()
    filtered_chunk_id = uuid4()
    db = _ContextDB(
        chunks=[
            SimpleNamespace(
                id=allowed_chunk_id,
                document_id=allowed_document_id,
                doc_metadata={
                    DISPLAY_METADATA_KEY: {"title": "Allowed title"},
                    "pipeline_hash": "from-chunk",
                },
            ),
            SimpleNamespace(
                id=filtered_chunk_id,
                document_id=filtered_document_id,
                doc_metadata={DISPLAY_METADATA_KEY: {"title": "Filtered title"}},
            ),
        ],
        dataset_rows=[
            (allowed_document_id, dataset_id),
            (filtered_document_id, other_dataset_id),
        ],
    )

    enriched = ragas_module._enrich_citations_with_chunk_metadata(
        db=db,
        tenant_id=tenant_id,
        citations=[
            {
                "chunk_id": str(allowed_chunk_id),
                "metadata": {"pipeline_hash": "existing", "keep": True},
            },
            {
                "chunk_id": str(filtered_chunk_id),
                "metadata": {"filtered": True},
            },
        ],
        allowed_document_ids=[],
        dataset_id=dataset_id,
    )

    assert enriched[0]["metadata"]["title"] == "Allowed title"
    assert enriched[0]["metadata"]["pipeline_hash"] == "existing"
    assert enriched[0]["metadata"]["keep"] is True
    assert enriched[1] == {
        "chunk_id": str(filtered_chunk_id),
        "metadata": {"filtered": True},
    }


def test_resolve_metrics_uses_aliases_defaults_and_rejects_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_metrics = ModuleType("ragas.metrics")

    class _Metric:
        def __init__(self, *, name: str, strictness: int | None = None) -> None:
            self.name = name
            self.strictness = strictness

    fake_metrics.Faithfulness = lambda: _Metric(name="faithfulness")
    fake_metrics.ResponseRelevancy = lambda strictness: _Metric(name="response_relevancy", strictness=strictness)
    fake_metrics.AnswerSimilarity = lambda: _Metric(name="answer_similarity")
    fake_metrics.AnswerCorrectness = lambda: _Metric(name="answer_correctness")
    fake_metrics.ContextRecall = lambda: _Metric(name="context_recall")
    fake_metrics.ContextPrecision = lambda: _Metric(name="context_precision")
    fake_metrics.IDBasedContextRecall = lambda: _Metric(name="id_based_context_recall")
    fake_metrics.IDBasedContextPrecision = lambda: _Metric(name="id_based_context_precision")
    fake_metrics.LLMContextPrecisionWithoutReference = lambda: _Metric(
        name="llm_context_precision_without_reference"
    )
    monkeypatch.setitem(sys.modules, "ragas.metrics", fake_metrics)
    monkeypatch.setattr(ragas_module, "_resolve_response_relevancy_strictness", lambda: 7)

    default_metrics = ragas_module._resolve_metrics([])
    alias_metric = ragas_module._resolve_metrics(["answer_relevancy"])[0]

    assert [metric.name for metric in default_metrics] == ["faithfulness", "response_relevancy"]
    assert alias_metric.name == "response_relevancy"
    assert alias_metric.strictness == 7

    with pytest.raises(ValueError, match="Unsupported RAGAS metric: nope"):
        ragas_module._resolve_metrics(["nope"])


def test_run_conversation_ragas_evaluation_timeout_falls_back_to_deterministic_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    conversation_id = uuid4()
    run = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        status="queued",
        started_at=None,
        finished_at=None,
        error_message="old",
        metrics=None,
        params=None,
        summary=None,
    )
    db = _RunDB(run, item_model=ragas_module.RagasEvaluationItem)
    monkeypatch.setattr(ragas_module, "SessionLocal", lambda: db, raising=True)
    monkeypatch.setattr(ragas_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(
        ragas_module,
        "_load_conversation_for_evaluation",
        lambda *_a, **_k: (SimpleNamespace(id=conversation_id), []),
        raising=True,
    )
    monkeypatch.setattr(
        ragas_module,
        "_build_conversation_eval_items",
        lambda *_a, **_k: [
            {
                "turn_index": 1,
                "user_message_id": uuid4(),
                "assistant_message_id": uuid4(),
                "user_input": "Question",
                "response": "Answer",
                "retrieved_contexts": ["ctx"],
                "citations": [],
            }
        ],
        raising=True,
    )
    monkeypatch.setattr(
        ragas_module,
        "_should_use_conversation_deterministic_eval",
        lambda _metrics: False,
        raising=True,
    )
    monkeypatch.setattr(
        ragas_module,
        "_run_conversation_ragas",
        lambda **_kwargs: (_ for _ in ()).throw(TimeoutError("boom")),
        raising=True,
    )

    ragas_module.run_conversation_ragas_evaluation(
        run_id=run.id,
        tenant_id=tenant_id,
        account_id="acct-1",
        conversation_id=conversation_id,
        metric_names=["faithfulness"],
        max_turns=5,
        skip_empty_contexts=False,
    )

    assert run.status == "completed"
    assert run.summary["mode"] == "deterministic_conversation"
    assert run.summary["ragas_skipped_reason"] == "ragas_wall_timeout"
    assert run.summary["ragas_attempted"] is True
    assert run.summary["ragas_fallback_error"] == "boom"
    assert run.summary["total_tokens"] is None
    assert run.summary["eval_llm_tokens_input"] is None
    assert run.summary["eval_estimated_cost_usd"] is None
    assert run.params["ragas_attempted"] is True
    assert db.events.count("commit") == 2
    assert len(db.added) == 1


def test_persist_retrieval_only_regression_result_sets_progress_and_zero_eval_costs() -> None:
    tenant_id = uuid4()
    run = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        status="running",
        metrics=None,
        params={"existing": True},
        summary=None,
        finished_at=None,
    )
    db = _RunDB(run, item_model=ragas_module.RagasRegressionItem)

    ragas_module._persist_retrieval_only_regression_result(
        db=db,
        run=run,
        run_id=run.id,
        tenant_id=tenant_id,
        eval_items=[
            {
                "case_id": uuid4(),
                "question": "What happened?",
                "response": "",
                "retrieved_contexts": ["ctx"],
                "citations": [{"chunk_id": "c1"}],
                "sample_kwargs": {"user_input": "What happened?"},
                "item_meta": {"retrieval_recall": 1.0},
            }
        ],
        skip_empty_contexts=True,
        max_cases=10,
        rag_params={"top_k": 5},
        llm_judge_summary={},
        total_cases=3,
    )

    assert run.status == "completed"
    assert run.metrics == []
    assert run.params["mode"] == "retrieval_only"
    assert run.summary["progress"] == {
        "mode": "retrieval_only",
        "processed_cases": 3,
        "total_cases": 3,
        "evaluable_items": 1,
        "percent": 1.0,
    }
    assert run.summary["eval_llm_tokens_input"] == 0
    assert run.summary["eval_llm_tokens_output"] == 0
    assert run.summary["eval_estimated_cost_usd"] == 0.0
    assert len(db.added) == 1
