from __future__ import annotations

import builtins
import datetime as _datetime
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import starlette.status as starlette_status
from PIL import Image
from pydantic import ConfigDict as _PydanticConfigDict

if not hasattr(_datetime, "UTC"):
    _datetime.UTC = _datetime.timezone.utc
if not hasattr(starlette_status, "HTTP_413_CONTENT_TOO_LARGE"):
    starlette_status.HTTP_413_CONTENT_TOO_LARGE = 413
if not hasattr(starlette_status, "HTTP_422_UNPROCESSABLE_CONTENT"):
    starlette_status.HTTP_422_UNPROCESSABLE_CONTENT = 422
if not hasattr(builtins, "ConfigDict"):
    builtins.ConfigDict = _PydanticConfigDict


def test_deepdoc_parser_docx_parse_formats_sections_and_attaches_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.parsing.parsers.deepdoc_parser import DeepDocParser

    runtime_metadata = {
        "layout": {"available": True},
        "ocr_recognition": {"available": False},
    }

    class _DocxParser:
        def __call__(self, _path: str):
            return (
                [
                    ("Document Title", "Heading 1"),
                    ("First bullet", "List Bullet"),
                    "Body paragraph",
                ],
                [["A1", "A2"], "Table tail"],
            )

    parser = DeepDocParser()
    monkeypatch.setattr(parser, "_ensure_docx_parser", lambda: _DocxParser())
    monkeypatch.setattr(parser, "_small_model_runtime_metadata", lambda: runtime_metadata)

    docs = parser.parse(tmp_path / "sample.docx")

    assert len(docs) == 1
    assert docs[0].page_content == "# Document Title\n\n- First bullet\n\nBody paragraph\n\nA1\nA2\n\nTable tail"
    assert docs[0].metadata["file_type"] == "docx"
    assert docs[0].metadata["parser_backend"] == "deepdoc"
    assert docs[0].metadata["small_model_runtime"] == runtime_metadata
    assert docs[0].metadata["deepdoc_profile"] == {
        "schema": "mimirq.deepdoc_profile.v1",
        "engine": "deepdoc",
        "file_type": "docx",
        "stages_ms": docs[0].metadata["deepdoc_profile"]["stages_ms"],
        "document_count": 1,
        "section_count": 3,
        "media_count": 2,
        "small_model_summary": {
            "task_count": 2,
            "available_count": 1,
            "unavailable_count": 1,
            "unavailable_tasks": ["ocr_recognition"],
        },
    }


def test_deepdoc_parser_pdf_returns_fallback_doc_with_profile_when_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import app.parsing.parsers.deepdoc_parser as deepdoc_module
    from app.parsing.parsers.deepdoc_parser import DeepDocParser

    runtime_metadata = {"layout": {"available": True}}

    class _PdfParser:
        total_page = 2
        ocr = SimpleNamespace(last_recognition_profile={"provider": "fake"})

        def __call__(self, _path: str, **_kwargs):
            return [], []

    parser = DeepDocParser()
    monkeypatch.setattr(parser, "_ensure_pdf_parser", lambda: _PdfParser())
    monkeypatch.setattr(parser, "_small_model_runtime_metadata", lambda: runtime_metadata)
    monkeypatch.setattr(
        deepdoc_module,
        "remove_document_watermark_elements",
        lambda elements: SimpleNamespace(changed=False, elements=elements, to_metadata=lambda: {"changed": False}),
    )
    monkeypatch.setattr(
        deepdoc_module,
        "remove_repeated_header_footer_elements",
        lambda elements: SimpleNamespace(changed=False, elements=elements, to_metadata=lambda: {"changed": False}),
    )
    monkeypatch.setattr(
        deepdoc_module,
        "fix_reading_order_elements",
        lambda elements: SimpleNamespace(elements=elements, to_metadata=lambda: {"changed": False}),
    )
    monkeypatch.setattr(deepdoc_module, "build_section_tree", lambda elements: [])
    monkeypatch.setattr(deepdoc_module, "link_cross_page_table_documents", lambda docs: docs)

    docs = parser.parse(tmp_path / "scan.pdf")

    assert len(docs) == 1
    assert docs[0].page_content == ""
    assert docs[0].metadata["source"] == "scan.pdf"
    assert docs[0].metadata["file_type"] == "pdf"
    assert docs[0].metadata["parser_backend"] == "deepdoc"
    assert docs[0].metadata["total_pages"] == 2
    assert docs[0].metadata["small_model_runtime"] == runtime_metadata
    assert docs[0].metadata["deepdoc_profile"]["document_count"] == 1
    assert docs[0].metadata["deepdoc_profile"]["total_pages"] == 2
    assert docs[0].metadata["deepdoc_profile"]["ocr_recognition"] == {"provider": "fake"}


