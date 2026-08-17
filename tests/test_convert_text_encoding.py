from __future__ import annotations

from pathlib import Path

from scripts.convert_text_encoding import convert_encoding


def test_convert_encoding_writes_utf8_and_does_not_recurse_into_target(tmp_path: Path, capsys) -> None:
    source = tmp_path / "source"
    target = source / "output"
    source.mkdir()
    (source / "alpha.txt").write_bytes("café".encode("latin-1"))
    target.mkdir()
    (target / "already.txt").write_text("leave me", encoding="utf-8")

    result = convert_encoding(
        source_dir=source,
        target_dir=target,
        extensions={".txt"},
        clean_target=False,
        dry_run=False,
    )

    assert result == 0
    assert (target / "alpha.txt").read_text(encoding="utf-8") == "café"
    assert not (target / "output").exists()
    assert "converted=1 skipped=0" in capsys.readouterr().out


def test_convert_encoding_dry_run_reports_clean_without_deleting(tmp_path: Path, capsys) -> None:
    source = tmp_path / "source"
    target = source / "output"
    source.mkdir()
    (source / "alpha.txt").write_text("alpha", encoding="utf-8")
    target.mkdir()
    marker = target / "marker.txt"
    marker.write_text("keep", encoding="utf-8")

    result = convert_encoding(
        source_dir=source,
        target_dir=target,
        extensions={".txt"},
        clean_target=True,
        dry_run=True,
    )

    output = capsys.readouterr().out
    assert result == 0
    assert marker.exists()
    assert f"[dry-run] rm -rf {target}" in output
    assert "converted=1 skipped=0" in output


def test_convert_encoding_counts_write_failures_and_continues(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    (source / "alpha.txt").write_text("alpha", encoding="utf-8")
    original_write_text = Path.write_text

    def fail_target_write(path: Path, *args, **kwargs):
        if target in path.parents:
            raise OSError("disk full")
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_target_write)

    result = convert_encoding(
        source_dir=source,
        target_dir=target,
        extensions={".txt"},
        clean_target=False,
        dry_run=False,
    )

    assert result == 1
    assert "converted=0 skipped=1" in capsys.readouterr().out
