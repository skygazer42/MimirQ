"""
Lightweight SAG engine to run Extract -> Search using local adapters.
"""
from typing import Dict, Optional
from uuid import UUID

from app.core.config import settings
from app.kg.extraction.config import ExtractConfig
from app.kg.extraction.extractor import EventExtractor
from app.kg.search.config import SearchConfig
from app.kg.search.searcher import SAGSearcher
from app.kg.utils import get_logger

logger = get_logger("sag.engine")


class SAGEngine:
    def __init__(self, model_config: Optional[dict] = None):
        self.extractor = EventExtractor(model_config=model_config)
        self.searcher = SAGSearcher()

    async def extract(self, chunk_ids, tenant_id: Optional[UUID] = None):
        config = ExtractConfig(chunk_ids=list(chunk_ids), tenant_id=tenant_id or settings.DEFAULT_TENANT_ID)
        return await self.extractor.extract(config)

    async def search(self, query: str, tenant_id: Optional[UUID] = None) -> Dict:
        config = SearchConfig(query=query, tenant_id=tenant_id or settings.DEFAULT_TENANT_ID)
        return await self.searcher.search(config)
