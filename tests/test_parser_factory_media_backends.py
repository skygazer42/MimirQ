from __future__ import annotations


def test_parser_factory_routes_video_files_to_video_backend() -> None:
    from app.parsing.factory import ParserFactory

    backend = ParserFactory().resolve_backend(".mp4", "auto")
    assert backend == "video"


def test_parser_factory_routes_audio_files_to_audio_backend() -> None:
    from app.parsing.factory import ParserFactory

    backend = ParserFactory().resolve_backend(".mp3", "auto")
    assert backend == "audio"
