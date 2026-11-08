from app.api.schemas.settings import MagicPDFConfig


def test_magicpdf_device_mode_default_matches_declared_setting():
    assert MagicPDFConfig().device_mode == ""
