from pathlib import Path
import re


def test_artifact_normalizer_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/parsing/utils/artifact_normalizer.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
