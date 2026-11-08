import pytest


@pytest.mark.parametrize("model", [None, ""])
def test_dify_signature_preserves_zero_boost_budget_and_optional_model(model, monkeypatch):
    from app.api.v1 import integrations_dify as module

    monkeypatch.setattr(module.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_MAX_PROMOTED", 0)
    monkeypatch.setattr(module.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_ENABLED", False)
    monkeypatch.setattr(module.settings, "RERANKER_MODEL", model)
    signature = module._dify_response_cache_settings_signature()
    assert signature["kg_chunk_boost_max_promoted_default"] == 0
    assert signature["kg_chunk_boost_default"] is False
    assert signature["reranker_model"] == ""


def test_zero_redirect_budget_disallows_all_redirect_hops(monkeypatch):
    from app.api.utils import url_ingest

    monkeypatch.setattr(url_ingest.settings, "URL_INGEST_MAX_REDIRECTS", 0)
    options = url_ingest._download_options(None)
    assert options.max_redirects == 0
