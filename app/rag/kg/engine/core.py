"""
Lightweight KG engine to run Extract -> Search using local adapters.
"""
from typing import Dict, List, Optional, Sequence
from uuid import UUID

from app.core.config import settings
from app.models.document import DocumentChunk
from app.rag.kg.extraction.config import ExtractConfig
from app.rag.kg.extraction.extractor import EventExtractor
from app.rag.kg.search.config import SearchConfig
from app.rag.kg.search.searcher import KGSearcher
from app.rag.kg.utils import get_logger
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
        prompt_template_id: Optional[UUID] = None,
        prompt_template_key: Optional[str] = None,
        prompt_ab_experiment_key: Optional[str] = None,
        ab_user_key: Optional[str] = None,
        extract_relations: Optional[bool] = None,
        extract_skills: Optional[bool] = None,
        replace_existing: Optional[bool] = None,
        prune_orphan_entities: Optional[bool] = None,
    ):
        config = ExtractConfig(
            chunk_ids=list(chunk_ids),
            tenant_id=tenant_id or settings.DEFAULT_TENANT_ID,
            extract_relations=extract_relations,
            extract_skills=extract_skills,
            replace_existing=bool(
                settings.KG_EXTRACT_REPLACE_EXISTING if replace_existing is None else replace_existing
            ),
            prune_orphan_entities=bool(
                settings.KG_EXTRACT_PRUNE_ORPHAN_ENTITIES
                if prune_orphan_entities is None
                else prune_orphan_entities
            ),
            prompt_template_id=prompt_template_id,
            prompt_template_key=prompt_template_key,
            prompt_ab_experiment_key=prompt_ab_experiment_key,
            ab_user_key=ab_user_key,
        )
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
        dataset_id: Optional[UUID] = None,
        account_id: Optional[str] = None,
        query_mode: Optional[str] = None,
        query_mode_reason_codes: Optional[List[str]] = None,
        query_mode_confidence: Optional[str] = None,
    ) -> Dict:
        config = SearchConfig(
            query=query,
            tenant_id=tenant_id or settings.DEFAULT_TENANT_ID,
            document_ids=document_ids,
            dataset_id=dataset_id,
            account_id=account_id,
            query_mode=(str(query_mode or "auto")),
            query_mode_reason_codes=[str(x) for x in (query_mode_reason_codes or []) if str(x).strip()][:8],
            query_mode_confidence=(str(query_mode_confidence or "").strip() or None),
        )
        return await self.searcher.search(config)
