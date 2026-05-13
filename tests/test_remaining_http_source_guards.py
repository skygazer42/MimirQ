from pathlib import Path


def test_remaining_http_helpers_no_longer_use_requests_round_trips() -> None:
    for rel_path in (
        "app/deepdoc/parser/mineru_parser.py",
        "app/deepdoc/parser/tcadp_parser.py",
        "app/third_party/integrated_pipeline/chunkers/naive.py",
    ):
        text = Path(rel_path).read_text(encoding="utf-8")
        assert "requests." not in text, rel_path
