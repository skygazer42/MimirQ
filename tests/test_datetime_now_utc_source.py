import re
from pathlib import Path


def test_app_code_does_not_use_naive_datetime_now() -> None:
    offenders: list[str] = []
    pattern = re.compile(r"\bdatetime\.now\(\s*\)")
    for path in Path("app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path}:{line_no}")

    assert offenders == []
