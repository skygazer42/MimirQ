from __future__ import annotations

from pathlib import Path

import pytest

from app.services.dataset_precheck_scan_runner import _iter_files


def test_precheck_iter_files_skips_symlink_files(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()

    ok = root / "ok.txt"
    ok.write_text("ok", encoding="utf-8")

    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")

    link = root / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink not supported on this platform")

    files = list(_iter_files(root, max_files=20))
    names = {p.name for p in files}
    assert "ok.txt" in names
    assert "link.txt" not in names

