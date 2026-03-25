from __future__ import annotations

from pathlib import Path

import pytest

from app.parsing.parsers.email_parser import EmailParser


def test_email_parser_extracts_subject_and_body(tmp_path: Path) -> None:
    eml = tmp_path / "sample.eml"
    eml.write_text(
        "\r\n".join(
            [
                "From: Alice <alice@example.com>",
                "To: Bob <bob@example.com>",
                "Subject: Hello World",
                "",
                "This is the body.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    docs = EmailParser().parse(eml)
    assert len(docs) == 1
    doc = docs[0]
    assert "Hello World" in (doc.page_content or "")
    assert "This is the body." in (doc.page_content or "")
    meta = doc.metadata or {}
    assert meta.get("parser_backend") == "email"
    assert meta.get("file_type") == "eml"


def test_email_parser_msg_requires_optional_dependency(tmp_path: Path) -> None:
    msg_path = tmp_path / "sample.msg"
    msg_path.write_bytes(b"dummy msg payload")

    try:
        import extract_msg  # type: ignore  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError) as exc:
            EmailParser().parse(msg_path)
        # The error message is meant to be actionable.
        assert "extract-msg" in str(exc.value) or "extract_msg" in str(exc.value)
    else:
        # If extract-msg is installed, parsing a dummy file should still fail,
        # but it should not error due to missing deps.
        with pytest.raises(RuntimeError):
            EmailParser().parse(msg_path)
