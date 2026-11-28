import zipfile

import pytest

from app.rag.ingestion.parsing.parsers.mineru_parser import MinerUResultParser


def test_mineru_zip_extracts_contents_without_archive_root(tmp_path) -> None:
    archive = tmp_path / "result.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("document/result.md", "ok")

    output = tmp_path / "output"
    MinerUResultParser()._extract_zip_no_root(archive, output, "document/")
    assert (output / "result.md").read_text() == "ok"


def test_mineru_zip_rejects_path_traversal(tmp_path) -> None:
    archive = tmp_path / "malicious.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escaped.txt", "bad")

    with pytest.raises(ValueError, match="traversal"):
        MinerUResultParser()._extract_zip_no_root(archive, tmp_path / "output", None)
    assert not (tmp_path / "escaped.txt").exists()
