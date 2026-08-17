from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.deepdoc.parser.tcadp_parser as tcadp_module
from app.deepdoc.parser.tcadp_parser import TCADPParser, TencentCloudAPIClient


def _make_parser() -> TCADPParser:
    parser = object.__new__(TCADPParser)
    parser.logger = logging.getLogger("tests.tcadp")
    parser.secret_id = "secret-id"
    parser.secret_key = "secret-key"
    parser.region = "ap-guangzhou"
    parser.table_result_type = "1"
    parser.markdown_image_response_type = "1"
    return parser


def test_reconstruct_document_sse_streaming_completion_keeps_final_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, object]] = []

    class _FakeRequest:
        def from_json_string(self, payload: str) -> None:
            requests.append(json.loads(payload))

    def _events():
        yield {"data": "{not-json"}
        yield {"data": json.dumps({"Progress": "50"})}
        yield {
            "data": json.dumps(
                {
                    "Progress": "100",
                    "TaskId": "task-123",
                    "SuccessPageNum": 2,
                    "FailPageNum": 1,
                    "FailedPages": [{"PageNumber": 3, "ErrorMsg": "ocr failed"}],
                    "DocumentRecognizeResultUrl": "https://example.test/result.zip",
                }
            )
        }

    client = object.__new__(TencentCloudAPIClient)
    client.client = SimpleNamespace(ReconstructDocumentSSE=lambda _req: _events())
    monkeypatch.setattr(
        tcadp_module,
        "models",
        SimpleNamespace(ReconstructDocumentSSERequest=_FakeRequest),
    )

    result = client.reconstruct_document_sse(
        file_type="PDF",
        file_base64="ZmFrZQ==",
        file_start_page=3,
        file_end_page=9,
        config={"TableResultType": "1"},
    )

    assert result == {
        "Progress": "100",
        "TaskId": "task-123",
        "SuccessPageNum": 2,
        "FailPageNum": 1,
        "FailedPages": [{"PageNumber": 3, "ErrorMsg": "ocr failed"}],
        "DocumentRecognizeResultUrl": "https://example.test/result.zip",
    }
    assert requests == [
        {
            "FileType": "PDF",
            "FileStartPageNumber": 3,
            "FileEndPageNumber": 9,
            "FileBase64": "ZmFrZQ==",
            "Config": {"TableResultType": "1"},
        }
    ]


def test_reconstruct_document_sse_non_streaming_and_error_paths_return_expected_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeRequest:
        def from_json_string(self, payload: str) -> None:
            self.payload = payload

    client = object.__new__(TencentCloudAPIClient)
    monkeypatch.setattr(
        tcadp_module,
        "models",
        SimpleNamespace(ReconstructDocumentSSERequest=_FakeRequest),
    )

    client.client = SimpleNamespace(
        ReconstructDocumentSSE=lambda _req: SimpleNamespace(data=json.dumps({"Progress": "100", "TaskId": "ok"}))
    )
    assert client.reconstruct_document_sse(file_type="PDF", file_url="https://example.test/file.pdf") == {
        "Progress": "100",
        "TaskId": "ok",
    }

    client.client = SimpleNamespace(ReconstructDocumentSSE=lambda _req: SimpleNamespace(data=""))
    assert client.reconstruct_document_sse(file_type="PDF", file_url="https://example.test/file.pdf") is None

    client.client = SimpleNamespace(ReconstructDocumentSSE=lambda _req: (_ for _ in ()).throw(RuntimeError("boom")))
    assert client.reconstruct_document_sse(file_type="PDF", file_url="https://example.test/file.pdf") is None


def test_parse_content_to_sections_and_tables_preserve_fields_and_position_semantics() -> None:
    parser = _make_parser()
    content_data = [
        {"type": "text", "content": "Paragraph"},
        {"type": "paragraph", "content": "Body"},
        {"type": "table", "content": "table", "table_data": {"rows": [["H1", "H2"], ["A", "B"]]}},
        {"type": "image", "content": "image-binary", "caption": "Figure 1"},
        {"type": "equation", "content": "x+y"},
        {"type": "custom", "content": "Fallback"},
        {"type": "text", "content": ""},
    ]

    sections = parser._parse_content_to_sections(content_data)
    tables = parser._parse_content_to_tables(content_data)

    assert sections == [
        ("Paragraph", "@@1\t0.0\t1000.0\t0.0\t100.0##"),
        ("Body", "@@1\t0.0\t1000.0\t0.0\t100.0##"),
        ("H1 | H2\nA | B", "@@1\t0.0\t1000.0\t0.0\t100.0##"),
        ("[Image] Figure 1", "@@1\t0.0\t1000.0\t0.0\t100.0##"),
        ("$$x+y$$", "@@1\t0.0\t1000.0\t0.0\t100.0##"),
        ("Fallback", "@@1\t0.0\t1000.0\t0.0\t100.0##"),
    ]
    assert tables == [
        "<table>\n"
        "  <tr>\n"
        "    <th>H1</th>\n"
        "    <th>H2</th>\n"
        "  </tr>\n"
        "  <tr>\n"
        "    <td>A</td>\n"
        "    <td>B</td>\n"
        "  </tr>\n"
        "</table>"
    ]


