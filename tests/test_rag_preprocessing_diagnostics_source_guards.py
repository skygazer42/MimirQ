from pathlib import Path
import re


def test_rag_preprocessing_diagnostics_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/rag/preprocessing/diagnostics.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
