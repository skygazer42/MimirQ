
from app.rag.reranker.local_bge_v2_m3 import LocalBGEV2M3Reranker


class BGEV2Reranker(LocalBGEV2M3Reranker):
    """Backward-compatible wrapper for the BGE v2 reranker slot."""


__all__ = ["BGEV2Reranker"]
