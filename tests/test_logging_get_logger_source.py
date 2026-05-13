from __future__ import annotations

import re
from pathlib import Path


def test_app_code_uses_project_get_logger_instead_of_module_getlogger() -> None:
    offenders: list[str] = []
    pattern = re.compile(r"\blogging\.getLogger\(__name__\)")

    for path in Path("app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path}:{line_no}")

    assert offenders == []
