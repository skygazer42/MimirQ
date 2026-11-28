from types import SimpleNamespace


def test_zero_overlap_is_preserved_in_precheck_suggestion(monkeypatch):
    from app.services.datasets.precheck import ingestion_suggestions as suggestion

    monkeypatch.setattr(suggestion.settings, "PRECHECK_SUGGEST_CHUNK_SIZE", True)
    monkeypatch.setattr(suggestion.settings, "CHUNK_SIZE", 1000)
    monkeypatch.setattr(suggestion.settings, "CHUNK_OVERLAP", 0)
    result = suggestion._chunk_size_note(SimpleNamespace(token_p50=100, token_p90=500))
    assert "chunk_overlap=0" in result
