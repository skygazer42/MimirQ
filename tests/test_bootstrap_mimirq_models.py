import ast
import hashlib
from pathlib import Path

import pytest

from scripts import bootstrap_mimirq_models as bootstrap
from scripts.bootstrap_mimirq_models import verify_model_snapshot


def test_default_model_directory_matches_all_deepdoc_consumers() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = root / "app/rag/ingestion/parsing/resources/models"
    assert bootstrap.DEFAULT_MODEL_DIR == expected
    for module_name, constant, model_subdir in (
        ("ocr", "_OCR_MODEL_DIR", "ocr"),
        ("layout", "_LAYOUT_MODEL_DIR", "layout"),
        ("table_structure", "_TABLE_MODEL_DIR", "table"),
    ):
        module_path = root / f"app/rag/ingestion/parsing/models/{module_name}.py"
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        assignment = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == constant for target in node.targets)
        )
        actual = eval(
            compile(ast.Expression(assignment.value), str(module_path), "eval"),
            {"Path": Path, "__file__": str(module_path)},
        )
        assert actual == expected / model_subdir


def test_bootstrap_checks_the_downloaded_snapshot_without_loading_models(tmp_path, monkeypatch) -> None:
    def download(**kwargs):
        assert kwargs["repo_id"] == bootstrap.MODEL_REPO_ID
        assert kwargs["revision"] == bootstrap.MODEL_REVISION
        _write_manifest(kwargs["local_dir"], "ocr/det.onnx", b"fixture model bytes")

    monkeypatch.setattr(bootstrap, "snapshot_download", download)
    assert bootstrap.download_and_verify_models(tmp_path) == 1


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
