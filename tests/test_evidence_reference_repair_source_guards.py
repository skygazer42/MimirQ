import re
from pathlib import Path


def test_evidence_reference_repair_service_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/services/evidence_reference_repair_service.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
