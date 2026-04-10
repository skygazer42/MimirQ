from __future__ import annotations

from langchain_core.documents import Document

from app.core.config import settings
from app.parsing.parsers.deepdoc_parser import DeepDocParser


class _FakePdfParser:
    total_page = 1

    def __call__(self, _path: str, **_kwargs):  # noqa: ANN001
        return ["合同正文"], []


def test_deepdoc_parser_appends_seal_documents_when_enabled(monkeypatch, tmp_path):  # noqa: ANN001
    import app.parsing.enrich.seal_recognition as seal_mod

    parser = DeepDocParser()
    parser._pdf_parser = _FakePdfParser()

    monkeypatch.setattr(settings, "SEAL_RECOGNITION_ENABLED", True, raising=False)
    monkeypatch.setattr(
        seal_mod,
        "extract_seal_documents_from_pdf",
        lambda **_kwargs: [
            Document(
                page_content="印章识别：杭州测试科技有限公司",
                metadata={
                    "doc_type_kwd": "seal",
                    "seal_present": True,
                    "seal_text": "杭州测试科技有限公司",
                    "seal_score": 0.97,
                    "parser_backend": "deepdoc",
                    "page": 1,
                },
            )
        ],
        raising=True,
    )

    docs = parser.parse(tmp_path / "contract.pdf")

    assert len(docs) == 2
    assert docs[0].page_content == "合同正文"
    assert docs[1].metadata["doc_type_kwd"] == "seal"
    assert docs[1].metadata["seal_present"] is True
    assert docs[1].metadata["seal_text"] == "杭州测试科技有限公司"


def test_deepdoc_parser_skips_seal_documents_when_disabled(monkeypatch, tmp_path):  # noqa: ANN001
    import app.parsing.enrich.seal_recognition as seal_mod

    parser = DeepDocParser()
    parser._pdf_parser = _FakePdfParser()

    monkeypatch.setattr(settings, "SEAL_RECOGNITION_ENABLED", False, raising=False)

    def _unexpected(**_kwargs):  # noqa: ANN001
        raise AssertionError("seal extraction should not run when disabled")

    monkeypatch.setattr(seal_mod, "extract_seal_documents_from_pdf", _unexpected, raising=True)

    docs = parser.parse(tmp_path / "contract.pdf")

    assert len(docs) == 1
    assert docs[0].page_content == "合同正文"
