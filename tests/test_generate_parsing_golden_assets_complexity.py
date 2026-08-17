from pathlib import Path
from typing import Any

import pytest

from scripts import generate_parsing_golden_assets as assets


class _RecordingImage:
    def __init__(self) -> None:
        self.saved_path: Path | None = None

    def save(self, path: Path) -> None:
        self.saved_path = path


class _RecordingDraw:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def text(self, *args: Any, **kwargs: Any) -> None:
        self._record("text", *args, **kwargs)

    def rectangle(self, *args: Any, **kwargs: Any) -> None:
        self._record("rectangle", *args, **kwargs)

    def line(self, *args: Any, **kwargs: Any) -> None:
        self._record("line", *args, **kwargs)


def _record_table(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    **kwargs: Any,
) -> tuple[_RecordingImage, _RecordingDraw]:
    image = _RecordingImage()
    draw = _RecordingDraw()
    monkeypatch.setattr(assets.Image, "new", lambda *_args, **_kwargs: image)
    monkeypatch.setattr(assets.ImageDraw, "Draw", lambda _image: draw)
    output = tmp_path / "nested" / "table.png"

    assets._write_table_page(output, **kwargs)

    assert image.saved_path == output
    assert output.parent.is_dir()
    return image, draw


def test_write_table_page_draws_bordered_grid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _image, draw = _record_table(
        monkeypatch,
        tmp_path,
        header=["Name", "Value"],
        rows=[["Alpha", "1"], ["Beta", "2"]],
    )

    assert [call for call in draw.calls if call[0] == "rectangle"] == [
        ("rectangle", ([72, 72, 828, 246],), {"outline": (100, 116, 139), "width": 2})
    ]
    assert [call for call in draw.calls if call[0] == "line"] == [
        ("line", ([450, 72, 450, 246],), {"fill": (100, 116, 139), "width": 2}),
        ("line", ([72, 130, 828, 130],), {"fill": (100, 116, 139), "width": 2}),
        ("line", ([72, 188, 828, 188],), {"fill": (100, 116, 139), "width": 2}),
    ]
    assert [call[1][1] for call in draw.calls if call[0] == "text"] == [
        "Name",
        "Value",
        "Alpha",
        "1",
        "Beta",
        "2",
        "Rows: 2",
    ]


def test_write_table_page_preserves_borderless_layout_and_preamble(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _image, draw = _record_table(
        monkeypatch,
        tmp_path,
        header=["Name", "Value"],
        rows=[["Alpha", "1"], ["Beta", "2"]],
        title="Quarterly table",
        merged_header="Regional summary",
        borderless=True,
        leading_paragraph=["Prepared for review"],
    )

    assert [call[1][1] for call in draw.calls if call[0] == "text"] == [
        "Quarterly table",
        "Prepared for review",
        "Regional summary",
        "Name   Value",
        "Alpha   1",
        "Beta   2",
        "Rows: 2",
    ]
    assert [call for call in draw.calls if call[0] == "line"] == [
        ("line", ([72, 256, 828, 256],), {"fill": (100, 116, 139), "width": 2}),
        ("line", ([72, 132, 828, 132],), {"fill": (226, 232, 240), "width": 1}),
    ]