def test_parse_pdf_success_keeps_callbacks_and_cleans_temp_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    parser = _make_parser()
    callback_events: list[tuple[float, str]] = []
    base64_calls: list[tuple[str, bytes | None, bool]] = []
    output_dir = tmp_path / "tcadp-output"
    sample_content = [
        {"type": "text", "content": "Summary"},
        {"type": "table", "content": "table", "table_data": {"rows": [["Col"], ["Value"]]}},
    ]

    class _FakeClient:
        instances: list[_FakeClient] = []

        def __init__(self, secret_id: str, secret_key: str, region: str) -> None:
            self.secret_id = secret_id
            self.secret_key = secret_key
            self.region = region
            self.download_calls: list[tuple[str, str]] = []
            self.reconstruct_calls: list[dict[str, object]] = []
            self.__class__.instances.append(self)

        def reconstruct_document_sse(self, **kwargs):
            self.reconstruct_calls.append(kwargs)
            return {"DocumentRecognizeResultUrl": "https://example.test/result.zip"}

        def download_result_file(self, download_url: str, target_dir: str) -> str:
            self.download_calls.append((download_url, target_dir))
            Path(target_dir).mkdir(parents=True, exist_ok=True)
            zip_path = Path(target_dir) / "result.zip"
            zip_path.write_bytes(b"zip")
            return str(zip_path)

    def _callback(progress: float, message: str) -> None:
        callback_events.append((progress, message))

    def _file_to_base64(file_path: str, binary: bytes | None = None) -> str:
        base64_calls.append((file_path, binary, Path(file_path).exists()))
        return "encoded-pdf"

    monkeypatch.setattr(tcadp_module, "TencentCloudAPIClient", _FakeClient)
    monkeypatch.setattr(parser, "_file_to_base64", _file_to_base64)
    monkeypatch.setattr(parser, "_extract_content_from_zip", lambda _zip_path: sample_content)
    monkeypatch.setattr(tcadp_module.tempfile, "mkdtemp", lambda prefix="adp_pdf_": str(output_dir))

    sections, tables = parser.parse_pdf(
        filepath="ignored.pdf",
        binary=b"%PDF-1.4\n",
        callback=_callback,
        max_retries=1,
    )

    fake_client = _FakeClient.instances[0]
    temp_pdf = Path(base64_calls[0][0])

    assert sections == [
        ("Summary", "@@1\t0.0\t1000.0\t0.0\t100.0##"),
        ("Col\nValue", "@@1\t0.0\t1000.0\t0.0\t100.0##"),
    ]
    assert tables == ["<table>\n  <tr>\n    <th>Col</th>\n  </tr>\n  <tr>\n    <td>Value</td>\n  </tr>\n</table>"]
    assert fake_client.secret_id == "secret-id"
    assert fake_client.secret_key == "secret-key"
    assert fake_client.region == "ap-guangzhou"
    assert fake_client.reconstruct_calls == [
        {
            "file_type": "PDF",
            "file_base64": "encoded-pdf",
            "file_start_page": 1,
            "file_end_page": 1000,
            "config": {"TableResultType": "1", "MarkdownImageResponseType": "1"},
        }
    ]
    assert fake_client.download_calls == [("https://example.test/result.zip", str(output_dir))]
    assert base64_calls == [(str(temp_pdf), b"%PDF-1.4\n", True)]
    assert not temp_pdf.exists()
    assert not output_dir.exists()
    assert callback_events == [
        (0.1, f"[TCADP] Received binary PDF -> {temp_pdf.name}"),
        (0.2, "[TCADP] Converting file to Base64 format"),
        (0.25, "[TCADP] File converted to Base64, size: 11 characters"),
        (0.3, "[TCADP] Starting to call Tencent Cloud document parsing API"),
        (0.6, "[TCADP] Parsing result download link obtained"),
        (0.8, "[TCADP] Parsing result downloaded: result.zip"),
        (0.9, "[TCADP] Extracted 2 content blocks"),
        (1.0, "[TCADP] Parsing completed: 2 sections, 1 tables"),
    ]


def test_parse_pdf_raises_after_retrying_failed_attempts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    parser = _make_parser()
    callback_events: list[tuple[float, str]] = []
    sleep_calls: list[int] = []
    pdf_path = tmp_path / "input.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    class _FakeClient:
        def __init__(self, secret_id: str, secret_key: str, region: str) -> None:
            self.secret_id = secret_id
            self.secret_key = secret_key
            self.region = region

        def reconstruct_document_sse(self, **kwargs):
            return None

    monkeypatch.setattr(tcadp_module, "TencentCloudAPIClient", _FakeClient)
    monkeypatch.setattr(parser, "_file_to_base64", lambda file_path, binary=None: "encoded-pdf")
    monkeypatch.setattr(tcadp_module.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    with pytest.raises(RuntimeError, match=r"^\[TCADP\] Document parsing failed, retried 2 times$"):
        parser.parse_pdf(
            filepath=str(pdf_path),
            binary=b"",
            callback=lambda progress, message: callback_events.append((progress, message)),
            max_retries=2,
        )

    assert sleep_calls == [2]
    assert callback_events == [
        (0.2, "[TCADP] Converting file to Base64 format"),
        (0.25, "[TCADP] File converted to Base64, size: 11 characters"),
        (0.3, "[TCADP] Starting to call Tencent Cloud document parsing API"),
        (0.4, "[TCADP] Retry attempt 2"),
        (-1, "[TCADP] Document parsing failed, retried 2 times"),
    ]
