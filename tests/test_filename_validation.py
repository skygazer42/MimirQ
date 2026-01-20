import pytest
from fastapi import HTTPException


@pytest.mark.parametrize(
    "filename",
    [
        "合同（最终版）.pdf",
        "《公司制度》v1.2.pdf",
        "报告【2026】.docx",
        "RAG+评测(含图表)_v2.md",
        "spaces and -_..txt",
    ],
)
def test_validate_filename_allows_common_unicode(filename: str) -> None:
    from app.api.v1.documents import _validate_filename as validate_doc
    from app.api.v1.parsing import _validate_filename as validate_parsing

    validate_doc(filename)
    validate_parsing(filename)


@pytest.mark.parametrize(
    "filename",
    [
        "",
        ".",
        "..",
        "a/b.pdf",
        r"a\\b.pdf",
        "bad\nname.pdf",
        "bad\rname.pdf",
        "bad\tname.pdf",
        "bad\x00name.pdf",
    ],
)
def test_validate_filename_rejects_unsafe(filename: str) -> None:
    from app.api.v1.documents import _validate_filename as validate_doc
    from app.api.v1.parsing import _validate_filename as validate_parsing

    with pytest.raises(HTTPException):
        validate_doc(filename)
    with pytest.raises(HTTPException):
        validate_parsing(filename)

