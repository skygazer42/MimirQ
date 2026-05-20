"""
Lightweight KG engine to run Extract -> Search using local adapters.
"""
from collections.abc import Sequence
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
    def __init__(self, model_config: dict | None = None):
        self.extractor = EventExtractor(model_config=model_config)
        self.searcher = KGSearcher()

    async def extract(
        self,
        chunk_ids,
        tenant_id: UUID | None = None,
        *,
        chunks: Sequence[DocumentChunk] | None = None,
        index_options: IndexingOptions | None = None,
        prompt_template_id: UUID | None = None,
        prompt_template_key: str | None = None,
        prompt_ab_experiment_key: str | None = None,
        ab_user_key: str | None = None,
        extract_relations: bool | None = None,
        extract_skills: bool | None = None,
        extraction_backend: str | None = None,
        replace_existing: bool | None = None,
        prune_orphan_entities: bool | None = None,
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
            extraction_backend=extraction_backend,
        )
        return await self.extractor.extract(
            config,
            chunks=chunks,
            index_options=index_options,
        )

    async def search(
        self,
        query: str,
        tenant_id: UUID | None = None,
        *,
        document_ids: list[UUID] | None = None,
        dataset_id: UUID | None = None,
        account_id: str | None = None,
        query_mode: str | None = None,
        query_mode_reason_codes: list[str] | None = None,
        query_mode_confidence: str | None = None,
    ) -> dict:
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
