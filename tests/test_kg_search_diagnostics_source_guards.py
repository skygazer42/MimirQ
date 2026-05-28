import re
from pathlib import Path


def test_kg_search_diagnostics_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/rag/evaluation/kg_search_diagnostics.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
