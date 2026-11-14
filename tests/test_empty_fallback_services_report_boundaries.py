import pytest

from app.services import report_html, report_service


@pytest.mark.parametrize("status", [None, 0, False])
def test_missing_or_invalid_audit_status_is_not_reported_as_a_passed_audit(status):
    assert report_service._retrieval_audit_next_action({}, status=status).startswith("Run a Golden")


def test_passed_audit_keeps_the_existing_next_action():
    assert report_service._retrieval_audit_next_action({}, status="passed").startswith("Retrieval audit passed")


def test_safe_report_payload_keeps_optional_audit_values_absent():
    safe = report_html._safe_retrieval_audit_payload(
        {"status": "unavailable", "gates": [{"name": "golden", "status": "unavailable"}]}
    )
    assert safe["kg_recommendation"] is None
    assert safe["recommended_next_action"] is None
    assert safe["gates"][0]["source"] is None
    assert safe["gates"][0]["generated_at"] is None


def test_connector_report_requires_the_status_emitted_by_its_builder():
    with pytest.raises(KeyError, match="status"):
        report_html._render_connector_runs_table([{"connector_id": "crawler", "created_at": None}])


def test_report_text_cell_renders_a_real_zero_value():
    rendered = report_html._render_chunk_targets_table([{"label": "Check", "status": "failed", "message": 0}])
    assert '<td class="v">0</td>' in rendered
