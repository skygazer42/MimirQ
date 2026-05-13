from pathlib import Path


def test_vlm_correction_no_longer_uses_requests_round_trips() -> None:
    text = Path("app/parsing/processors/vlm_correction.py").read_text(encoding="utf-8")
    assert "requests." not in text
