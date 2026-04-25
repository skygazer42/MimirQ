from __future__ import annotations

from pathlib import Path

import pytest


def test_audio_parser_emits_markdown_reference(tmp_path: Path) -> None:
    from app.parsing.parsers.audio_parser import AudioParser

    audio = tmp_path / "call recording.mp3"
    audio.write_bytes(b"not-a-real-audio")

    docs = AudioParser().parse(audio)
    assert len(docs) == 1
    doc = docs[0]
    assert "call%20recording.mp3" in (doc.page_content or "")
    meta = doc.metadata or {}
    assert meta.get("parser_backend") == "audio"
    assert meta.get("doc_type_kwd") == "audio"
    assert meta.get("asset_base_dir") == str(tmp_path.resolve(strict=False))


def test_audio_parser_rejects_unsupported_extension(tmp_path: Path) -> None:
    from app.parsing.parsers.audio_parser import AudioParser

    bogus = tmp_path / "demo.txt"
    bogus.write_text("not audio", encoding="utf-8")

    with pytest.raises(ValueError, match="AudioParser supports only"):
        AudioParser().parse(bogus)
