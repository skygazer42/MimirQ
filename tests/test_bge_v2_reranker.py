from __future__ import annotations


def test_bge_v2_reranker_wrapper_resolves_to_local_bge_v2_m3() -> None:
    from app.rag.reranker.bge_v2 import BGEV2Reranker
    from app.rag.reranker.local_bge_v2_m3 import LocalBGEV2M3Reranker

    assert issubclass(BGEV2Reranker, LocalBGEV2M3Reranker)
