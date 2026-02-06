from __future__ import annotations


def test_build_db_profile_cache_key_is_stable_and_scoped():
    from app.services.db_catalog_profile_cache import build_db_profile_cache_key  # noqa: WPS433

    key = build_db_profile_cache_key(
        tenant_id="t1",
        dataset_id="d1",
        entitlement_hash="e1",
        table_fingerprint="f1",
        profile_version=3,
    )
    assert key == "db_profile:v3:t1:d1:e1:f1"


def test_profile_cache_respects_ttl(monkeypatch):  # noqa: ANN001
    import app.services.db_catalog_profile_cache as cache

    key = cache.build_db_profile_cache_key(
        tenant_id="t1",
        dataset_id="d1",
        entitlement_hash="e1",
        table_fingerprint="f1",
        profile_version=1,
    )

    now = {"t": 100.0}

    def fake_monotonic() -> float:
        return float(now["t"])

    monkeypatch.setattr(cache.time, "monotonic", fake_monotonic)

    cache.set_cached_db_profile(key, {"ok": True})
    assert cache.get_cached_db_profile(key, ttl_sec=10.0) == {"ok": True}

    now["t"] = 120.0
    assert cache.get_cached_db_profile(key, ttl_sec=10.0) is None

