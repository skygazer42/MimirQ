import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from langchain_core.documents import Document

from app.rag.retrieval.ranking import temporal
from app.services.documents import freshness


def _document(*, score=0.8):
    return Document(
        id=str(uuid4()),
        page_content="current policy",
        metadata={
            "document_id": str(uuid4()),
            "chunk_id": str(uuid4()),
            "score": score,
        },
    )


@pytest.mark.parametrize("field", ["tenant_id", "dataset_id"])
@pytest.mark.parametrize("invalid", ["invalid-scope", ""])
def test_invalid_timestamp_scope_is_rejected_before_querying(monkeypatch, field, invalid):
    calls = []
    monkeypatch.setattr(freshness, "_query_document_timestamp_rows", lambda **kwargs: calls.append(kwargs) or [])
    scope = {"tenant_id": uuid4(), "dataset_id": uuid4(), field: invalid}
    with pytest.raises(ValueError):
        freshness.fetch_document_updated_ts([str(uuid4())], **scope)
    assert calls == []


@pytest.mark.parametrize("failure", [TimeoutError("timestamp store unavailable"), asyncio.CancelledError()])
def test_timestamp_read_propagates_the_original_failure(monkeypatch, failure):
    def query(**kwargs):
        raise failure

    monkeypatch.setattr(freshness, "_query_document_timestamp_rows", query)
    with pytest.raises(type(failure)) as caught:
        freshness.fetch_document_updated_ts([str(uuid4())], tenant_id=uuid4(), dataset_id=uuid4())
    assert caught.value is failure


def test_timestamp_read_preserves_valid_scope_and_candidate_limit(monkeypatch):
    first, second, tenant, dataset = uuid4(), uuid4(), uuid4(), uuid4()
    created = datetime(2024, 1, 2, tzinfo=timezone.utc)
    calls = []

    def query(**kwargs):
        calls.append(kwargs)
        return [(first, None, created)]

    monkeypatch.setattr(freshness, "_query_document_timestamp_rows", query)
    result = freshness.fetch_document_updated_ts(
        [str(first), "invalid-document", str(first), str(second)],
        tenant_id=str(tenant),
        dataset_id=str(dataset),
        max_docs=1,
    )
    assert result == {str(first): created.timestamp()}
    assert calls == [{"tenant_uuid": tenant, "dataset_uuid": dataset, "doc_uuid_list": [first]}]


def test_corrupt_timestamp_row_is_not_reported_as_an_empty_success(monkeypatch):
    document_id = uuid4()
    monkeypatch.setattr(freshness, "_query_document_timestamp_rows", lambda **kwargs: [(document_id, "corrupt", None)])
    with pytest.raises(AttributeError):
        freshness.fetch_document_updated_ts([str(document_id)], tenant_id=uuid4())


@pytest.mark.parametrize("invalid_field", ["score", "timestamp"])
def test_invalid_recency_input_is_not_changed_to_zero_score_or_maximum_freshness(invalid_field):
    document = _document(score="invalid" if invalid_field == "score" else 0.8)
    timestamps = {document.metadata["document_id"]: "invalid" if invalid_field == "timestamp" else 1_700_000_000.0}
    with pytest.raises(ValueError):
        temporal.apply_recency_boost(
            [document],
            updated_ts_by_document_id=timestamps,
            boost_max=0.2,
            window_days=10,
            now_ts=1_700_000_000.0,
        )


def test_recency_ranking_keeps_ordering_limits_and_original_documents():
    now = 1_700_000_000.0
    old, recent, missing = _document(score=0.8), _document(score=0.75), _document(score=0.7)
    documents = [old, recent, missing]
    timestamps = {old.metadata["document_id"]: now - 20 * 86400, recent.metadata["document_id"]: now}
    ranked, metadata = temporal.apply_recency_boost(
        documents,
        updated_ts_by_document_id=timestamps,
        boost_max=0.2,
        window_days=10,
        now_ts=now,
    )
    assert ranked == [recent, old, missing]
    assert documents == [old, recent, missing]
    assert metadata["docs_with_ts"] == 2 and metadata["avg_boost"] == 0.066667
    assert metadata["max_boost"] == 0.2 and metadata["reordered"] is True


@pytest.mark.parametrize(
    "tenant,documents,limit", [(None, [str(uuid4())], 5), (uuid4(), [], 5), (uuid4(), [str(uuid4())], 0)]
)
def test_inapplicable_timestamp_reads_do_not_open_a_session(monkeypatch, tenant, documents, limit):
    def unexpected(**kwargs):
        pytest.fail("inapplicable timestamp read reached storage")

    monkeypatch.setattr(freshness, "_query_document_timestamp_rows", unexpected)
    assert freshness.fetch_document_updated_ts(documents, tenant_id=tenant, max_docs=limit) == {}


