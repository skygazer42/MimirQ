from __future__ import annotations


def test_asset_cache_control_returns_no_store_for_token_urls() -> None:
    import app.api.v1.documents as documents_module

    assert documents_module._asset_cache_control(token_in_url=True, max_age=3600) == "no-store"


def test_asset_cache_control_uses_private_cache_then_no_cache() -> None:
    import app.api.v1.documents as documents_module

    assert documents_module._asset_cache_control(token_in_url=False, max_age=3600) == "private, max-age=3600"
    assert documents_module._asset_cache_control(token_in_url=False, max_age=0) == "no-cache"
