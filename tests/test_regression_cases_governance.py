from __future__ import annotations

from pathlib import Path


def _window_after(text: str, *, needle: str, max_lines: int = 120) -> str:
    """
    Return a bounded source window starting at the first line containing `needle`.

    This is intentionally simple: the governance contract should be obvious in the endpoint body.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if needle in line:
            return "\n".join(lines[i : i + max_lines])
    raise AssertionError(f"Failed to locate needle: {needle}")


def test_regression_cases_write_ops_require_dataset_writable() -> None:
    """
    Wave21-T085 governance: writing regression cases (which back golden questions) must be
    protected by dataset-writable checks.
    """
    src = Path("app/api/v1/evaluations.py").read_text(encoding="utf-8")

    create_block = _window_after(src, needle="async def create_ragas_regression_case", max_lines=140)
    assert "assert_dataset_writable" in create_block

    patch_block = _window_after(src, needle="async def patch_ragas_regression_case", max_lines=160)
    assert "assert_dataset_writable" in patch_block

    delete_block = _window_after(src, needle="async def delete_ragas_regression_case", max_lines=120)
    assert "assert_dataset_writable" in delete_block
