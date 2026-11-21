"""Recall candidates through vector, BM25 and lexical channels.

HybridRetriever owns the request contract and final permission trimming.
CorpusIndex owns shared corpus artifacts. Fusion and ordering algorithms live
in retrieval.ranking; model rerankers live in retrieval.reranking.
"""
