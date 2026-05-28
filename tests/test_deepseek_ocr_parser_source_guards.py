import re
from pathlib import Path


def test_deepseek_ocr_parser_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/parsing/parsers/deepseek_ocr_parser.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
