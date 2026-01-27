from __future__ import annotations

from pathlib import Path

import pytest

from app.services.path_safety import resolve_under_base


def test_resolve_under_base_allows_in_base(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    inside = base / "a.txt"
    inside.write_text("ok", encoding="utf-8")
    assert resolve_under_base(inside, base=base) is not None


def test_resolve_under_base_blocks_outside(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    assert resolve_under_base(outside, base=base) is None


def test_resolve_under_base_blocks_symlink_escape(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")

    link = base / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink not supported on this platform")

    assert resolve_under_base(link, base=base) is None