def test_deepseek_ocr_parse_preserves_page_order_and_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import app.parsing.parsers.deepseek_ocr_parser as deepseek_module
    from app.parsing.parsers.deepseek_ocr_parser import DeepSeekOCRParser

    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    class _FakePixmap:
        def __init__(self, index: int) -> None:
            self._index = index

        def tobytes(self, fmt: str) -> bytes:
            return f"{fmt}-{self._index}".encode("utf-8")

    class _FakePage:
        def __init__(self, index: int) -> None:
            self._index = index

        def get_pixmap(self, dpi: int) -> _FakePixmap:
            assert dpi == 144
            return _FakePixmap(self._index)

    class _FakeDoc:
        def __init__(self) -> None:
            self._pages = [_FakePage(1), _FakePage(2)]
            self.closed = False

        def __len__(self) -> int:
            return len(self._pages)

        def __iter__(self):
            return iter(self._pages)

        def close(self) -> None:
            self.closed = True

    parser = object.__new__(DeepSeekOCRParser)
    parser._pdf_dpi = 144
    parser._extract_pdf_images = lambda doc, images_dir: 3
    parser._call_api = lambda data_bytes, *, mime_type: (
        "first page\n\n![](images/missing.jpg)" if data_bytes == b"png-1" else "second page"
    )

    monkeypatch.setattr(deepseek_module.settings, "DEEPSEEK_OCR_INCLUDE_PAGE_IMAGES", True, raising=False)
    monkeypatch.setattr(deepseek_module.settings, "DEEPSEEK_OCR_PAGE_IMAGE_MAX_PAGES", 0, raising=False)
    monkeypatch.setattr(deepseek_module.settings, "DEEPSEEK_OCR_PAGE_IMAGE_FORMAT", "invalid", raising=False)
    monkeypatch.setattr(deepseek_module.settings, "DEEPSEEK_OCR_CONCURRENCY", 1, raising=False)
    monkeypatch.setattr(deepseek_module.fitz, "open", lambda _path: _FakeDoc())

    docs = parser.parse(pdf_path, document_id="doc 17")
    artifact_root = (tmp_path / ".deepseek_ocr" / "doc_17").resolve()

    assert [doc.metadata["page"] for doc in docs] == [1, 2]
    assert docs[0].page_content == "![page 1](images/page_0001.jpg)\n\nfirst page\n\n![](images/missing.jpg)"
    assert docs[1].page_content == "![page 2](images/page_0002.jpg)\n\nsecond page"
    for doc in docs:
        assert doc.metadata["asset_base_dir"] == str(artifact_root)
        assert doc.metadata["artifact_dir"] == str(artifact_root)
        assert doc.metadata["deepseek_ocr_extracted_images"] == 3
        assert doc.metadata["deepseek_ocr_concurrency"] == 1

    assert (artifact_root / "images" / "page_0001.png").read_bytes() == b"png-1"
    assert (artifact_root / "images" / "page_0001.jpg").read_bytes() == b"jpg-1"
    assert (artifact_root / "images" / "missing.jpg").read_bytes() == b"jpg-1"


