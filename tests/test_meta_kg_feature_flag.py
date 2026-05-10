from app.api.v1 import meta


def test_meta_exposes_kg_enabled_flag(monkeypatch):
    monkeypatch.setattr(meta.settings, "KG_ENABLED", True, raising=False)

    payload = meta.get_meta()

    assert payload["features"]["kg_enabled"] is True
