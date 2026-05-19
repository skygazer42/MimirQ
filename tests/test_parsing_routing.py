import pytest

from app.core.config import settings
import app.parsing.routing as routing
from app.parsing.routing import choose_pdf_backend, should_attempt_pdf_fallback


def _set_flags(monkeypatch: pytest.MonkeyPatch, **kwargs):
    defaults = {
        "MARKITDOWN_ENABLED": False,
        "MINERU_ENABLED": False,
        "MINERU_API_TOKEN": "",
        "MINERU_LOCAL_SERVER_URL": "",
        "DEEPDOC_ENABLED": False,
        "DOCLING_ENABLED": False,
        "MAGIC_PDF_ENABLED": False,
        "MAGIC_PDF_CLI": "magic-pdf",
        "DEEPSEEK_OCR_ENABLED": False,
        "SILICONFLOW_API_KEY": "",
        "QIANFAN_OCR_ENABLED": False,
        "QIANFAN_OCR_API_URL": "",
        "ETL4LLM_ENABLED": False,
        "ETL4LLM_API_URL": "",
    }
    defaults.update(kwargs)
    for k, v in defaults.items():
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


def test_choose_pdf_backend_honors_magicpdf_alias(monkeypatch: pytest.MonkeyPatch):
    _set_flags(monkeypatch, MAGIC_PDF_ENABLED=True, MAGIC_PDF_CLI="magic-pdf")
    # Even when not installed, requested backend should be normalized.
    quality = {"score": 0.0, "is_scanned": True}
    assert choose_pdf_backend(quality, "magic-pdf") == "magicpdf"


def test_choose_pdf_backend_honors_etl4llm_legacy_alias(monkeypatch: pytest.MonkeyPatch):
    quality = {"score": 0.0, "is_scanned": True}
    assert choose_pdf_backend(quality, "bisheng") == "etl4llm"


def test_choose_pdf_backend_scanned_prefers_deepseek_ocr_when_enabled(monkeypatch: pytest.MonkeyPatch):
    _set_flags(
        monkeypatch,
        MINERU_ENABLED=False,
        MINERU_API_TOKEN="",
        MINERU_LOCAL_SERVER_URL="",
        DEEPDOC_ENABLED=True,
        DEEPSEEK_OCR_ENABLED=True,
        SILICONFLOW_API_KEY="k",
    )
    quality = {"score": 0.2, "is_scanned": True}
    assert choose_pdf_backend(quality, None) == "deepseek_ocr"


def test_choose_pdf_backend_scanned_prefers_qianfan_ocr_when_enabled(monkeypatch: pytest.MonkeyPatch):
    _set_flags(
        monkeypatch,
        MINERU_ENABLED=False,
        MINERU_API_TOKEN="",
        MINERU_LOCAL_SERVER_URL="",
        DEEPSEEK_OCR_ENABLED=False,
        SILICONFLOW_API_KEY="",
        QIANFAN_OCR_ENABLED=True,
        QIANFAN_OCR_API_URL="http://localhost:2090/convert",
        ETL4LLM_ENABLED=True,
        ETL4LLM_API_URL="http://localhost:10001/v1/etl4llm/predict",
        DEEPDOC_ENABLED=True,
    )
    quality = {"score": 0.2, "is_scanned": True}
    assert choose_pdf_backend(quality, None) == "qianfan_ocr"


def test_choose_pdf_backend_high_quality_prefers_etl4llm_when_docling_disabled(monkeypatch: pytest.MonkeyPatch):
    _set_flags(
        monkeypatch,
        DOCLING_ENABLED=False,
        ETL4LLM_ENABLED=True,
        ETL4LLM_API_URL="http://localhost:10001/v1/etl4llm/predict",
        MARKITDOWN_ENABLED=True,
        DEEPDOC_ENABLED=False,
        MINERU_ENABLED=False,
        MINERU_API_TOKEN="",
        MINERU_LOCAL_SERVER_URL="",
    )
    quality = {"score": 0.95, "is_scanned": False}
    assert choose_pdf_backend(quality, None) == "etl4llm"


