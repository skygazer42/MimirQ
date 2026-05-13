from pathlib import Path


def test_gitattributes_tracks_onnx_with_lfs() -> None:
    text = Path(".gitattributes").read_text(encoding="utf-8")
    assert "*.onnx filter=lfs diff=lfs merge=lfs -text" in text
