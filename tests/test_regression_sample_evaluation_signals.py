from __future__ import annotations

from types import SimpleNamespace


def test_regression_sample_builder_emits_citation_and_hallucination_signals() -> None:
    from app.rag.evaluation.regression_sample_builder import build_regression_item_meta, build_regression_sample

    case = SimpleNamespace(
        expected_answer="Alpha is the approved policy.",
        reference_sources=[
            {
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "quote": "Alpha is the approved policy.",
            }
        ],
        extra={},
    )
    item = {
        "question": "What is the approved policy?",
        "response": 'Alpha is the approved policy. "Alpha is the approved policy."',
        "retrieved_contexts": ["Alpha is the approved policy."],
        "citations": [
            {
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "chunk_content": "Alpha is the approved policy.",
            }
        ],
    }

    sample_kwargs, meta = build_regression_sample(case, item)
    stored_meta = build_regression_item_meta(sample_kwargs=sample_kwargs, item_meta=meta)

    assert meta["citation_accuracy"] == 1.0
    assert meta["citation_coverage"] == 1.0
    assert meta["quote_verifiability"] == 1.0
    assert meta["atomic_faithfulness"] == 1.0
    assert meta["hallucination_rate"] == 0.0
    assert stored_meta["citation_accuracy"] == 1.0
    assert stored_meta["quote_verifiability"] == 1.0


def test_regression_sample_builder_scores_expected_metadata_from_plugin_golden_cases() -> None:
    from app.rag.evaluation.regression_sample_builder import build_regression_item_meta, build_regression_sample

    case = SimpleNamespace(
        expected_answer="Required materials: identity proof and signed form.",
        reference_sources=[
            {
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "quote": "Required materials: identity proof and signed form.",
            }
        ],
        extra={
            "source": "plugin_golden_draft",
            "expected_metadata": {
                "source_record_id": "record-1",
                "chunk_kind": "demo_materials",
            },
        },
    )
    item = {
        "question": "What materials does the demo record require?",
        "response": "Required materials include identity proof and a signed form.",
        "retrieved_contexts": ["Required materials: identity proof and signed form."],
        "citations": [
            {
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "metadata": {
                    "_evaluable_metadata": {
                        "source_record_id": "record-1",
                        "chunk_kind": "demo_materials",
                    }
                },
            }
        ],
    }

    sample_kwargs, meta = build_regression_sample(case, item)
    stored_meta = build_regression_item_meta(sample_kwargs=sample_kwargs, item_meta=meta)

    assert meta["expected_metadata_hit"] is True
    assert meta["expected_metadata_recall"] == 1.0
    assert meta["expected_metadata_fields_total"] == 2
    assert meta["expected_metadata_fields_matched"] == 2
    assert meta["expected_metadata_missing_keys"] == []
    assert stored_meta["expected_metadata_hit"] is True
    assert stored_meta["expected_metadata_recall"] == 1.0


def test_regression_sample_builder_counts_plugin_record_identity_recall() -> None:
    from app.rag.evaluation.regression_sample_builder import build_regression_sample

    record_identity = {
        "schema": "mimirq.record_identity.v1",
        "key": "knowledge_section=demo_section|source_record_id=record-1",
        "fields": {
            "knowledge_section": "demo_section",
            "source_record_id": "record-1",
        },
    }
    case = SimpleNamespace(
        expected_answer="Location: service desk.",
        reference_sources=[
            {
                "document_id": "doc-1",
                "chunk_id": "old-basic-chunk",
                "chunk_index": 0,
                "_record_identity": record_identity,
                "quote": "Record name: demo record\nLocation: service desk.",
            }
        ],
        extra={
            "expected_metadata": {
                "source_record_id": "record-1",
                "knowledge_section": "demo_section",
            }
        },
    )
    item = {
        "question": "Where is the demo record handled?",
        "response": "It is handled at the service desk.",
        "retrieved_contexts": ["Location: service desk."],
        "citations": [
            {
                "document_id": "doc-1",
                "chunk_id": "new-location-chunk",
                "chunk_index": 3,
                "chunk_content": "Location: service desk.",
                "metadata": {
                    "_record_identity": record_identity,
                    "_evaluable_metadata": {
                        "knowledge_section": "demo_section",
                        "source_record_id": "record-1",
                        "chunk_kind": "demo_location",
                    },
                },
            }
        ],
    }

    _sample_kwargs, meta = build_regression_sample(case, item)

    assert meta["retrieval_recall"] == 1.0
    assert meta["retrieval_hit_at_1"] is True
    assert meta["expected_metadata_hit"] is True


def test_regression_sample_builder_reports_missing_expected_metadata_keys() -> None:
    from app.rag.evaluation.regression_sample_builder import build_regression_sample

    case = SimpleNamespace(
        expected_answer=None,
        reference_sources=[{"document_id": "doc-1", "chunk_id": "chunk-1"}],
        extra={
            "expected_metadata": {
                "source_record_id": "record-1",
                "chunk_kind": "demo_materials",
            }
        },
    )
    item = {
        "question": "What materials does the demo record require?",
        "response": "",
        "retrieved_contexts": [],
        "citations": [
            {
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "metadata": {
                    "_indexed_metadata": {
                        "source_record_id": "record-1",
                        "chunk_kind": "wrong_section",
                    }
                },
            }
        ],
    }

    _sample_kwargs, meta = build_regression_sample(case, item)

    assert meta["expected_metadata_hit"] is False
    assert meta["expected_metadata_recall"] == 0.5
    assert meta["expected_metadata_missing_keys"] == ["chunk_kind"]


def test_regression_sample_builder_does_not_score_raw_business_metadata_without_plugin_views() -> None:
    from app.rag.evaluation.regression_sample_builder import build_regression_sample

    case = SimpleNamespace(
        expected_answer=None,
        reference_sources=[{"document_id": "doc-1", "chunk_id": "chunk-1"}],
        extra={
            "expected_metadata": {
                "source_record_id": "record-1",
                "chunk_kind": "demo_materials",
            }
        },
    )
    item = {
        "question": "What materials does the demo record require?",
        "response": "",
        "retrieved_contexts": [],
        "citations": [
            {
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "metadata": {
                    "source_record_id": "record-1",
                    "chunk_kind": "demo_materials",
                },
            }
        ],
    }

    _sample_kwargs, meta = build_regression_sample(case, item)

    assert meta["expected_metadata_hit"] is False
    assert meta["expected_metadata_recall"] == 0.0
    assert meta["expected_metadata_missing_keys"] == ["source_record_id", "chunk_kind"]