def test_paddle_vl_normalize_local_files_rewrites_images_json_and_markdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.parsing.parsers.paddle_vl_parser import PaddleVLParser

    output_dir = tmp_path / "output"
    page_dir = output_dir / "page_1"
    imgs_dir = page_dir / "imgs"
    nested_dir = output_dir / "nested"
    imgs_dir.mkdir(parents=True)
    nested_dir.mkdir(parents=True)

    old_name = "img_in_image_box_1_2_3_4.jpg"
    (imgs_dir / old_name).write_bytes(b"img-bytes")
    (page_dir / "page_1_res.json").write_text(
        json.dumps(
            {
                "page_index": 0,
                "parsing_res_list": [{"block_label": "image", "block_bbox": [1, 2, 3, 4]}],
            }
        ),
        encoding="utf-8",
    )
    markdown_path = nested_dir / "source.md"
    markdown_path.write_text(
        f"![figure](./{old_name})\n<img src=\"{old_name}\" alt=\"figure\">",
        encoding="utf-8",
    )

    parser = object.__new__(PaddleVLParser)
    monkeypatch.setattr(
        "app.parsing.parsers.paddle_vl_parser.ZipImageProcessor._choose_markdown_file",
        lambda files: markdown_path,
    )

    normalized = parser._normalize_local_files(output_dir)

    assert normalized["image_count"] == 1
    assert normalized["markdown_file"] == output_dir / "result.md"
    assert normalized["json_file"] == output_dir / "result.json"
    assert (output_dir / "images" / "image_001.jpg").read_bytes() == b"img-bytes"
    assert not (imgs_dir / old_name).exists()

    combined = json.loads((output_dir / "result.json").read_text(encoding="utf-8"))
    assert combined["pages"][0]["parsing_res_list"][0]["img_path"] == "images/image_001.jpg"

    markdown = (output_dir / "result.md").read_text(encoding="utf-8")
    assert "![figure](images/image_001.jpg)" in markdown
    assert '<img src="images/image_001.jpg" alt="figure">' in markdown


def test_excel_parser_parse_xlsx_unmerges_cells_and_marks_truncation(tmp_path: Path) -> None:
    from openpyxl import Workbook

    from app.parsing.parsers.excel_parser import ExcelParser

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet["A1"] = "Name"
    sheet["B1"] = "Value"
    sheet["A2"] = "Merged"
    sheet.merge_cells("A2:B3")
    sheet["A4"] = "Ignored"
    file_path = tmp_path / "table.xlsx"
    workbook.save(file_path)
    workbook.close()

    docs = ExcelParser(max_rows=3).parse(file_path)

    assert len(docs) == 1
    assert "Excel: table.xlsx" in docs[0].page_content
    assert "## Sheet: Data" in docs[0].page_content
    assert "| Name | Value |" in docs[0].page_content
    assert "| Merged | Merged |" in docs[0].page_content
    assert docs[0].metadata["excel_rows_emitted"] == 3
    assert docs[0].metadata["excel_truncated"] is True


def test_preprocess_file_applies_text_and_html_steps_in_order(tmp_path: Path) -> None:
    from app.parsing.preprocess.file_preprocessor import preprocess_file

    input_path = tmp_path / "sample.html"
    input_path.write_bytes(
        (
            "\ufeff<header>top</header>\r\n<body>line 1  \r\n<script>bad()</script>\r\n"
            "<!-- comment -->\r\n<nav>menu</nav>\r\nline 2\u200b\r\n\r\n\r\n</body>\r\n"
        ).encode("utf-8")
    )

    result = preprocess_file(
        input_path=input_path,
        steps=[
            {"id": "text.reencode_utf8"},
            {"id": "text.strip_bom"},
            {"id": "text.normalize_newlines"},
            {"id": "html.strip_scripts_styles"},
            {"id": "html.strip_comments"},
            {"id": "html.strip_boilerplate_tags"},
            {"id": "text.remove_zero_width"},
            {"id": "text.collapse_blank_lines"},
            {"id": "text.trim_trailing_whitespace"},
        ],
    )

    output_text = Path(result.output_path).read_text(encoding="utf-8")

    assert result.changed is True
    assert result.output_path != str(input_path)
    assert result.warnings == []
    assert [step.id for step in result.steps] == [
        "text.reencode_utf8",
        "text.strip_bom",
        "text.normalize_newlines",
        "html.strip_scripts_styles",
        "html.strip_comments",
        "html.strip_boilerplate_tags",
        "text.remove_zero_width",
        "text.collapse_blank_lines",
        "text.trim_trailing_whitespace",
    ]
    assert output_text == "\n<body>line 1\n\nline 2\n\n</body>\n"


