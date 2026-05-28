import re
from pathlib import Path


def test_citations_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/rag/core/citations.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
