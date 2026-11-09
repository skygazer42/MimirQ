import pytest

from app.rag.retrieval.hybrid.dedup import DedupDiversityMixin
from app.rag.retrieval.hybrid.post_process import PostProcessMixin


def test_family_collapse_preserves_a_supplied_zero_family_identifier():
    class Retriever(DedupDiversityMixin):
        hierarchy_family_collapse = True
        retrieval_profile = None

    first = {"chunk_id": "chunk-1", "content": "First.", "metadata": {"hierarchy_family_key": 0}}
    second = {"chunk_id": "chunk-2", "content": "Second.", "metadata": {"hierarchy_family_key": 0}}
    assert Retriever()._collapse_results_by_family([first, second]) == [first]


def test_zero_simhash_is_a_real_hash_instead_of_missing_metadata():
    assert DedupDiversityMixin._simhash64_from_meta({"simhash64": 0}) == 0


def test_enrichment_does_not_hide_a_missing_persisted_document_status():
    with pytest.raises((AttributeError, TypeError)):
        PostProcessMixin._document_ready(
            status=None, doc_meta={}, archived_at=None, disabled_at=None, publication_status="published"
        )
