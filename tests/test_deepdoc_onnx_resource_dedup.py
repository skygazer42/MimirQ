from __future__ import annotations

import hashlib
import subprocess
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_TRACKED_ONNX = {
    "app/deepdoc/resources/data_parser/qieci/det.onnx",
    "app/deepdoc/resources/data_parser/qieci/layout.onnx",
    "app/deepdoc/resources/data_parser/qieci/rec.onnx",
    "app/deepdoc/resources/data_parser/qieci/tsr.onnx",
    "app/deepdoc/resources/models/hf_onnx/ocr_pipeline__paddleocr_onnx__monkt__paddleocr-onnx/detection/v5/det.onnx",
    "app/deepdoc/resources/models/hf_onnx/ocr_pipeline__paddleocr_onnx__monkt__paddleocr-onnx/languages/chinese/rec.onnx",
    "app/deepdoc/resources/models/hf_onnx/ocr_pipeline__paddleocr_onnx__monkt__paddleocr-onnx/preprocessing/doc-orientation/PP-LCNet_x1_0_doc_ori.onnx",
    "app/deepdoc/resources/models/hf_onnx/ocr_pipeline__paddleocr_onnx__monkt__paddleocr-onnx/preprocessing/doc-unwarping/UVDoc.onnx",
    "app/deepdoc/resources/models/hf_onnx/ocr_pipeline__paddleocr_onnx__monkt__paddleocr-onnx/preprocessing/textline-orientation/PP-LCNet_x1_0_textline_ori.onnx",
    "app/deepdoc/resources/models/hf_onnx/table_structure__tatr_v1_1_all__microsoft__table-transformer-structure-recognition-v1.1-all/model.onnx",
    "app/deepdoc/resources/models/layout/layout.onnx",
    "app/deepdoc/resources/models/ocr/PP-OCRv4/PP-OCRv4/ch_PP-OCRv4_det_infer.onnx",
    "app/deepdoc/resources/models/ocr/PP-OCRv4/PP-OCRv4/ch_PP-OCRv4_rec_infer.onnx",
    "app/deepdoc/resources/models/ocr/det.onnx",
    "app/deepdoc/resources/models/ocr/rec.onnx",
    "app/deepdoc/resources/models/seal/trocr_seal_384/decoder_model.onnx",
    "app/deepdoc/resources/models/seal/trocr_seal_384/encoder_model.onnx",
    "app/deepdoc/resources/models/table/tsr.onnx",
}

EXPECTED_SYMLINKS = {
    "app/deepdoc/resources/data_parser/qieci/det.onnx": "../../models/ocr/det.onnx",
    "app/deepdoc/resources/data_parser/qieci/layout.onnx": "../../models/layout/layout.onnx",
    "app/deepdoc/resources/data_parser/qieci/rec.onnx": "../../models/ocr/rec.onnx",
    "app/deepdoc/resources/data_parser/qieci/tsr.onnx": "../../models/table/tsr.onnx",
    "app/deepdoc/resources/models/ocr/det.onnx": "PP-OCRv4/PP-OCRv4/ch_PP-OCRv4_det_infer.onnx",
    "app/deepdoc/resources/models/ocr/rec.onnx": "PP-OCRv4/PP-OCRv4/ch_PP-OCRv4_rec_infer.onnx",
}


def _tracked_onnx_entries() -> dict[str, str]:
    output = subprocess.check_output(
        ["git", "ls-files", "-s", "*.onnx"],
        cwd=REPO_ROOT,
        text=True,
    )
    entries: dict[str, str] = {}
    for line in output.splitlines():
        mode, _object_id, _stage, path = line.split(maxsplit=3)
        entries[path] = mode
    return entries


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_deepdoc_tracks_only_runtime_onnx_resource_paths() -> None:
    tracked_paths = set(_tracked_onnx_entries())

    assert tracked_paths == EXPECTED_TRACKED_ONNX


def test_required_onnx_symlinks_resolve_to_kept_models() -> None:
    for relative_path, target in EXPECTED_SYMLINKS.items():
        onnx_path = REPO_ROOT / relative_path

        assert onnx_path.is_symlink(), f"{relative_path} should stay a symlink"
        assert onnx_path.readlink().as_posix() == target
        assert onnx_path.exists(), f"{relative_path} points at a missing ONNX"


def test_no_duplicate_regular_onnx_payloads_are_tracked() -> None:
    payloads: defaultdict[str, list[str]] = defaultdict(list)
    for relative_path, mode in _tracked_onnx_entries().items():
        if mode != "100644":
            continue
        payloads[_sha256_file(REPO_ROOT / relative_path)].append(relative_path)

    duplicates = {
        digest: paths for digest, paths in payloads.items() if len(paths) > 1
    }

    assert duplicates == {}
