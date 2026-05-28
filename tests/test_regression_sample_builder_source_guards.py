import re
from pathlib import Path


def test_regression_sample_builder_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/rag/evaluation/regression_sample_builder.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
