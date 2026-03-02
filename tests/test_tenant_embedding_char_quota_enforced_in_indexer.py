from __future__ import annotations

from uuid import UUID

import pytest

from app.services.indexer import Indexer
from app.types.indexing import ChunkInput


def test_indexer_enforces_tenant_embedding_char_quota(monkeypatch):  # noqa: ANN001
    import app.services.tenant_quota_service as tq

    # Force a tiny window so a single small chunk exceeds the limit.
    monkeypatch.setattr(
        tq,
        "check_tenant_embedding_char_quota",
        lambda _db, *, tenant_id: {  # noqa: ARG005
            "enabled": True,
            "mode": "block",
            "limit_chars": 10,
            "used_chars": 9,
            "exceeded": False,
            "window_hours": 24,
        },
        raising=True,
    )

    class _DummyIndexer:
        def __init__(self) -> None:
            # Presence of `_db` triggers quota enforcement. It doesn't need to be a real Session
            # because the check function is patched above.
            self._db = object()

        def _resolve_chunk_vector_enabled(self, _options):  # noqa: ANN001
            return False

        def _resolve_bm25_enabled(self, _options):  # noqa: ANN001
            return False

        def _index_chunk_vectors(self, *_args, **_kwargs):  # noqa: ANN001
            raise AssertionError("unexpected vector indexing on quota failure")

        def _persist_document_chunks(self, **_kwargs):  # noqa: ANN001
            raise AssertionError("unexpected chunk persistence on quota failure")

        def _update_bm25_for_chunks(self, **_kwargs):  # noqa: ANN001
            raise AssertionError("unexpected BM25 update on quota failure")

    dummy = _DummyIndexer()
    doc_id = UUID(int=1)
    tenant_id = UUID(int=2)

    with pytest.raises(tq.TenantQuotaExceededError) as excinfo:
        Indexer.index_chunks(  # type: ignore[misc]
            dummy,
            document_id=doc_id,
            tenant_id=tenant_id,
            chunks=[ChunkInput(content="hello", metadata={})],  # 5 chars; used 9 + 5 > 10
            default_source="doc.txt",
            commit=False,
            options=None,
        )

    assert excinfo.value.quota == "embedding_chars"
