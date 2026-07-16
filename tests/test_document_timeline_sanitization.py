from app.api.v1.document_timeline import _sanitize_timeline_details


def test_timeline_details_redact_sensitive_keys_recursively() -> None:
    details = {
        "status": "completed",
        "access_token": "top-level-secret",
        "nested": {"password": "nested-secret", "attempt": 2},
        "items": [{"api_key": "list-secret", "id": "safe"}],
        "too_deep": {"one": {"two": {"three": "hidden"}}},
    }

    assert _sanitize_timeline_details(details) == {
        "status": "completed",
        "nested": {"attempt": 2},
        "items": [{"id": "safe"}],
    }
