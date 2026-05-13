from __future__ import annotations

from pathlib import Path

import pytest


def test_vlm_image_caption_missing_url_is_noop(tmp_path: Path):
    from app.parsing.enrich.vlm_image_caption import add_vlm_image_captions

    md = "![](cat.png)\n"
    out, added, audit = add_vlm_image_captions(md, origin_path=tmp_path, api_url="")
    assert out == md
    assert added == 0
    assert audit.applied is False
    assert audit.error == "missing_api_url"


def test_vlm_image_caption_uses_descriptive_alt_without_http_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app.parsing.enrich import vlm_image_caption

    (tmp_path / "cat.png").write_bytes(b"not-an-image-but-ok")

    async def _boom_async(**_kwargs):  # noqa: ANN001
        raise AssertionError("caption backend should not be called for descriptive alt text")

    monkeypatch.setattr(vlm_image_caption, "_call_caption_backend_async", _boom_async)

    md = "![A cute kitten](cat.png)\n"
    out, added, audit = vlm_image_caption.add_vlm_image_captions(
        md,
        origin_path=tmp_path,
        api_url="http://example.com/caption",
        max_images=10,
    )
    assert "Image caption: A cute kitten" in out
    assert added == 1
    assert audit.captions_added == 1
    assert audit.images_attempted == 0
    assert audit.images_succeeded == 0
    assert audit.applied is True


def test_vlm_image_caption_calls_backend_for_generic_alt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app.parsing.enrich import vlm_image_caption

    (tmp_path / "cat.png").write_bytes(b"fake-bytes")

    async def _caption_backend_async(**_kwargs):  # noqa: ANN001
        return ("A simple chart of revenue growth", "ok_json")

    monkeypatch.setattr(vlm_image_caption, "_call_caption_backend_async", _caption_backend_async)

    md = "![](cat.png)\n"
    out, added, audit = vlm_image_caption.add_vlm_image_captions(
        md,
        origin_path=tmp_path,
        api_url="http://example.com/caption",
        max_images=10,
    )
    assert "Image caption: A simple chart of revenue growth" in out
    assert added == 1
    assert audit.images_attempted == 1
    assert audit.images_succeeded == 1
    assert audit.captions_added == 1
    assert audit.applied is True


def test_vlm_image_caption_blocks_path_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app.parsing.enrich import vlm_image_caption

    async def _boom_async(**_kwargs):  # noqa: ANN001
        raise AssertionError("caption backend should not be called when the image path is outside origin")

    monkeypatch.setattr(vlm_image_caption, "_call_caption_backend_async", _boom_async)

    md = "![](../secret.png)\n"
    out, added, audit = vlm_image_caption.add_vlm_image_captions(
        md,
        origin_path=tmp_path / "doc.md",
        api_url="http://example.com/caption",
        max_images=10,
    )
    # Fallback to filename only (no file read, no HTTP).
    assert "Image caption: secret.png" in out
    assert added == 1
    assert audit.images_attempted == 0
    assert audit.captions_added == 1
