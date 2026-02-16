from __future__ import annotations

from app.core.config import settings
from app.services.dataset_precheck_scan_runner import _is_local_scan_allowed_for_root


def test_precheck_internal_upload_scan_flag_allows_upload_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "LOCAL_SCAN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"), raising=False)

    root = tmp_path / "uploads" / "t1" / ".tmp" / "precheck_ingest"
    root.mkdir(parents=True, exist_ok=True)

    assert _is_local_scan_allowed_for_root(cfg={"internal_allow_upload_scan": True}, root=root) is True
    assert _is_local_scan_allowed_for_root(cfg={"internal_allow_upload_scan": False}, root=root) is False
    assert _is_local_scan_allowed_for_root(cfg={}, root=root) is False

    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    assert _is_local_scan_allowed_for_root(cfg={"internal_allow_upload_scan": True}, root=outside) is False


def test_precheck_local_scan_enabled_allows_any_root(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "LOCAL_SCAN_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"), raising=False)

    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    assert _is_local_scan_allowed_for_root(cfg={}, root=outside) is True