def test_run_local_onnx_cleanup_restores_original_size(tmp_path: Path) -> None:
    from app.parsing.preprocess.handwriting_cleanup import _run_local_onnx_cleanup

    input_path = tmp_path / "source.png"
    output_path = tmp_path / "cleaned.png"
    Image.new("RGB", (2, 1), color=(10, 20, 30)).save(input_path)

    class _FakeSession:
        def get_inputs(self):
            return [SimpleNamespace(name="input", shape=[1, 3, 4, 4])]

        def run(self, _names, feeds):
            tensor = feeds["input"]
            assert tensor.shape == (1, 3, 4, 4)
            return [np.ones((1, 3, 4, 4), dtype=np.float32)]

    changed = _run_local_onnx_cleanup(input_path=input_path, output_path=output_path, session=_FakeSession())

    with Image.open(output_path) as cleaned:
        assert cleaned.size == (2, 1)
        assert cleaned.mode == "RGB"
    assert changed is True


def test_cleanup_handwriting_document_auto_uses_heuristic_for_raster(tmp_path: Path) -> None:
    from app.parsing.preprocess.handwriting_cleanup import cleanup_handwriting_document

    input_path = tmp_path / "handwritten.png"
    output_path = tmp_path / "handwritten.cleaned.png"
    Image.new("RGB", (3, 3), color=(120, 120, 120)).save(input_path)

    changed, note, info = cleanup_handwriting_document(
        input_path=input_path,
        output_path=output_path,
        backend="auto",
    )

    assert info["backend"] == "heuristic"
    assert output_path.exists()
    assert note in {"cleanup_ok", "cleanup_no_change"}
    assert isinstance(changed, bool)


