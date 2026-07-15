import hashlib

import pytest

from scripts.bootstrap_mimirq_models import verify_model_snapshot


def _write_manifest(model_dir, relative_name: str, payload: bytes) -> None:
    model_file = model_dir / relative_name
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_bytes(payload)
    checksum = hashlib.sha256(payload).hexdigest()
    (model_dir / "SHA256SUMS").write_text(f"{checksum}  {relative_name}\n", encoding="utf-8")


def test_verify_model_snapshot_accepts_matching_files(tmp_path) -> None:
    _write_manifest(tmp_path, "layout/layout.onnx", b"model")

    assert verify_model_snapshot(tmp_path) == 1


def test_verify_model_snapshot_rejects_tampered_files(tmp_path) -> None:
    _write_manifest(tmp_path, "layout/layout.onnx", b"model")
    (tmp_path / "layout" / "layout.onnx").write_bytes(b"tampered")

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        verify_model_snapshot(tmp_path)


def test_verify_model_snapshot_rejects_paths_outside_target(tmp_path) -> None:
    checksum = hashlib.sha256(b"model").hexdigest()
    (tmp_path / "SHA256SUMS").write_text(f"{checksum}  ../outside.onnx\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="escapes model directory"):
        verify_model_snapshot(tmp_path)
