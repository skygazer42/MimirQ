"""
Lightweight KG engine to run Extract -> Search using local adapters.
"""
from typing import Dict, List, Optional, Sequence
from uuid import UUID

from app.core.config import settings
from app.rag.kg.extraction.config import ExtractConfig
from app.rag.kg.extraction.extractor import EventExtractor
from app.rag.kg.search.config import SearchConfig
from app.rag.kg.search.searcher import KGSearcher
from app.rag.kg.utils import get_logger
from app.models.document import DocumentChunk
from app.types.indexing import IndexingOptions

logger = get_logger("kg.engine")


class KGEngine:
    def __init__(self, model_config: Optional[dict] = None):
        self.extractor = EventExtractor(model_config=model_config)
        self.searcher = KGSearcher()

    async def extract(
        self,
        chunk_ids,
        tenant_id: Optional[UUID] = None,
        *,
        chunks: Optional[Sequence[DocumentChunk]] = None,
        index_options: Optional[IndexingOptions] = None,
    ):
        config = ExtractConfig(chunk_ids=list(chunk_ids), tenant_id=tenant_id or settings.DEFAULT_TENANT_ID)
        return await self.extractor.extract(
            config,
            chunks=chunks,
            index_options=index_options,
        )

    async def search(
        self,
        query: str,
        tenant_id: Optional[UUID] = None,
        *,
        document_ids: Optional[List[UUID]] = None,
    ) -> Dict:
        config = SearchConfig(
            query=query,
            tenant_id=tenant_id or settings.DEFAULT_TENANT_ID,
            document_ids=document_ids,
        )
        return await self.searcher.search(config)
