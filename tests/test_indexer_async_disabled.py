from __future__ import annotations

from uuid import UUID

import pytest

from app.services.indexer import Indexer
from app.types.indexing import ChunkInput


@pytest.mark.asyncio
async def test_index_chunks_async_is_disabled() -> None:
    class _DummyIndexer:
        pass

    with pytest.raises(RuntimeError) as exc:
        await Indexer.index_chunks_async(  # type: ignore[misc]
            _DummyIndexer(),
            document_id=UUID(int=1),
            tenant_id=UUID(int=2),
            chunks=[ChunkInput(content="hello", metadata={})],
            default_source="orig.pdf",
            commit=False,
            options=None,
        )

    assert "index_chunks_async" in str(exc.value).lower()

