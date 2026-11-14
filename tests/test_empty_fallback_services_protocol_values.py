from types import SimpleNamespace

import pytest

from app.services import saml_service, web_crawler


@pytest.mark.parametrize(
    "normalize",
    [saml_service._parse_iso_datetime, saml_service._normalize_path, saml_service._first_pem_certificate_b64],
)
def test_invalid_saml_values_do_not_select_the_absent_input_behavior(normalize):
    with pytest.raises(AttributeError):
        normalize(False)


def test_invalid_saml_provider_selector_cannot_select_the_only_provider(monkeypatch):
    monkeypatch.setattr(saml_service, "_load_saml_providers", lambda: [SimpleNamespace(id="provider")])
    with pytest.raises(AttributeError):
        saml_service._resolve_provider(False)


@pytest.mark.parametrize("text", [0, False])
def test_invalid_crawl_text_cannot_become_a_url_only_sync_token(text):
    with pytest.raises(AttributeError):
        web_crawler._build_page_sync_token(url="https://example.com", text=text, content_type=None)


def test_a_real_absent_saml_redirect_path_uses_the_documented_root_path():
    assert saml_service._normalize_path(None) == "/"


def test_a_real_absent_crawl_body_keeps_the_url_fingerprint():
    assert web_crawler._build_page_sync_token(
        url="https://example.com", text=None, content_type=None
    ).startswith("url_sha256:")
