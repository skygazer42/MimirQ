from io import BytesIO

import pytest
from langchain_core.documents import Document

from app.rag.ingestion.parsing.parsers.docling_parser import DoclingParser, _html_table_to_markdown
from app.services.parsing import docling


class _Response:
    def __init__(self, payload=None, *, error=None):
        self.payload = payload
        self.error = error
        self.closed = 0

    def raise_for_status(self):
        return None

    def json(self):
        if self.error is not None:
            raise self.error
        return self.payload

    def close(self):
        self.closed += 1


class _Session:
    def __init__(self, response):
        self.response = response
        self.uploaded = []

    def post(self, url, **kwargs):
        self.uploaded.append((url, kwargs))
        return self.response


def test_docling_table_processing_preserves_content_metadata_and_identity():
    source = Document(
        page_content="<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>",
        metadata={"content_type": "table", "source": "report.pdf"},
        id="table-1",
    )
    expected = "| A | B |\n| --- | --- |\n| 1 | 2 |"
    assert _html_table_to_markdown(source.page_content) == expected
    result = DoclingParser(table_mode="markdown")._process_document(source)
    assert result[0].page_content == expected
    assert result[0].metadata["source"] == "report.pdf"
    assert result[0].id == "table-1"
    image = Document(page_content="image", metadata={"doc_type_kwd": "image"})
    assert DoclingParser(extract_images=False)._process_document(image) == []


def test_remote_docling_conversion_closes_response_and_restores_caller_stream(monkeypatch):
    monkeypatch.setattr(docling.settings, "DOCLING_ENABLED", True)
    response = _Response({"status": "success", "document": {"md_content": "# Body"}})
    session = _Session(response)
    parser = docling.DoclingServiceParser(api_url="http://docling.invalid", session=session)
    stream = BytesIO(b"PDF fixture")
    stream.seek(3)
    sections, tables = parser.parse_pdf("nested/report.pdf", binary=stream)
    assert sections == [("# Body", "")]
    assert tables == []
    assert stream.tell() == 3
    assert not stream.closed
    assert response.closed == 1
    assert session.uploaded[0][1]["files"]["files"][0] == "report.pdf"


def test_docling_conversion_error_remains_visible_and_closes_response(monkeypatch):
    monkeypatch.setattr(docling.settings, "DOCLING_ENABLED", True)
    response = _Response(error=ValueError("not json"))
    parser = docling.DoclingServiceParser(api_url="http://docling.invalid", session=_Session(response))
    with pytest.raises(RuntimeError, match="non-JSON") as error:
        parser.parse_pdf("report.pdf", binary=b"PDF fixture")
    assert isinstance(error.value.__cause__, ValueError)
    assert response.closed == 1


def test_docling_path_payload_closes_owned_file_on_failure(tmp_path):
    path = tmp_path / "input.pdf"
    path.write_bytes(b"PDF fixture")
    with pytest.raises(RuntimeError, match="downstream"):
        with docling.DoclingServiceParser._source_payload(path, None) as (actual, stream):
            assert actual == path
            assert stream.read() == b"PDF fixture"
            raise RuntimeError("downstream")
    assert stream.closed


@pytest.mark.parametrize("max_pages", [0, -1, False, "2"])
def test_docling_rejects_invalid_page_limits_before_conversion(max_pages):
    with pytest.raises(ValueError, match="positive integer"):
        DoclingParser(max_pages=max_pages)
