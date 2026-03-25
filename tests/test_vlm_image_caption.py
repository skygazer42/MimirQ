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

    def _boom(*args, **kwargs):  # noqa: ANN001, D401
        raise AssertionError("requests.post should not be called for descriptive alt text")

    monkeypatch.setattr(vlm_image_caption.requests, "post", _boom)

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

    class _Resp:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self):  # noqa: D401
            return {"caption": "A simple chart of revenue growth"}

        @property
        def text(self):  # noqa: D401
            return ""

    def _post(*args, **kwargs):  # noqa: ANN001, D401
        return _Resp()

    monkeypatch.setattr(vlm_image_caption.requests, "post", _post)

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

    def _boom(*args, **kwargs):  # noqa: ANN001, D401
        raise AssertionError("requests.post should not be called when the image path is outside origin")

    monkeypatch.setattr(vlm_image_caption.requests, "post", _boom)

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

