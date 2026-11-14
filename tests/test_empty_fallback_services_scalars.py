from functools import partial

import pytest

from app.services import evidence_feedback_materialization, hardcase_discovery_service, indexer, lineage_service, report_service


@pytest.mark.parametrize("normalize", [
    evidence_feedback_materialization._safe_text,
    hardcase_discovery_service._safe_str,
    lineage_service._safe_str,
    report_service._safe_report_text,
    partial(indexer._coerce_short_text, max_chars=32),
])
def test_optional_scalar_text_preserves_zero_and_actual_absence(normalize):
    assert normalize(0) == "0"
    assert normalize(None) is None


def test_retrieval_metadata_prefix_keeps_a_zero_keyword():
    text, fields = indexer._build_retrieval_metadata_prefix({"keywords": [0]})
    assert "0" in text
    assert "keywords" in fields


def test_safe_report_lists_keep_zero_entries():
    assert report_service._safe_report_list([0, None]) == ["0"]