def test_root_keeps_candidates_and_reports_timestamp_storage_failure(monkeypatch, caplog):
    from app.infrastructure.config import settings
    from app.query import expand
    from app.rag.retrieval import orchestrator
    from app.rag.retrieval.stages import preparation

    for flag in (
        "ENABLE_QUERY_REWRITE",
        "ENABLE_MULTI_QUERY",
        "ENABLE_HYDE",
        "ENABLE_STEP_BACK_QUERY",
        "ENABLE_QUERY_DECOMPOSITION",
        "EVIDENCE_POST_RERANK_ENABLED",
        "KG_ENABLED",
        "KG_CHAT_ENABLED",
        "RETRIEVAL_LIGHTWEIGHT_SUBQUERY_ENABLED",
        "RAG_EVIDENCE_REQUIRE_SPANS_ENABLED",
    ):
        monkeypatch.setattr(settings, flag, False)
    monkeypatch.setattr(settings, "RAG_TEMPORAL_INTENT_ENABLED", True)
    monkeypatch.setattr(settings, "RAG_TEMPORAL_INTENT_RECENCY_BOOST_ENABLED", True)
    monkeypatch.setattr(expand, "load_base_dictionary_rules", lambda: {})
    failure = TimeoutError("timestamp read failed")

    def query(**kwargs):
        raise failure

    monkeypatch.setattr(freshness, "_query_document_timestamp_rows", query)
    document = _document()

    class Retriever:
        _last_debug_metrics = {}

        def model_copy(self, **kwargs):
            return self

        def invoke(self, query):
            return [document]

    monkeypatch.setattr(preparation, "hybrid_retriever", Retriever())
    with caplog.at_level(logging.DEBUG):
        result = orchestrator.run_retrieval(
            {
                "question": "latest policy",
                "tenant_id": uuid4(),
                "dataset_id": uuid4(),
                "history": [],
                "intent_router": False,
                "adaptive_router": False,
                "industry_rules_enabled": False,
                "enable_hierarchy_recall": False,
                "must_recall": False,
            }
        )
    assert [doc.id for doc in result["docs"]] == [document.id]
    metadata = result["query_debug"]["temporal_intent"]["recency_rerank"]
    assert metadata["used"] is False and metadata["reason"] == "exception:timestamp read failed"
    assert any(record.exc_info and record.exc_info[1] is failure for record in caplog.records)


@pytest.mark.asyncio
async def test_stream_records_timestamp_failure_without_erasing_successful_intent_detection(monkeypatch):
    from types import SimpleNamespace

    from app.infrastructure.config import settings
    from app.rag.runtime.streaming import evidence as standard_stream_evidence
    from app.rag.runtime.streaming.state import StandardStreamState

    class NoEngineHelpers:
        def __getattr__(self, name):
            raise AssertionError("temporal operation read an engine module helper: " + name)

    monkeypatch.setattr(settings, "RAG_TEMPORAL_INTENT_ENABLED", True)
    monkeypatch.setattr(settings, "RAG_TEMPORAL_INTENT_RECENCY_BOOST_ENABLED", True)
    failure = TimeoutError("timestamp read failed")

    def query(**kwargs):
        raise failure

    monkeypatch.setattr(freshness, "_query_document_timestamp_rows", query)
    failures = []
    monkeypatch.setattr(
        standard_stream_evidence,
        "logger",
        SimpleNamespace(debug=lambda _message, *, exc_info: failures.append(exc_info)),
    )
    document = _document()
    runtime = StandardStreamState(
        engine=NoEngineHelpers(),
        payload={
            "temporal_intent_enabled": True,
            "query_for_retrieval": "latest policy",
            "docs": [document],
            "tenant_id": uuid4(),
            "dataset_id": uuid4(),
            "temporal_intent_meta": {"detected": False, "reason_codes": []},
        },
    )
    await standard_stream_evidence.apply_temporal_rerank(runtime)
    assert runtime.data.docs == [document]
    assert runtime.data.temporal_intent_meta == {"detected": True, "reason_codes": ["keyword"]}
    assert runtime.data.temporal_recency_meta["reason"] == "exception"
    assert runtime.data.temporal_recency_meta["error"] == "timestamp read failed"
    assert len(failures) == 1
    assert isinstance(failures[0], TimeoutError)
    assert str(failures[0]) == str(failure)
