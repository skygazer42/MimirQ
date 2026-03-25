from __future__ import annotations

from pathlib import Path

from app.parsing.enrich.formula_ocr import add_formula_latex_blocks


class _FakeResponse:
    def __init__(self, *, status_code: int, headers: dict[str, str], text: str = "", json_body: dict | None = None):
        self.status_code = status_code
        self.headers = headers
        self.text = text
        self._json_body = json_body

    def json(self):  # noqa: ANN201
        if self._json_body is None:
            raise ValueError("no json")
        return self._json_body


def test_formula_ocr_noop_without_api_url(tmp_path: Path) -> None:
    img = tmp_path / "eq.png"
    img.write_bytes(b"not-an-image-but-bytes")
    md = "![formula](eq.png)\n"
    out, added, audit = add_formula_latex_blocks(md, origin_path=tmp_path, api_url="")
    assert out == md
    assert added == 0
    assert audit.applied is False


def test_formula_ocr_inserts_latex_block(monkeypatch, tmp_path: Path) -> None:
    img = tmp_path / "eq.png"
    img.write_bytes(b"fake-bytes")

    def _fake_post(*_args, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return _FakeResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            json_body={"latex": "a^2 + b^2 = c^2"},
        )

    import requests

    monkeypatch.setattr(requests, "post", _fake_post)

    md = "Some text\n\n![formula](eq.png)\n"
    out, added, audit = add_formula_latex_blocks(
        md,
        origin_path=tmp_path,
        api_url="http://example/formula",
        max_images=3,
        max_image_bytes=10_000,
        max_latex_chars=200,
    )
    assert added == 1
    assert "$$ a^2 + b^2 = c^2 $$" in out
    assert audit.applied is True
    assert audit.formulas_added == 1

