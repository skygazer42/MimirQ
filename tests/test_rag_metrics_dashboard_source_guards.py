from pathlib import Path
import re


def test_rag_metrics_dashboard_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/services/rag_metrics_dashboard.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
