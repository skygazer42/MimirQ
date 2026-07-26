"""Stage result dataclasses for the document processor pipeline."""
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langchain_core.documents import Document

from app.models.document import DocumentChunk
from app.parsing.processors.support.common import REDACTED_MASK, SECRET_MASK
from app.rag.preprocessing.processor import GovernanceStats


class DocumentCancelledError(Exception):
    pass


@dataclass(frozen=True)
class ParseResult:
    resolved_backend: str
    resolved_chunk_strategy: str
    documents: list[Document] | None = None
    chunks: list[Document] | None = None


@dataclass(frozen=True)
class InlineAssetResult:
    documents: list[Document]
    uploaded_img_ids: list[str]
    next_asset_index: int
    image_codes_added: int = 0
    image_code_audit: dict[str, Any] | None = None
    captions_added: int = 0
    caption_backend: str | None = None
    caption_audit: dict[str, Any] | None = None
    formulas_added: int = 0
    formula_backend: str | None = None
    formula_audit: dict[str, Any] | None = None
    charts_added: int = 0
    chart_backend: str | None = None
    chart_audit: dict[str, Any] | None = None


@dataclass(frozen=True)
class GovernanceResult:
    items: list[Document]
    stats: GovernanceStats | None = None


@dataclass(frozen=True)
class ChunkingResult:
    chunks: list[Document]


@dataclass(frozen=True)
class ChunkDedupResult:
    chunks: list[Document]
    duplicates_dropped: int


@dataclass(frozen=True)
class ChunkAssetResult:
    chunks: list[Document]
    img_ids: list[str]


@dataclass(frozen=True)
class ChunkAssetOptions:
    dataset_id: str
    resolved_backend: str
    resolved_chunk_strategy: str
    image_caption_enabled: bool = False
    image_ocr_enabled: bool = False
    image_ocr_max_chars: int = 2000
    image_ocr_max_images: int = 20
    pii_anonymize: bool = False
    pii_mode: str = "mask"
    pii_mask: str = REDACTED_MASK
    secrets_redact: bool = False
    secrets_mode: str = "mask"
    secrets_mask: str = SECRET_MASK


@dataclass(frozen=True)
class ChunkPostprocessStats:
    merge_small_enabled: bool
    merge_small_min_chars: int
    merge_small_before: int
    merge_small_after: int
    merge_small_reduced: int
    dedup_enabled: bool
    dedup_dropped: int
    max_chunks_per_document: int
    max_chunks_strategy: str
    truncated_from: int
    truncated_to: int
    truncated_dropped: int
    truncated_asset_total: int
    truncated_asset_kept: int


@dataclass(frozen=True)
class IndexResult:
    chunk_ids: list[UUID]
    total_characters: int
    db_chunks: list[DocumentChunk]
