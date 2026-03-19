from __future__ import annotations

from pathlib import Path

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

