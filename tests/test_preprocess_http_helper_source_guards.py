from pathlib import Path


def test_preprocess_http_helpers_no_longer_use_requests_round_trips() -> None:
    for rel_path in (
        "app/parsing/preprocess/deskew.py",
        "app/parsing/preprocess/watermark.py",
        "app/parsing/preprocess/handwriting_cleanup.py",
    ):
        text = Path(rel_path).read_text(encoding="utf-8")
        assert "requests." not in text, rel_path
