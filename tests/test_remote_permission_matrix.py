from __future__ import annotations

from scripts.remote_permission_matrix import build_case_result, status_matches_expected


def test_remote_permission_matrix_status_matches_expected() -> None:
    assert status_matches_expected(200, [200]) is True
    assert status_matches_expected(403, [401, 403]) is True
    assert status_matches_expected(404, [401, 403]) is False


def test_remote_permission_matrix_build_case_result_marks_failure_outside_expected() -> None:
    result = build_case_result("outsider_settings", status=404, body={"detail": "nope"}, elapsed=0.123, expected_statuses=[401, 403])

    assert result["name"] == "outsider_settings"
    assert result["ok"] is False
    assert result["status_code"] == 404
    assert "response" in result
