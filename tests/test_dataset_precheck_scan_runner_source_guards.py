import re
from pathlib import Path


def test_dataset_precheck_scan_runner_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/services/dataset_precheck_scan_runner.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
