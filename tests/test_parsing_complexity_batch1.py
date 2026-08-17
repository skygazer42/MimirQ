import io
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from PIL import Image

from app.parsing.parsers.csv_parser import CsvParser
from app.parsing.parsers.docx_parser import DocxParser
from app.parsing.parsers.pdf_parser import PDFParser
from app.parsing.preprocess.llm_noise_miner import mine_noise_rule_candidates
from app.parsing.preprocess.orientation import normalize_pdf_rotation
from app.parsing.utils.cli import resolve_cli_command


def test_csv_parser_characterizes_headerless_rows(tmp_path: Path) -> None:
    path = tmp_path / "sample.csv"
    path.write_text("1,2\n3,4\n", encoding="utf-8")

    document = CsvParser().parse(path)[0]

    assert document.page_content == (
        "CSV: sample.csv\nDelimiter: ','\nColumns: 1, 2\n\nrow 1: 1=1 | 2=2\nrow 2: 1=3 | 2=4\n"
    )
    assert document.metadata["csv_has_header"] is False
    assert document.metadata["csv_rows_emitted"] == 2
    assert document.metadata["csv_columns"] == ["1", "2"]


def test_csv_parser_characterizes_empty_cells_and_truncation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "sample.csv"
    path.write_text('name,,notes\nAlice,,"line 1\nline 2"\n', encoding="utf-8")
    monkeypatch.setattr("app.parsing.parsers.csv_parser.csv.Sniffer.has_header", lambda _self, _sample: True)

    document = CsvParser(max_cell_chars=6).parse(path)[0]

    assert document.page_content == (
        "CSV: sample.csv\nDelimiter: ','\nColumns: name, col2, notes\n\nrow 1: name=Alice | col2= | notes=line …\n"
    )
    assert document.metadata["csv_has_header"] is True
    assert document.metadata["csv_columns"] == ["name", "col2", "notes"]


def test_docx_parser_preserves_block_order_and_formats_structures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_doc = object()
    docx_module = ModuleType("docx")
    docx_module.Document = lambda _path: fake_doc  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "docx", docx_module)

    heading = SimpleNamespace(text="Project Brief", style=SimpleNamespace(name="Heading 2"))
    bullet = SimpleNamespace(text="First item", style=SimpleNamespace(name="List Bullet"), is_list=True, list_level=1)
    paragraph = SimpleNamespace(text="Closing summary", style=SimpleNamespace(name="Body Text"))
    table = SimpleNamespace(
        rows=[
            SimpleNamespace(cells=[SimpleNamespace(text="Metric"), SimpleNamespace(text="Value")]),
            SimpleNamespace(cells=[SimpleNamespace(text="Latency"), SimpleNamespace(text="120ms")]),
        ]
    )

    monkeypatch.setattr(
        "app.parsing.parsers.docx_parser._iter_docx_blocks", lambda _doc: [heading, bullet, paragraph, table]
    )
    monkeypatch.setattr(
        "app.parsing.parsers.docx_parser._is_list_paragraph", lambda block: bool(getattr(block, "is_list", False))
    )
    monkeypatch.setattr(
        "app.parsing.parsers.docx_parser._list_level", lambda block: int(getattr(block, "list_level", 0))
    )

    path = tmp_path / "brief.docx"
    path.write_bytes(b"placeholder")

    document = DocxParser().parse(path)[0]

    assert document.page_content == "\n\n".join(
        [
            "## Project Brief",
            "  - First item",
            "Closing summary",
            "| Metric | Value |\n| --- | --- |\n| Latency | 120ms |",
        ]
    )
    assert document.metadata == {"source": "brief.docx", "file_type": "docx"}


def test_pdf_parser_extract_image_documents_deduplicates_xrefs_and_keeps_code_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_buffer = io.BytesIO()
    Image.new("RGB", (4, 4), color="white").save(image_buffer, format="PNG")
    image_bytes = image_buffer.getvalue()

    class _FakePdf:
        def __len__(self) -> int:
            return 2

        def extract_image(self, xref: int) -> dict[str, bytes]:
            assert xref == 7
            return {"image": image_bytes}

    class _FakePage:
        def get_images(self, *, full: bool) -> list[tuple[int]]:
            assert full is True
            return [(7,), (7,)]

    monkeypatch.setattr(
        "app.parsing.parsers.pdf_parser.decode_image_codes",
        lambda image: {"visual_kind": "qr", "text": "HELLO-QR", "values": ["HELLO-QR", ""]},
    )
    monkeypatch.setattr("app.parsing.parsers.pdf_parser.infer_visual_kind_from_pixels", lambda image: "ignored")

    documents = PDFParser()._extract_image_documents(
        pdf_document=_FakePdf(),
        page=_FakePage(),
        file_path=tmp_path / "scan.pdf",
        page_num=1,
    )

    assert len(documents) == 1
    document = documents[0]
    assert document.page_content == "HELLO-QR"
    assert document.metadata["source"] == "scan.pdf"
    assert document.metadata["page"] == 2
    assert document.metadata["total_pages"] == 2
    assert document.metadata["visual_kind"] == "qr"
    assert document.metadata["image_code_text"] == "HELLO-QR"
    assert document.metadata["image_code_values"] == ["HELLO-QR"]
    assert document.metadata["image_index"] == 0


