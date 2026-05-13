from __future__ import annotations

from pathlib import Path

from app.parsing.enrich.formula_ocr import add_formula_latex_blocks


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

    async def _fake_backend_async(**_kwargs):  # noqa: ANN001
        return ("a^2 + b^2 = c^2", "ok_json")

    monkeypatch.setattr(
        "app.parsing.enrich.formula_ocr._call_formula_backend_async",
        _fake_backend_async,
    )

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
