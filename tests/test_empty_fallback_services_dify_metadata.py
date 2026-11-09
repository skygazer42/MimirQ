import pytest

from app.services.dify_integration.common import _diagnostic_value_hash
from app.services.dify_integration.records import _record_dedupe_key
from app.services.dify_integration.tracing import _dify_trace_retrieval_queries


@pytest.mark.parametrize("value", [0, False])
def test_dify_explicit_record_identity_is_distinct_from_an_absent_identity(value):
    supplied = {"metadata": {"chunk_id": value}, "content": "body", "title": "title"}
    absent = {"metadata": {}, "content": "body", "title": "title"}
    assert _record_dedupe_key(supplied) != _record_dedupe_key(absent)


@pytest.mark.parametrize("value", [0, False])
def test_diagnostic_hash_keeps_real_scalar_values(value):
    assert _diagnostic_value_hash(value)
    assert _diagnostic_value_hash(value) != _diagnostic_value_hash(None)


def test_trace_measures_the_actual_provided_query_value():
    trace = _dify_trace_retrieval_queries(
        question="question", retrieval_path="path", retrieval_queries=[{"query": 0, "path": None}]
    )
    assert trace[0]["query_chars"] == 1


def test_absent_diagnostic_values_keep_the_existing_privacy_sentinel():
    assert _diagnostic_value_hash(None) == ""
