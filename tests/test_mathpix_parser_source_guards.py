from pathlib import Path


def test_mathpix_parser_no_longer_uses_requests_round_trips() -> None:
    text = Path("app/parsing/parsers/mathpix_parser.py").read_text(encoding="utf-8")
    assert "requests." not in text
