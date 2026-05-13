from pathlib import Path
import re


def test_ragas_service_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/rag/evaluation/ragas.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
