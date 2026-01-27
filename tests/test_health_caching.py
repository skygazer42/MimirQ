from __future__ import annotations


def test_health_cache_hits_within_ttl(monkeypatch) -> None:
    import app.main as main

    monkeypatch.setattr(main, "_HEALTH_CACHE_TTL_SEC", 2.0, raising=False)
    monkeypatch.setattr(main.time, "monotonic", lambda: 100.0)

    key = ("k",)
    payload = {"status": "ok"}
    main._health_cache["ts"] = 99.0
    main._health_cache["key"] = key
    main._health_cache["payload"] = payload

    assert main._get_cached_health_payload(key) == payload


def test_health_cache_misses_when_expired(monkeypatch) -> None:
    import app.main as main

    monkeypatch.setattr(main, "_HEALTH_CACHE_TTL_SEC", 1.0, raising=False)
    monkeypatch.setattr(main.time, "monotonic", lambda: 100.0)

    key = ("k",)
    main._health_cache["ts"] = 98.0
    main._health_cache["key"] = key
    main._health_cache["payload"] = {"status": "ok"}

    assert main._get_cached_health_payload(key) is None


def test_ready_cache_hits_within_ttl(monkeypatch) -> None:
    import app.api.v1.health as health

    monkeypatch.setattr(health, "_READY_CACHE_TTL_SEC", 2.0, raising=False)
    monkeypatch.setattr(health.time, "monotonic", lambda: 100.0)

    key = ("k",)
    payload = {"ok": True}
    health._ready_cache["ts"] = 99.0
    health._ready_cache["key"] = key
    health._ready_cache["payload"] = payload
    health._ready_cache["status"] = 200

    got_payload, got_status = health._get_ready_cache(key)
    assert got_payload == payload
    assert got_status == 200


def test_ready_cache_misses_when_expired(monkeypatch) -> None:
    import app.api.v1.health as health

    monkeypatch.setattr(health, "_READY_CACHE_TTL_SEC", 1.0, raising=False)
    monkeypatch.setattr(health.time, "monotonic", lambda: 100.0)

    key = ("k",)
    health._ready_cache["ts"] = 98.0
    health._ready_cache["key"] = key
    health._ready_cache["payload"] = {"ok": True}
    health._ready_cache["status"] = 200

    got_payload, got_status = health._get_ready_cache(key)
    assert got_payload is None
    assert got_status is None

