from __future__ import annotations

from pathlib import Path


def test_deepdoc_default_resource_paths_use_project_model_assets() -> None:
    from app.deepdoc.vision import layout_recognizer, ocr, table_structure_recognizer

    repo = Path.cwd().resolve()

    assert Path(ocr.get_default_resource_dir()).resolve() == repo / "app/deepdoc/resources/models/ocr"
    assert Path(layout_recognizer.get_default_resource_dir()).resolve() == repo / "app/deepdoc/resources/models/layout"
    assert Path(table_structure_recognizer.get_default_resource_dir()).resolve() == repo / "app/deepdoc/resources/models/table"


def test_deepdoc_ocr_model_path_resolves_nested_ppocr_assets() -> None:
    from app.deepdoc.vision.ocr import resolve_model_file_path

    model_dir = Path("app/deepdoc/resources/models/ocr").resolve()

    assert resolve_model_file_path(str(model_dir), "det").resolve() == model_dir / "PP-OCRv4/PP-OCRv4/ch_PP-OCRv4_det_infer.onnx"
    assert resolve_model_file_path(str(model_dir), "rec").resolve() == model_dir / "PP-OCRv4/PP-OCRv4/ch_PP-OCRv4_rec_infer.onnx"
