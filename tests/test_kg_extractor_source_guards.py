from pathlib import Path
import re


def test_kg_extractor_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/rag/kg/extraction/extractor.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