def test_preprocess_image_document_skips_high_quality_pdf(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.parsing.preprocess import image_preprocess as image_module
    from app.parsing.preprocess.image_preprocess import preprocess_image_document

    pdf_path = tmp_path / "clean.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(image_module.settings, "IMAGE_PREPROCESS_ENABLED", True, raising=False)
    monkeypatch.setattr(image_module.settings, "PREPROCESS_SKIP_HIGH_QUALITY", True, raising=False)

    result = preprocess_image_document(
        input_path=pdf_path,
        pdf_quality={"score": 0.9, "is_scanned": False},
    )

    assert result.output_path == str(pdf_path)
    assert result.changed is False
    assert [step.id for step in result.steps] == ["pdf_preprocess"]
    assert result.steps[0].note == "skip_high_quality"
    assert result.meta["pdf_quality_score"] == 0.9
    assert result.meta["pdf_is_scanned"] is False


def test_preprocess_image_document_image_pipeline_preserves_stage_order_and_artifact_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.parsing.preprocess import image_preprocess as image_module
    from app.parsing.preprocess.image_preprocess import ImagePreprocessStepLog, preprocess_image_document

    input_path = tmp_path / "photo.png"
    Image.new("RGB", (4, 4), color=(10, 20, 30)).save(input_path)

    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def _fix_exif_orientation(*, input_path: Path, output_path: Path):
        _write(output_path, b"oriented")
        return True, "rotated", {"backend": "exif"}

    def _run_paddle_stage(*, current: Path, artifact_root: Path, output_stem: str, warnings: list[str]):
        output_path = artifact_root / f"{output_stem}.paddleocr{current.suffix.lower()}"
        _write(output_path, b"paddle")
        return (
            output_path,
            True,
            ImagePreprocessStepLog(id="paddle_ocr_preprocess", applied=True, changed=True, note="cleanup_ok"),
            {"backend": "paddle"},
        )

    def _deskew_via_http(*, input_path: Path, output_path: Path, url: str, timeout_sec: float):
        assert url == "http://deskew"
        assert timeout_sec == 30.0
        _write(output_path, b"deskew")
        return True, "deskew_ok"

    def _run_handwriting_stage(*, current: Path, artifact_root: Path, output_stem: str, warnings: list[str]):
        output_path = artifact_root / f"{output_stem}.handwriting{current.suffix.lower()}"
        _write(output_path, b"handwriting")
        warnings.append("handwriting_warning")
        return (
            output_path,
            True,
            ImagePreprocessStepLog(id="handwriting_cleanup", applied=True, changed=True, note="cleanup_ok"),
            {"backend": "heuristic"},
        )

    def _cleanup_watermark_document(*, input_path: Path, output_path: Path, **_kwargs):
        _write(output_path, b"watermark")
        return True, "cleanup_ok", {"backend": "http"}

    monkeypatch.setattr(image_module.settings, "IMAGE_PREPROCESS_ENABLED", True, raising=False)
    monkeypatch.setattr(image_module.settings, "ORIENTATION_ENABLED", True, raising=False)
    monkeypatch.setattr(image_module.settings, "DESKEW_ENABLED", True, raising=False)
    monkeypatch.setattr(image_module.settings, "DESKEW_BACKEND", "auto", raising=False)
    monkeypatch.setattr(image_module.settings, "DESKEW_PADDLE_URL", "http://deskew", raising=False)
    monkeypatch.setattr(image_module.settings, "DESKEW_TIMEOUT_SEC", 30.0, raising=False)
    monkeypatch.setattr(image_module.settings, "WATERMARK_REMOVAL_ENABLED", True, raising=False)
    monkeypatch.setattr(image_module.settings, "WATERMARK_REMOVAL_BACKEND", "auto", raising=False)
    monkeypatch.setattr(image_module.settings, "WATERMARK_REMOVAL_API_URL", "", raising=False)
    monkeypatch.setattr(image_module.settings, "WATERMARK_TIMEOUT_SEC", 60.0, raising=False)
    monkeypatch.setattr(image_module.settings, "WATERMARK_REMOVAL_MODEL_PATH", "", raising=False)
    monkeypatch.setattr(image_module, "fix_exif_orientation", _fix_exif_orientation)
    monkeypatch.setattr(image_module, "_run_paddle_doc_preprocess_stage", _run_paddle_stage)
    monkeypatch.setattr(image_module, "deskew_via_http", _deskew_via_http)
    monkeypatch.setattr(image_module, "_run_handwriting_cleanup_stage", _run_handwriting_stage)
    monkeypatch.setattr(image_module, "cleanup_watermark_document", _cleanup_watermark_document)

    result = preprocess_image_document(input_path=input_path, document_id="photo 17")

    assert [step.id for step in result.steps] == [
        "orientation",
        "paddle_ocr_preprocess",
        "deskew",
        "handwriting_cleanup",
        "watermark_removal",
    ]
    assert result.changed is True
    assert result.warnings == ["handwriting_warning"]
    assert result.meta["image_orientation"] == {"backend": "exif"}
    assert result.meta["paddle_ocr_preprocess"] == {"backend": "paddle"}
    assert result.meta["handwriting_cleanup"] == {"backend": "heuristic"}
    assert result.meta["watermark_removal"] == {"backend": "http"}
    assert result.meta["artifact_dir"].endswith("/.mimirq_preprocess/photo_17")
    assert Path(result.output_path).name == "photo.dewatermark.png"
