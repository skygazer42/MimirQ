import pytest

from app.services.dify_integration import common, records


def test_dify_response_metadata_condition_matches_real_zero_values():
    assert common._response_hint_metadata_conditions_match({"count": 0}, {"when_metadata": {"count": 0}})
    assert not common._response_hint_metadata_conditions_match({}, {"when_metadata": {"count": 0}})


def test_dify_deduplication_requires_the_content_written_by_record_producers():
    with pytest.raises(KeyError, match="content"):
        records._record_dedupe_key({"title": "Document", "metadata": {}})
