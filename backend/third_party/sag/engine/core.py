"""
Lightweight SAG engine to run Extract -> Search using local adapters.
"""
from typing import Dict, Optional
from uuid import UUID

from app.core.config import settings
from third_party.sag.modules.extract.config import ExtractConfig
from third_party.sag.modules.extract.extractor import EventExtractor
from third_party.sag.modules.search.config import SearchConfig
from third_party.sag.modules.search.searcher import SAGSearcher
from third_party.sag.utils import get_logger

logger = get_logger("sag.engine")


class SAGEngine:
    def __init__(self, model_config: Optional[dict] = None):
        self.extractor = EventExtractor(model_config=model_config)
        self.searcher = SAGSearcher()

    async def extract(self, chunk_ids, tenant_id: Optional[UUID] = None):
        config = ExtractConfig(chunk_ids=list(chunk_ids), tenant_id=tenant_id or settings.DEFAULT_TENANT_ID)
        return await self.extractor.extract(config)

    async def search(
        self,
        query: str,
        tenant_id: Optional[UUID] = None,
        document_ids: Optional[list[UUID]] = None,
    ) -> Dict:
        config = SearchConfig(
            query=query,
            tenant_id=tenant_id or settings.DEFAULT_TENANT_ID,
            document_ids=document_ids,
        )
        return await self.searcher.search(config)
