from __future__ import annotations

import sys
import types
from pathlib import Path

from PIL import Image

from app.core.config import settings


def test_extract_seal_documents_from_pdf_emits_structured_candidates(monkeypatch, tmp_path: Path) -> None:
    import app.parsing.enrich.seal_recognition as seal_mod
    from app.parsing.enrich.seal_recognition import SealRecognitionResult

    pdf_path = tmp_path / "contract.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%dummy\n")

    monkeypatch.setattr(settings, "SEAL_RECOGNITION_ENABLED", True, raising=False)
    monkeypatch.setattr(seal_mod, "_resolve_model_dir", lambda *_args, **_kwargs: tmp_path, raising=True)

    image = Image.new("RGB", (8, 8), color="white")

    class _DummyPixmap:
        def __init__(self) -> None:
            self.n = 3
            self.width = image.width
            self.height = image.height
            self.samples = image.tobytes()

    class _DummyPage:
        def get_pixmap(self, matrix=None, alpha=False):  # noqa: ANN001
            return _DummyPixmap()

    class _DummyPdf:
        page_count = 1

        def load_page(self, page_index: int) -> _DummyPage:  # noqa: ARG002
            return _DummyPage()

        def close(self) -> None:
            return None

    fitz_stub = types.SimpleNamespace(
        open=lambda _path: _DummyPdf(),
        Matrix=lambda x, y: (x, y),
        Pixmap=lambda _colorspace, pix: pix,
        csRGB=object(),
    )
    monkeypatch.setitem(sys.modules, "fitz", fitz_stub)
    monkeypatch.setattr(
        seal_mod,
        "detect_and_recognize_seal_candidates",
        lambda *_args, **_kwargs: [
            SealRecognitionResult(
                present=True,
                text="杭州测试科技有限公司",
                score=0.97,
                bbox=(10, 20, 60, 70),
                detection_score=0.91,
                region_count=2,
                seal_kind="round_stamp",
                rank=0.952,
            ),
            SealRecognitionResult(
                present=True,
                text="财务专用章",
                score=0.89,
                bbox=(80, 30, 140, 76),
                detection_score=0.84,
                region_count=2,
                seal_kind="oval_stamp",
                rank=0.875,
            ),
        ],
        raising=True,
    )

    docs = seal_mod.extract_seal_documents_from_pdf(file_path=pdf_path, source="contract.pdf", parser_backend="deepdoc")

    assert len(docs) == 1
    metadata = docs[0].metadata
    assert metadata["seal_text"] == "杭州测试科技有限公司"
    assert metadata["seal_kind"] == "round_stamp"
    assert metadata["seal_primary"]["text"] == "杭州测试科技有限公司"
    assert len(metadata["seal_candidates"]) == 2
    assert metadata["seal_candidates"][1]["seal_kind"] == "oval_stamp"
    assert len(metadata["seal_bbox_list"]) == 2
    assert metadata["seal_bbox_list"][0]["x0"] == 10

