from app.api.schemas.settings import MagicPDFConfig


def test_magicpdf_device_mode_default_matches_declared_setting():
    assert MagicPDFConfig().device_mode == ""


def test_get_settings_exposes_unconfigured_magicpdf_device_mode(monkeypatch):
    from app.api.v1 import settings as settings_api

    monkeypatch.setattr(settings_api, "_ensure_settings_readable", lambda *_args: None)
    monkeypatch.setattr(settings_api.settings, "MAGIC_PDF_DEVICE_MODE", "")
    response = settings_api.get_settings(tenant_id=None, account_id="account", db=None)
    assert response.magicpdf.device_mode == ""