def test_choose_pdf_backend_scanned_prefers_etl4llm_when_enabled(monkeypatch: pytest.MonkeyPatch):
    _set_flags(
        monkeypatch,
        MINERU_ENABLED=False,
        MINERU_API_TOKEN="",
        MINERU_LOCAL_SERVER_URL="",
        DEEPSEEK_OCR_ENABLED=False,
        SILICONFLOW_API_KEY="",
        DEEPDOC_ENABLED=False,
        DOCLING_ENABLED=False,
        MAGIC_PDF_ENABLED=False,
        ETL4LLM_ENABLED=True,
        ETL4LLM_API_URL="http://localhost:10001/v1/etl4llm/predict",
    )
    quality = {"score": 0.2, "is_scanned": True}
    assert choose_pdf_backend(quality, None) == "etl4llm"


def test_choose_pdf_backend_scanned_prefers_magicpdf_when_available(monkeypatch: pytest.MonkeyPatch):
    import shutil

    _set_flags(
        monkeypatch,
        MARKITDOWN_ENABLED=False,
        MINERU_ENABLED=False,
        MINERU_API_TOKEN="",
        MINERU_LOCAL_SERVER_URL="",
        DEEPDOC_ENABLED=False,
        MAGIC_PDF_ENABLED=True,
        MAGIC_PDF_CLI="magic-pdf",
    )
    monkeypatch.setattr(shutil, "which", lambda _cmd: "/usr/bin/magic-pdf")
    monkeypatch.setattr(routing, "resolve_magicpdf_models_dir", lambda _configured=None: object())
    quality = {"score": 0.2, "is_scanned": True}
    assert choose_pdf_backend(quality, None) == "magicpdf"


def test_choose_pdf_backend_scanned_skips_magicpdf_without_models(monkeypatch: pytest.MonkeyPatch):
    import shutil

    _set_flags(
        monkeypatch,
        MARKITDOWN_ENABLED=True,
        MINERU_ENABLED=False,
        MINERU_API_TOKEN="",
        MINERU_LOCAL_SERVER_URL="",
        DEEPDOC_ENABLED=False,
        MAGIC_PDF_ENABLED=True,
        MAGIC_PDF_CLI="magic-pdf",
    )
    monkeypatch.setattr(shutil, "which", lambda _cmd: "/usr/bin/magic-pdf")
    monkeypatch.setattr(routing, "resolve_magicpdf_models_dir", lambda _configured=None: None)
    quality = {"score": 0.2, "is_scanned": True}
    assert choose_pdf_backend(quality, None) == "markitdown"


def test_choose_pdf_backend_scanned_prefers_deepdoc_over_magicpdf(monkeypatch: pytest.MonkeyPatch):
    import shutil

    _set_flags(
        monkeypatch,
        MARKITDOWN_ENABLED=False,
        MINERU_ENABLED=False,
        MINERU_API_TOKEN="",
        MINERU_LOCAL_SERVER_URL="",
        DEEPDOC_ENABLED=True,
        MAGIC_PDF_ENABLED=True,
        MAGIC_PDF_CLI="magic-pdf",
    )
    monkeypatch.setattr(shutil, "which", lambda _cmd: "/usr/bin/magic-pdf")
    monkeypatch.setattr(routing, "resolve_magicpdf_models_dir", lambda _configured=None: object())
    quality = {"score": 0.2, "is_scanned": True}
    assert choose_pdf_backend(quality, None) == "deepdoc"


def test_should_attempt_pdf_fallback_when_parse_score_is_below_threshold() -> None:
    assert (
        should_attempt_pdf_fallback(
            grade="warn",
            parse_score=0.42,
            content_chars=500,
            min_content_chars=120,
            min_parse_score=0.6,
        )
        is True
    )


def test_should_attempt_pdf_fallback_when_content_is_too_short_even_with_ok_score() -> None:
    assert (
        should_attempt_pdf_fallback(
            grade="pass",
            parse_score=0.9,
            content_chars=80,
            min_content_chars=120,
            min_parse_score=0.6,
        )
        is True
    )


def test_should_not_attempt_pdf_fallback_when_quality_is_good() -> None:
    assert (
        should_attempt_pdf_fallback(
            grade="pass",
            parse_score=0.91,
            content_chars=500,
            min_content_chars=120,
            min_parse_score=0.6,
        )
        is False
    )
