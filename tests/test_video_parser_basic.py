from __future__ import annotations

from pathlib import Path

import pytest


def test_video_parser_emits_markdown_reference(tmp_path: Path) -> None:
    from app.parsing.parsers.video_parser import VideoParser

    video = tmp_path / "demo clip.mp4"
    video.write_bytes(b"not-a-real-video")

    docs = VideoParser().parse(video)
    assert len(docs) == 1
    doc = docs[0]
    assert "demo%20clip.mp4" in (doc.page_content or "")
    meta = doc.metadata or {}
    assert meta.get("parser_backend") == "video"
    assert meta.get("doc_type_kwd") == "video"
    assert meta.get("asset_base_dir") == str(tmp_path.resolve(strict=False))


def test_video_parser_rejects_unsupported_extension(tmp_path: Path) -> None:
    from app.parsing.parsers.video_parser import VideoParser

    bogus = tmp_path / "demo.txt"
    bogus.write_text("not video", encoding="utf-8")

    with pytest.raises(ValueError, match="VideoParser supports only"):
        VideoParser().parse(bogus)
