import pytest
from fastapi import HTTPException


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a.pdf", None),
        ("Docs/a.pdf", "Docs/a.pdf"),
        ("Docs/sub/a.pdf", "Docs/sub/a.pdf"),
        (r"Docs\\sub\\a.pdf", "Docs/sub/a.pdf"),
        (r"C:\\fakepath\\a.pdf", None),
        ("C:/fakepath/a.pdf", None),
        ("a/../b.pdf", None),
    ],
)
def test_normalize_upload_source_path(raw: str, expected: str | None) -> None:
    from app.api.v1.documents import _normalize_upload_source_path

    assert _normalize_upload_source_path(raw) == expected


def test_normalize_upload_source_path_rejects_control_chars() -> None:
    from app.api.v1.documents import _normalize_upload_source_path

    with pytest.raises(HTTPException):
        _normalize_upload_source_path("bad\nname.pdf")

