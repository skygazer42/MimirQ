from __future__ import annotations

from pathlib import Path

import pytest

from app.parsing.utils.artifact_normalizer import normalize_extracted_artifacts


def test_normalize_extracted_artifacts_moves_images_and_rewrites_refs(tmp_path: Path) -> None:
    root = tmp_path / "extract"
    (root / "nested").mkdir(parents=True)
    (root / "imgs").mkdir(parents=True)

    (root / "nested" / "doc.md").write_text(
        '![a](../imgs/p1.png)\n<img src="../imgs/p2.jpg">\n',
        encoding="utf-8",
    )
    (root / "imgs" / "p1.png").write_bytes(b"png")
    (root / "imgs" / "p2.jpg").write_bytes(b"jpg")

    out = normalize_extracted_artifacts(root)

    md = (root / "result.md").read_text(encoding="utf-8")
    assert "images/image_001.png" in md
    assert 'src="images/image_002.jpg"' in md

    assert (root / "images" / "image_001.png").exists()
    assert (root / "images" / "image_002.jpg").exists()
    assert out["image_count"] == 2


def test_normalize_extracted_artifacts_no_images_keeps_markdown(tmp_path: Path) -> None:
    root = tmp_path / "extract"
    root.mkdir(parents=True)
    (root / "note.md").write_text("# Title\n\nhello\n", encoding="utf-8")

    out = normalize_extracted_artifacts(root)
    assert out["image_count"] == 0
    assert (root / "result.md").read_text(encoding="utf-8") == "# Title\n\nhello\n"


def test_normalize_extracted_artifacts_rejects_output_path_traversal(tmp_path: Path) -> None:
    root = tmp_path / "extract"
    root.mkdir(parents=True)
    (root / "result.md").write_text("hello", encoding="utf-8")

    with pytest.raises(ValueError, match="output_markdown_name"):
        normalize_extracted_artifacts(root, output_markdown_name="../escape.md")