def test_mine_noise_rule_candidates_characterizes_template_and_exact_matches() -> None:
    result = mine_noise_rule_candidates(
        [
            "重复行",
            "回复时间：昨天",
            "重复行",
            "【回复 12 - 标题】",
            "回复时间：今天",
            "重复行",
        ],
        top_k=5,
        min_frequency=2,
    )

    assert result["summary"] == {"input_lines": 6, "candidate_count": 2}
    assert result["candidates"] == [
        {
            "pattern_kind": "exact",
            "pattern_name": "repeated_line",
            "pattern": r"(?m)^\s*重复行\s*$",
            "count": 3,
            "examples": ["重复行"],
            "review_required": True,
        },
        {
            "pattern_kind": "template",
            "pattern_name": "reply_time",
            "pattern": r"(?m)^\s*回复时间：.*$",
            "count": 2,
            "examples": ["回复时间：昨天", "回复时间：今天"],
            "review_required": True,
        },
    ]


def test_normalize_pdf_rotation_characterizes_uniform_rotation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class _FakePage:
        def __init__(self, rotation: int) -> None:
            self.rotation = rotation
            self.set_rotation_calls: list[int] = []

        def set_rotation(self, value: int) -> None:
            self.set_rotation_calls.append(value)
            self.rotation = value

    class _FakeDoc:
        def __init__(self) -> None:
            self.pages = [_FakePage(90), _FakePage(90), _FakePage(90)]
            self.page_count = len(self.pages)
            self.saved: tuple[str, int, bool] | None = None
            self.closed = False

        def load_page(self, index: int) -> _FakePage:
            return self.pages[index]

        def save(self, path: str, *, garbage: int, deflate: bool) -> None:
            self.saved = (path, garbage, deflate)

        def close(self) -> None:
            self.closed = True

    fake_doc = _FakeDoc()
    fitz_module = ModuleType("fitz")
    fitz_module.open = lambda _path: fake_doc  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fitz", fitz_module)

    output_path = tmp_path / "normalized" / "sample.pdf"
    changed, note, meta = normalize_pdf_rotation(
        input_path=tmp_path / "sample.pdf",
        output_path=output_path,
        sample_pages=2,
    )

    assert changed is True
    assert note == "normalized_rotation:90->0"
    assert meta["sample_pages"] == 2
    assert meta["rotation_counts"] == {"90": 2}
    assert meta["rotation_mode"] == 90
    assert isinstance(meta["elapsed_ms"], int)
    assert fake_doc.saved == (str(output_path), 4, True)
    assert fake_doc.closed is True
    assert [page.set_rotation_calls for page in fake_doc.pages] == [[0], [0], [0]]


def test_normalize_pdf_rotation_characterizes_mixed_sample_skip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class _FakePage:
        def __init__(self, rotation: int) -> None:
            self.rotation = rotation
            self.set_rotation_calls: list[int] = []

        def set_rotation(self, value: int) -> None:
            self.set_rotation_calls.append(value)

    class _FakeDoc:
        def __init__(self) -> None:
            self.pages = [_FakePage(90), _FakePage(0), _FakePage(90)]
            self.page_count = len(self.pages)
            self.saved = False
            self.closed = False

        def load_page(self, index: int) -> _FakePage:
            return self.pages[index]

        def save(self, path: str, *, garbage: int, deflate: bool) -> None:
            self.saved = True

        def close(self) -> None:
            self.closed = True

    fake_doc = _FakeDoc()
    fitz_module = ModuleType("fitz")
    fitz_module.open = lambda _path: fake_doc  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fitz", fitz_module)

    changed, note, meta = normalize_pdf_rotation(
        input_path=tmp_path / "sample.pdf",
        output_path=tmp_path / "normalized.pdf",
        sample_pages=2,
    )

    assert changed is False
    assert note == "mixed_rotation_skipped"
    assert meta["rotation_counts"] == {"0": 1, "90": 1}
    assert meta["rotation_mode"] == 90
    assert fake_doc.saved is False
    assert fake_doc.closed is True
    assert [page.set_rotation_calls for page in fake_doc.pages] == [[], [], []]


def test_resolve_cli_command_characterizes_pathlike_and_env_bin_lookup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_python = tmp_path / "venv" / "python"
    env_bin = tmp_path / "venv" / "bin"
    env_bin.mkdir(parents=True)
    env_python.write_text("", encoding="utf-8")
    tool_path = env_bin / "pandoc"
    tool_path.write_text("", encoding="utf-8")

    monkeypatch.setattr("app.parsing.utils.cli.shutil.which", lambda _cmd: None)
    monkeypatch.setattr("app.parsing.utils.cli.sys.executable", str(env_python))

    assert resolve_cli_command(str(tmp_path / "missing" / "pandoc")) is None
    assert resolve_cli_command("pandoc") == str(tool_path.resolve())
