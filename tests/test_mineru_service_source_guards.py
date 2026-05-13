from pathlib import Path


def test_mineru_service_no_longer_uses_requests_round_trips() -> None:
    text = Path("app/services/mineru_service.py").read_text(encoding="utf-8")
    assert "requests." not in text
