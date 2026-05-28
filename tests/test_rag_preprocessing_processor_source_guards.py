import re
from pathlib import Path


def test_rag_preprocessing_processor_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/rag/preprocessing/processor.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
