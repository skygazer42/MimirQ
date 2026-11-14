import pytest
from langchain_core.documents import Document

from app.rag.retrieval.hybrid.text_preparation import normalize_document_questions
from app.rag.retrieval.orchestration.citation_quality import _citation_coverage_lists, _parse_quality_low_sample
from app.rag.retrieval.orchestration.finalize_trace import _per_query_trace, _retrieval_variant_counts
from app.rag.retrieval.orchestration.hierarchy import _resolve_hierarchy_parent_key


def test_question_metadata_preserves_provided_falsy_scalars_and_valid_siblings():
    assert normalize_document_questions([None, 0, False, "Valid?"]) == ["0", "False", "Valid?"]


def test_citation_diagnostics_preserve_a_zero_document_identifier():
    assert _citation_coverage_lists([{"document_id": 0}])[1] == ["0"]


def test_parse_quality_diagnostics_keep_absent_identifiers_as_none():
    sample = _parse_quality_low_sample(Document(page_content="Content"), rank=1, score=0.2)
    assert sample["document_id"] is None
    assert sample["chunk_id"] is None


def test_explicit_root_parent_and_zero_parent_have_distinct_meanings():
    assert _resolve_hierarchy_parent_key({"hierarchy_parent_key": None, "parent_id": "legacy"}) is None
    assert _resolve_hierarchy_parent_key({"hierarchy_parent_key": 0}) == "0"


def test_trace_does_not_turn_broken_internal_kinds_into_main_or_empty_history():
    with pytest.raises((AttributeError, TypeError)):
        _retrieval_variant_counts([(None, "question", None)])
    with pytest.raises(KeyError):
        _per_query_trace([{"ok": True}])
