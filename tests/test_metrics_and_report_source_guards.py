from pathlib import Path
import re


def test_metrics_and_report_services_no_longer_use_silent_pass_fallbacks() -> None:
    for rel_path in (
        "app/services/metrics_logger.py",
        "app/services/report_service.py",
    ):
        text = Path(rel_path).read_text(encoding="utf-8")
        assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None, rel_path
