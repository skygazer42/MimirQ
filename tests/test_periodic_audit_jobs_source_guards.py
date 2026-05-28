import re
from pathlib import Path


def test_periodic_audit_jobs_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/services/periodic_audit_jobs.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
