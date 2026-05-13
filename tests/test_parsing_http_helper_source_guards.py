from pathlib import Path


def test_parsing_http_helpers_no_longer_use_requests_round_trips() -> None:
    for rel_path in (
        "app/parsing/enrich/chart_to_data.py",
        "app/parsing/enrich/formula_ocr.py",
        "app/parsing/enrich/vlm_image_caption.py",
    ):
        text = Path(rel_path).read_text(encoding="utf-8")
        assert "requests." not in text, rel_path
