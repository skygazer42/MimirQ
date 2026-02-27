def test_doc_pipeline_hash_prefers_active_pipeline_hash() -> None:
    from app.rag.kg.api.routes import _doc_pipeline_hash

    assert _doc_pipeline_hash({"active_pipeline_hash": "ph_active", "pipeline_hash": "ph_fallback"}) == "ph_active"
    assert _doc_pipeline_hash({"pipeline_hash": "ph_only"}) == "ph_only"
    assert _doc_pipeline_hash({"active_pipeline_hash": "  ph_trim  "}) == "ph_trim"
    assert _doc_pipeline_hash({}) is None
    assert _doc_pipeline_hash(None) is None

