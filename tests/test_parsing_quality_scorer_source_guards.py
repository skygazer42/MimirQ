import re
from pathlib import Path


def test_parsing_quality_scorer_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/parsing/quality/scorer.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
