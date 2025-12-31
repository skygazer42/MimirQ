import pytest

from app.core.config import settings
from app.parsing.routing import choose_pdf_backend


def _set_flags(monkeypatch: pytest.MonkeyPatch, **kwargs):
    for k, v in kwargs.items():
        monkeypatch.setattr(settings, k, v)


def test_choose_pdf_backend_honors_requested():
    quality = {"score": 0.0, "is_scanned": True}
    assert choose_pdf_backend(quality, "MinerU") == "mineru"


def test_choose_pdf_backend_high_quality_prefers_markitdown(monkeypatch: pytest.MonkeyPatch):
    _set_flags(
        monkeypatch,
        MARKITDOWN_ENABLED=True,
        MINERU_ENABLED=False,
        DEEPDOC_ENABLED=False,
        MINERU_API_TOKEN="",
        MINERU_LOCAL_SERVER_URL="",
    )
    quality = {"score": 0.95, "is_scanned": False}
    assert choose_pdf_backend(quality, None) == "markitdown"


def test_choose_pdf_backend_high_quality_falls_back_to_basic(monkeypatch: pytest.MonkeyPatch):
    _set_flags(
        monkeypatch,
        MARKITDOWN_ENABLED=False,
        MINERU_ENABLED=False,
        DEEPDOC_ENABLED=False,
        MINERU_API_TOKEN="",
        MINERU_LOCAL_SERVER_URL="",
    )
    quality = {"score": 0.95, "is_scanned": False}
    assert choose_pdf_backend(quality, None) == "basic"


def test_choose_pdf_backend_scanned_prefers_mineru_when_configured(monkeypatch: pytest.MonkeyPatch):
    _set_flags(
        monkeypatch,
        MARKITDOWN_ENABLED=False,
        MINERU_ENABLED=True,
        MINERU_API_TOKEN="token",
        MINERU_LOCAL_SERVER_URL="",
        DEEPDOC_ENABLED=True,
    )
    quality = {"score": 0.2, "is_scanned": True}
    assert choose_pdf_backend(quality, None) == "mineru"


def test_choose_pdf_backend_scanned_falls_back_to_deepdoc(monkeypatch: pytest.MonkeyPatch):
    _set_flags(
        monkeypatch,
        MARKITDOWN_ENABLED=False,
        MINERU_ENABLED=True,
        MINERU_API_TOKEN="",
        MINERU_LOCAL_SERVER_URL="",
        DEEPDOC_ENABLED=True,
    )
    quality = {"score": 0.2, "is_scanned": True}
    assert choose_pdf_backend(quality, None) == "deepdoc"


def test_choose_pdf_backend_mid_prefers_deepdoc(monkeypatch: pytest.MonkeyPatch):
    _set_flags(
        monkeypatch,
        DEEPDOC_ENABLED=True,
        MINERU_ENABLED=True,
        MINERU_API_TOKEN="token",
        MINERU_LOCAL_SERVER_URL="",
        MARKITDOWN_ENABLED=True,
    )
    quality = {"score": 0.65, "is_scanned": False}
    assert choose_pdf_backend(quality, None) == "deepdoc"

