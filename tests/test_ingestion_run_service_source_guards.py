from pathlib import Path
import re


def test_ingestion_run_service_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/services/ingestion_run_service.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
