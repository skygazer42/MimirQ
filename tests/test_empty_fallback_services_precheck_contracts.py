from uuid import uuid4

import pytest

from app.services.dataset_precheck_classification import classify_parse_failure_kind
from app.services.dataset_precheck_diff import diff_precheck_summaries
from app.services.dataset_precheck_ingestion_suggestion import _extract_suggestion_signals
from app.services.dataset_precheck_scan_runner import _load_jsonl_records_by_name
from app.services.dataset_profile_service import _collapse_ws


def test_scan_record_missing_required_name_is_not_silently_discarded(tmp_path):
    records = tmp_path / "records.jsonl"
    records.write_text('{"file_type": "txt"}\n', encoding="utf-8")
    with pytest.raises(KeyError, match="name"):
        _load_jsonl_records_by_name(records)


def test_suggestion_missing_finding_identity_does_not_become_blank():
    with pytest.raises(KeyError, match="key"):
        _extract_suggestion_signals({"findings": [{"count": 1}]})


def test_summary_diff_missing_finding_identity_does_not_silently_discard_the_finding():
    with pytest.raises(KeyError, match="key"):
        diff_precheck_summaries(
            base_scan_run_id=uuid4(),
            target_scan_run_id=uuid4(),
            base_summary={"findings": [{"count": 1}]},
            target_summary={},
        )


@pytest.mark.parametrize("message", [0, False])
def test_provided_invalid_parse_error_is_not_reported_as_an_unknown_failure(message):
    with pytest.raises(AttributeError):
        classify_parse_failure_kind(file_type="txt", error_message=message)


def test_required_redacted_text_does_not_become_a_blank_preview():
    with pytest.raises(AttributeError):
        _collapse_ws(None)


def test_parse_error_without_message_keeps_the_existing_unknown_category():
    assert classify_parse_failure_kind(file_type="txt", error_message=None) == "other_parse_failure"
    assert classify_parse_failure_kind(file_type="doc", error_message=None) == "legacy_format"
