from __future__ import annotations


def test_preprocess_file_text_and_html_steps(tmp_path):  # noqa: ANN001
    from pathlib import Path

    from app.parsing.preprocess.file_preprocessor import preprocess_file

    src = tmp_path / "a.html"
    # Include BOM + CRLF + script/style + comment.
    raw = (
        "\ufeff<html>\r\n"
        "<nav>top nav</nav>\r\n"
        "<!-- comment -->\r\n"
        "<style>body{color:red}</style>\r\n"
        "<script>alert(1)</script>\r\n"
        "<body>hi \t \r\n</body>\r\n"
        "</html>\r\n"
    ).encode("utf-8")
    src.write_bytes(raw)

    res = preprocess_file(
        input_path=Path(src),
        steps=[
            {"id": "text.reencode_utf8", "params": {}},
            {"id": "text.strip_bom", "params": {}},
            {"id": "text.normalize_newlines", "params": {}},
            {"id": "text.collapse_blank_lines", "params": {}},
            {"id": "text.trim_trailing_whitespace", "params": {}},
            {"id": "html.strip_scripts_styles", "params": {}},
            {"id": "html.strip_comments", "params": {}},
            {"id": "html.strip_boilerplate_tags", "params": {}},
        ],
        max_text_bytes=50_000,
    )

    assert res.changed is True
    out_path = Path(res.output_path)
    assert out_path.exists()
    out = out_path.read_text("utf-8", errors="replace")
    assert "<nav" not in out.lower()
    assert "<script" not in out.lower()
    assert "<style" not in out.lower()
    assert "<!--" not in out
    assert "\r" not in out
    assert res.steps and hasattr(res.steps[0], "bytes_before")
    for s in res.steps:
        assert int(getattr(s, "bytes_before", 0) or 0) >= 0
        assert int(getattr(s, "bytes_after", 0) or 0) >= 0
        assert int(getattr(s, "elapsed_ms", 0) or 0) >= 0


def test_preprocess_file_skips_non_text(tmp_path):  # noqa: ANN001
    from pathlib import Path

    from app.parsing.preprocess.file_preprocessor import preprocess_file

    src = tmp_path / "a.pdf"
    src.write_bytes(b"%PDF-1.4\n%fake\n")

    res = preprocess_file(
        input_path=Path(src),
        steps=[{"id": "text.normalize_newlines", "params": {}}],
        max_text_bytes=10_000,
    )
    assert res.changed is False
    assert "non_text_file_skipped" in (res.warnings or [])


def test_preprocess_file_respects_size_cap(tmp_path):  # noqa: ANN001
    from pathlib import Path

    from app.parsing.preprocess.file_preprocessor import preprocess_file

    src = tmp_path / "a.txt"
    src.write_bytes(b"a" * 100)

    res = preprocess_file(
        input_path=Path(src),
        steps=[{"id": "text.normalize_newlines", "params": {}}],
        max_text_bytes=10,
    )
    assert res.changed is False
    assert any("text_too_large_skipped" in w for w in (res.warnings or []))


def test_preprocess_file_new_text_steps(tmp_path):  # noqa: ANN001
    from pathlib import Path

    from app.parsing.preprocess.file_preprocessor import preprocess_file

    src = tmp_path / "a.txt"
    # Includes: zero-width space, soft hyphen, NUL control char, and full-width Latin letters.
    raw = ("A\u200bB\u00adC\x00\nＡＢＣ\n").encode("utf-8", errors="replace")
    src.write_bytes(raw)

    res = preprocess_file(
        input_path=Path(src),
        steps=[
            {"id": "text.remove_zero_width", "params": {}},
            {"id": "text.remove_control_chars", "params": {}},
            {"id": "text.collapse_blank_lines", "params": {}},
            {"id": "text.normalize_unicode_nfc", "params": {}},
            {"id": "text.normalize_unicode_nfkc", "params": {}},
        ],
        max_text_bytes=50_000,
    )

    assert res.changed is True
    out = Path(res.output_path).read_text("utf-8", errors="replace")
    assert "\u200b" not in out
    assert "\u00ad" not in out
    assert "\x00" not in out
    # NFKC should normalize full-width letters to ASCII.
    assert "ABC" in out
