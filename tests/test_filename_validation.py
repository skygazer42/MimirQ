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
    from app.api.v1.documents import _sanitize_filename as sanitize_doc
    from app.api.v1.parsing import _sanitize_filename as sanitize_parsing

    assert sanitize_doc(filename) == filename
    assert sanitize_parsing(filename) == filename


@pytest.mark.parametrize(
    "filename",
    [
        "",
        ".",
        "..",
        "bad\nname.pdf",
        "bad\rname.pdf",
        "bad\tname.pdf",
        "bad\x00name.pdf",
    ],
)
def test_validate_filename_rejects_unsafe(filename: str) -> None:
    from app.api.v1.documents import _sanitize_filename as sanitize_doc
    from app.api.v1.parsing import _sanitize_filename as sanitize_parsing

    with pytest.raises(HTTPException):
        sanitize_doc(filename)
    with pytest.raises(HTTPException):
        sanitize_parsing(filename)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a/b.pdf", "b.pdf"),
        (r"a\\b.pdf", "b.pdf"),
        (r"C:\\fakepath\\a.pdf", "a.pdf"),
        ("C:/fakepath/a.pdf", "a.pdf"),
    ],
)
def test_sanitize_filename_strips_path_components(raw: str, expected: str) -> None:
    from app.api.v1.documents import _sanitize_filename as sanitize_doc
    from app.api.v1.parsing import _sanitize_filename as sanitize_parsing

    assert sanitize_doc(raw) == expected
    assert sanitize_parsing(raw) == expected

