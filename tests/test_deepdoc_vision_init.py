
from types import SimpleNamespace

import pytest
from PIL import Image

from app.deepdoc import vision


class _FakeImage:
    def __init__(self, name: str) -> None:
        self.name = name

    def convert(self, mode: str) -> "_FakeImage":
        assert mode == "RGB"
        return self


def test_init_in_out_preserves_pdf_reset_and_output_order(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    input_dir = tmp_path / "inputs"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    first = input_dir / "first.png"
    pdf = input_dir / "pages.pdf"
    last = input_dir / "last.jpg"
    for path in (first, pdf, last):
        path.write_bytes(path.name.encode())

    page_images = [_FakeImage("page-0"), _FakeImage("page-1")]
    pdf_handle = SimpleNamespace(
        pages=[
            SimpleNamespace(to_image=lambda resolution, image=image: SimpleNamespace(annotated=image))
            for image in page_images
        ],
        close=lambda: None,
    )
    monkeypatch.setattr(vision, "traversal_files", lambda _base: iter((str(first), str(pdf), str(last))))
    monkeypatch.setattr(vision.pdfplumber, "open", lambda _path: pdf_handle)
    monkeypatch.setattr(Image, "open", lambda stream: _FakeImage(stream.getvalue().decode()))

    images, outputs = vision.init_in_out(SimpleNamespace(inputs=str(input_dir), output_dir=str(output_dir)))

    assert [image.name for image in images] == ["page-0", "page-1", "last.jpg"]
    assert outputs == [
        str(output_dir / "first.png"),
        str(output_dir / "pages.pdf_0.jpg"),
        str(output_dir / "pages.pdf_1.jpg"),
        str(output_dir / "last.jpg"),
    ]


def test_init_in_out_closes_pdf_when_page_rendering_fails(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = tmp_path / "pages.pdf"
    pdf.write_bytes(b"pdf")
    closed: list[bool] = []

    def fail_page(*, resolution: int):
        assert resolution == 216
        raise RuntimeError("render failed")

    pdf_handle = SimpleNamespace(
        pages=[SimpleNamespace(to_image=fail_page)],
        close=lambda: closed.append(True),
    )
    monkeypatch.setattr(vision.pdfplumber, "open", lambda _path: pdf_handle)

    with pytest.raises(RuntimeError, match="render failed"):
        vision.init_in_out(SimpleNamespace(inputs=str(pdf), output_dir=str(tmp_path / "outputs")))

    assert closed == [True]


def test_init_in_out_skips_unreadable_images(tmp_path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    image_path = tmp_path / "broken.png"
    image_path.write_bytes(b"broken")
    monkeypatch.setattr(Image, "open", lambda _stream: (_ for _ in ()).throw(ValueError("bad image")))

    images, outputs = vision.init_in_out(SimpleNamespace(inputs=str(image_path), output_dir=str(tmp_path / "outputs")))

    assert images == []
    assert outputs == []
    assert "bad image" in capsys.readouterr().err
