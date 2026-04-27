from __future__ import annotations


def test_local_bge_v2_m3_reranker_defaults_to_bge_model_and_auto_device(monkeypatch):  # noqa: ANN001
    import app.rag.reranker.local_bge_v2_m3 as mod

    monkeypatch.setattr(mod, "_resolve_device", lambda: "cpu", raising=True)

    reranker = mod.LocalBGEV2M3Reranker()

    assert reranker.model_name == "BAAI/bge-reranker-v2-m3"
    assert reranker.device == "cpu"


def test_factory_resolves_local_bge_v2_m3_provider() -> None:
    from app.rag.reranker.factory import get_reranker

    inst = get_reranker("local_bge_v2_m3")

    assert inst.__class__.__name__ == "LocalBGEV2M3Reranker"
