from types import SimpleNamespace

import pytest

from app.rag.retrieval.context_expansion import _neighbor_item
from app.rag.retrieval.corpus_index import CorpusIndex
from app.rag.retrieval.planner import _metadata_terms


def test_neighbor_projection_exposes_a_missing_required_database_identity():
    with pytest.raises(AttributeError):
        _neighbor_item(chunk=SimpleNamespace(content="Valid content"), result={}, anchor_chunk_id="anchor")


def test_corpus_projection_rejects_missing_required_passage_content():
    with pytest.raises((TypeError, ValueError)):
        CorpusIndex._document_from_chunk_row(("chunk", None, {}, "tenant", "document", 0, None, None))


def test_policy_metadata_terms_preserve_supplied_falsy_scalar_candidates():
    assert _metadata_terms([None, 0, False, "Valid"]) == ("0", "False", "Valid")
