"""Document processing pipeline stage classes.

Stage classes that hold the service (``ParsingStage``, ``InlineAssetStage``,
``ChunkAssetStage``) receive it via ``__init__(self, service)``; the parameter
is annotated with a string literal so this module never imports
``app.parsing.processors.processor`` (circular import).
"""

import asyncio
import datetime as dt
import hashlib
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document as DBDocument
from app.parsing.artifact_stats import compute_parsing_artifact_stats
from app.parsing.enrich.chart_to_data import add_chart_data_blocks
from app.parsing.enrich.formula_ocr import add_formula_latex_blocks
from app.parsing.enrich.image_caption import add_image_captions
from app.parsing.enrich.image_code import add_image_code_blocks
from app.parsing.enrich.vlm_image_caption import add_vlm_image_captions
from app.parsing.errors import ParsingError
from app.parsing.processors.parse_quality_gate import apply_parse_quality_gate_metadata
from app.parsing.processors.support.common import (
    _PROCESSOR_CLEANUP_LOG_MESSAGE,
    MIMIRQ_PARSE_DIRNAME,
    REDACTED_MASK,
    SECRET_MASK,
    _log_processor_fallback,
    logger,
)
from app.parsing.processors.support.parse_io import (
    _attach_logical_source_metadata,
    _join_document_page_content,
    _join_original_markdown_for_persistence,
)
from app.parsing.processors.support.quality import (
    _build_ocr_quality_summary,
    _build_seal_summary,
    _seal_summary_to_specialty_signals,
)
from app.parsing.processors.support.results import (
    ChunkAssetOptions,
    ChunkAssetResult,
    ChunkDedupResult,
    ChunkingResult,
    DocumentCancelledError,
    GovernanceResult,
    InlineAssetResult,
    ParseResult,
)
from app.parsing.quality.document_quality import score_document_parse_quality
from app.parsing.quality.text_quality import score_parsed_text_quality
from app.parsing.routing import route_pdf_backend
from app.parsing.subprocess_runner import SubprocessCancelled, run_parser_subprocess
from app.rag.chunking.factory import chunker_factory
from app.rag.chunking.roles import classify_chunk_semantic_role, classify_chunk_type
from app.rag.chunking.strategies import SeparatorChunker
from app.rag.chunking.utils.hierarchical import apply_sequence_hierarchy_metadata
from app.rag.core.metadata import (
    ensure_hierarchy_overlay_metadata,
    infer_chunk_structure,
    normalize_image_metadata,
    normalize_section_metadata,
)
from app.rag.pipeline_plugins.runtime import apply_chunk_python_plugin
from app.rag.preprocessing.markdown_canonical import canonicalize_markdown
from app.rag.preprocessing.normalization import normalize_text
from app.rag.preprocessing.processor import governance_processor
from app.rag.preprocessing.simhash import simhash64, simhash64_hex
from app.services.parse_cache import (
    ParseCacheEntry as RemoteParseCacheEntry,
)
from app.services.parse_cache import (
    build_parse_cache_key as build_remote_parse_cache_key,
)
from app.services.parse_cache import (
    parse_cache_service,
)
from app.types.document_analytics import compute_document_analytics


@dataclass
class _InlineAssetStats:
    uploaded: list[str] = field(default_factory=list)
    image_codes_added_total: int = 0
    image_code_audit: dict[str, Any] | None = None
    captions_added_total: int = 0
    caption_backend: str | None = None
    caption_audit: dict[str, Any] | None = None
    formulas_added_total: int = 0
    formula_backend: str | None = None
    formula_audit: dict[str, Any] | None = None
    charts_added_total: int = 0
    chart_backend: str | None = None
    chart_audit: dict[str, Any] | None = None

    def to_result(self, *, documents: list[Document], next_asset_index: int) -> InlineAssetResult:
        return InlineAssetResult(
            documents=documents,
            uploaded_img_ids=self.uploaded,
            next_asset_index=next_asset_index,
            image_codes_added=int(self.image_codes_added_total),
            image_code_audit=(dict(self.image_code_audit) if isinstance(self.image_code_audit, dict) else None),
            captions_added=int(self.captions_added_total),
            caption_backend=self.caption_backend,
            caption_audit=(dict(self.caption_audit) if isinstance(self.caption_audit, dict) else None),
            formulas_added=int(self.formulas_added_total),
            formula_backend=self.formula_backend,
            formula_audit=(dict(self.formula_audit) if isinstance(self.formula_audit, dict) else None),
            charts_added=int(self.charts_added_total),
            chart_backend=self.chart_backend,
            chart_audit=(dict(self.chart_audit) if isinstance(self.chart_audit, dict) else None),
        )


@dataclass(frozen=True)
class _ChunkAssetDeps:
    append_image_understanding_text: Any
    decode_image_codes: Any
    derive_image_caption: Any
    infer_visual_kind_from_pixels: Any
    load_image_for_ocr: Any
    ocr_image: Any
    redact_ocr_text: Any
    score_chunk_quality: Any


@dataclass
class _ChunkAssetRuntime:
    dataset_id: str
    resolved_backend: str
    resolved_chunk_strategy: str
    ocr_remaining: int | None
    img_ids: list[str] = field(default_factory=list)
    out_chunks: list[Document] = field(default_factory=list)
    out_idx: int = 0
    seen_ocr_hashes: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class _ImageUnderstandingResult:
    caption: str = ""
    ocr_text: str = ""
    image_code_text: str = ""


class ParsingStage:
    def __init__(self, service):
        self._svc = service

    @staticmethod
    def _artifact_root(*, tenant_id: UUID, document_id: UUID, suffix: str) -> Path:
        return (
            Path(settings.UPLOAD_DIR)
            / str(tenant_id)
            / MIMIRQ_PARSE_DIRNAME
            / f"{str(document_id)}-{suffix}-{uuid.uuid4().hex}"
        )

    @staticmethod
    def _cleanup_artifact_root(artifact_root: Path) -> None:
        try:
            shutil.rmtree(artifact_root, ignore_errors=True)
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

    @staticmethod
    def _documents_from_items(items: list[Any] | None) -> list[Document]:
        return [
            Document(
                page_content=str(item.get("page_content") or ""),
                metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                id=item.get("id") if isinstance(item.get("id"), str) else None,
            )
            for item in (items or [])
            if isinstance(item, dict)
        ]

    @staticmethod
    def _commit_document_metadata(db: Session, db_document: DBDocument, metadata: dict[str, Any]) -> None:
        db_document.doc_metadata = metadata
        db.commit()
        db.refresh(db_document)

    async def _run_parser_job(
        self,
        *,
        db: Session,
        tenant_id: UUID,
        document_id: UUID,
        artifact_root: Path,
        payload: dict[str, Any],
        error_prefix: str,
    ) -> dict[str, Any]:
        cancel_check = self._svc._build_cancel_check(db=db, tenant_id=tenant_id, document_id=document_id)

        async def cancel_check_worker() -> bool:
            return await cancel_check()

        try:
            return await run_parser_subprocess(
                tenant_id=tenant_id,
                payload=payload,
                cancel_check=cancel_check_worker,
                timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
            )
        except SubprocessCancelled as exc:
            self._cleanup_artifact_root(artifact_root)
            raise DocumentCancelledError(str(exc)) from exc
        except asyncio.CancelledError:
            self._cleanup_artifact_root(artifact_root)
            raise
        except ParsingError as exc:
            raise RuntimeError(f"{error_prefix}: {str(exc)[:200]}") from exc

    async def _run_integrated_pipeline(
        self,
        *,
        db: Session,
        db_document: DBDocument,
        file_path: Path,
        document_id: UUID,
        tenant_id: UUID,
        resolved_chunk_strategy: str,
    ) -> ParseResult:
        resolved_backend = "integrated"
        self._svc._record_processing_metadata(
            db,
            tenant_id,
            document_id,
            parser_backend=resolved_backend,
            chunk_strategy=resolved_chunk_strategy,
        )
        artifact_root = self._artifact_root(tenant_id=tenant_id, document_id=document_id, suffix="integrated")
        result = await self._run_parser_job(
            db=db,
            tenant_id=tenant_id,
            document_id=document_id,
            artifact_root=artifact_root,
            payload={
                "action": "integrated_chunk",
                "tenant_id": str(tenant_id),
                "file_path": str(file_path),
                "strategy": resolved_chunk_strategy,
                "mode": "ingest",
                "artifact_root": str(artifact_root),
            },
            error_prefix="Integrated pipeline parsing failed",
        )
        chunks = self._documents_from_items(result.get("documents"))
        return ParseResult(
            resolved_backend=resolved_backend,
            resolved_chunk_strategy=resolved_chunk_strategy,
            chunks=_attach_logical_source_metadata(chunks, db_document=db_document, file_path=file_path),
        )

    def _resolve_pdf_backend(
        self,
        *,
        db: Session,
        db_document: DBDocument,
        file_path: Path,
        parser_backend: str | None,
    ) -> tuple[str | None, dict[str, Any] | None]:
        effective_parser_backend = parser_backend
        pdf_quality = None
        if file_path.suffix.lower() != ".pdf":
            return effective_parser_backend, pdf_quality

        requested = (parser_backend or "").strip().lower()
        if requested and requested != "auto":
            return effective_parser_backend, pdf_quality

        cached_quality = None
        try:
            metadata = db_document.doc_metadata or {}
            quality = metadata.get("pdf_quality") if isinstance(metadata, dict) else None
            if isinstance(quality, dict) and quality.get("score") is not None:
                cached_quality = dict(quality)
        except (TypeError, ValueError, AttributeError):
            cached_quality = None

        effective_parser_backend, pdf_quality = route_pdf_backend(
            file_path,
            parser_backend,
            quality=cached_quality,
            sample_pages=3,
            use_ocr_validation=settings.RAPIDOCR_ENABLED,
        )
        if isinstance(pdf_quality, dict):
            metadata = dict(db_document.doc_metadata or {})
            metadata["pdf_quality"] = pdf_quality
            self._commit_document_metadata(db, db_document, metadata)
        return effective_parser_backend, pdf_quality

    def _maybe_load_parse_cache(
        self,
        *,
        db: Session,
        db_document: DBDocument,
        tenant_id: UUID,
        dataset_id: str,
        effective_parser_backend: str | None,
    ) -> tuple[str | None, bool, list[Document]]:
        parse_cache_key: str | None = None
        if not bool(getattr(settings, "PARSE_CACHE_ENABLED", False)) or not bool(
            getattr(settings, "MINIO_ENABLED", False)
        ):
            return parse_cache_key, False, []

        try:
            metadata = dict(db_document.doc_metadata or {})
            file_sha = str(metadata.get("file_sha256") or "").strip().lower()
            pipeline_hash = str(metadata.get("pipeline_hash") or metadata.get("active_pipeline_hash") or "").strip()
            backend_key = str(effective_parser_backend or "").strip().lower()
            if not file_sha or not backend_key:
                return parse_cache_key, False, []

            parse_cache_key = build_remote_parse_cache_key(
                file_sha256=file_sha,
                resolved_backend=backend_key,
                config_hash=(pipeline_hash or "unknown"),
                version=str(getattr(settings, "PARSE_CACHE_VERSION", "v1") or "v1"),
            )
            cached, age_ms = parse_cache_service.get(
                tenant_id=str(tenant_id),
                dataset_id=str(dataset_id),
                cache_key=parse_cache_key,
                ttl_sec=int(getattr(settings, "PARSE_CACHE_TTL_SEC", 0) or 0),
                max_bytes=int(getattr(settings, "PARSE_CACHE_MAX_BYTES", 0) or 0),
            )
            documents = self._documents_from_items(list(getattr(cached, "documents", None) or []))
            if not documents:
                return parse_cache_key, False, []

            try:
                meta_patch = dict(db_document.doc_metadata or {})
                meta_patch["parse_cache"] = {
                    "schema": "mimirq.parse_cache_hit.v1",
                    "hit": True,
                    "age_ms": int(age_ms or 0),
                    "backend": backend_key,
                }
                self._commit_document_metadata(db, db_document, meta_patch)
            except Exception as exc:
                logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
            return parse_cache_key, True, documents
        except Exception as exc:
            _log_processor_fallback("run", exc)
            return parse_cache_key, False, []

    async def _parse_documents(
        self,
        *,
        db: Session,
        file_path: Path,
        document_id: UUID,
        tenant_id: UUID,
        dataset_id: str,
        effective_parser_backend: str | None,
        pdf_quality: dict[str, Any] | None,
        html_xpath: str | None,
    ) -> tuple[dict[str, Any], list[Document]]:
        artifact_root = self._artifact_root(tenant_id=tenant_id, document_id=document_id, suffix="parse")
        payload: dict[str, Any] = {
            "action": "parse_documents",
            "tenant_id": str(tenant_id),
            "file_path": str(file_path),
            "parser_backend": effective_parser_backend,
            "mode": "ingest",
            "dataset_id": dataset_id,
            "document_id": str(document_id),
            "pdf_quality": pdf_quality,
            "artifact_root": str(artifact_root),
        }
        if isinstance(html_xpath, str) and html_xpath.strip():
            payload["html_xpath"] = html_xpath.strip()

        parsed = await self._run_parser_job(
            db=db,
            tenant_id=tenant_id,
            document_id=document_id,
            artifact_root=artifact_root,
            payload=payload,
            error_prefix="Parsing failed",
        )
        return parsed, self._documents_from_items(parsed.get("documents"))

    def _persist_parse_provenance(self, db: Session, db_document: DBDocument, parsed: dict[str, Any] | None) -> None:
        try:
            provenance = parsed.get("provenance") if isinstance(parsed, dict) else None
            if not isinstance(provenance, dict) or not provenance:
                return
            metadata = dict(db_document.doc_metadata or {})
            metadata["parse_provenance"] = provenance
            self._commit_document_metadata(db, db_document, metadata)
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

    def _persist_parse_quality(
        self,
        *,
        db: Session,
        db_document: DBDocument,
        documents: list[Document],
        pdf_quality: dict[str, Any] | None,
    ) -> None:
        try:
            joined = _join_document_page_content(documents)
            quality = score_parsed_text_quality(joined).to_dict()
            seal_summary = _build_seal_summary(documents)
            specialty_signals = _seal_summary_to_specialty_signals(seal_summary)
            ocr_summary = _build_ocr_quality_summary(
                documents,
                low_confidence_threshold=float(settings.PARSE_QUALITY_OCR_LOW_CONFIDENCE_THRESHOLD),
            )
            metadata = dict(db_document.doc_metadata or {})
            metadata["parsed_text_quality"] = quality
            metadata["parse_quality"] = score_document_parse_quality(
                pdf_quality=(pdf_quality if isinstance(pdf_quality, dict) else None),
                parsed_text_quality=quality,
                specialty_signals=specialty_signals,
            )
            if seal_summary is not None:
                metadata["seal_summary"] = seal_summary
            if ocr_summary is not None:
                metadata["ocr"] = ocr_summary
            metadata.update(
                compute_parsing_artifact_stats(
                    documents=documents,
                    original_markdown=_join_original_markdown_for_persistence(documents),
                    markdown=joined,
                    pdf_quality=(pdf_quality if isinstance(pdf_quality, dict) else None),
                )
            )
            try:
                metadata["document_analytics_raw"] = compute_document_analytics(
                    markdown=joined,
                    documents=documents,
                    pdf_quality=(pdf_quality if isinstance(pdf_quality, dict) else None),
                    detect_language=bool(getattr(settings, "GOVERNANCE_DETECT_LANGUAGE", False)),
                    language_min_chars=int(getattr(settings, "GOVERNANCE_LANGUAGE_MIN_CHARS", 40) or 40),
                ).to_dict()
            except Exception as exc:
                logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
            self._commit_document_metadata(db, db_document, apply_parse_quality_gate_metadata(metadata))
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

    def _maybe_write_parse_cache(
        self,
        *,
        db_document: DBDocument,
        tenant_id: UUID,
        dataset_id: str,
        parse_cache_key: str | None,
        parse_cache_hit: bool,
        documents: list[Document],
        effective_parser_backend: str | None,
    ) -> None:
        if parse_cache_hit or not parse_cache_key or not documents:
            return

        try:
            metadata = dict(db_document.doc_metadata or {})
            file_sha = str(metadata.get("file_sha256") or "").strip().lower()
            pipeline_hash = str(metadata.get("pipeline_hash") or metadata.get("active_pipeline_hash") or "").strip()
            entry = RemoteParseCacheEntry(
                created_at=dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
                file_sha256=file_sha,
                resolved_backend=str(effective_parser_backend or "").strip().lower(),
                config_hash=(pipeline_hash or "unknown"),
                documents=[
                    {
                        "page_content": str(doc.page_content or ""),
                        "metadata": dict(doc.metadata or {}),
                        "id": str(doc.id) if isinstance(getattr(doc, "id", None), str) else None,
                    }
                    for doc in documents
                ],
            )
            parse_cache_service.set(
                tenant_id=str(tenant_id),
                dataset_id=str(dataset_id),
                cache_key=parse_cache_key,
                entry=entry,
                max_bytes=int(getattr(settings, "PARSE_CACHE_MAX_BYTES", 0) or 0),
            )
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

    async def run(
        self,
        *,
        db: Session,
        db_document: DBDocument,
        file_path: Path,
        document_id: UUID,
        tenant_id: UUID,
        dataset_id: str,
        parser_backend: str | None,
        chunk_strategy: str | None,
        html_xpath: str | None = None,
    ) -> ParseResult:
        # IMPORTANT: resolve strategy first so defaults (e.g. DEFAULT_CHUNK_STRATEGY)
        # are honored consistently (including integrated_* strategies).
        resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy)
        if resolved_chunk_strategy in self._svc.INTEGRATED_PIPELINE_STRATEGIES:
            return await self._run_integrated_pipeline(
                db=db,
                db_document=db_document,
                file_path=file_path,
                document_id=document_id,
                tenant_id=tenant_id,
                resolved_chunk_strategy=resolved_chunk_strategy,
            )

        logger.info("Parsing document: %s", file_path)
        effective_parser_backend, pdf_quality = self._resolve_pdf_backend(
            db=db,
            db_document=db_document,
            file_path=file_path,
            parser_backend=parser_backend,
        )
        parse_cache_key, parse_cache_hit, documents = self._maybe_load_parse_cache(
            db=db,
            db_document=db_document,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            effective_parser_backend=effective_parser_backend,
        )

        parsed: dict[str, Any] | None = None

        if not parse_cache_hit:
            parsed, documents = await self._parse_documents(
                db=db,
                file_path=file_path,
                document_id=document_id,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                effective_parser_backend=effective_parser_backend,
                pdf_quality=(pdf_quality if isinstance(pdf_quality, dict) else None),
                html_xpath=html_xpath,
            )

        documents = _attach_logical_source_metadata(documents, db_document=db_document, file_path=file_path)
        self._persist_parse_provenance(db, db_document, parsed)
        self._persist_parse_quality(
            db=db,
            db_document=db_document,
            documents=documents,
            pdf_quality=(pdf_quality if isinstance(pdf_quality, dict) else None),
        )
        self._maybe_write_parse_cache(
            db_document=db_document,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            parse_cache_key=parse_cache_key,
            parse_cache_hit=parse_cache_hit,
            documents=documents,
            effective_parser_backend=effective_parser_backend,
        )

        parsed_backend = parsed.get("resolved_backend") if isinstance(parsed, dict) else None
        resolved_backend = str(parsed_backend or effective_parser_backend or parser_backend or "auto")
        self._svc._record_processing_metadata(
            db,
            tenant_id,
            document_id,
            parser_backend=resolved_backend,
            chunk_strategy=resolved_chunk_strategy,
        )
        return ParseResult(
            resolved_backend=resolved_backend,
            resolved_chunk_strategy=resolved_chunk_strategy,
            documents=documents,
        )


class InlineAssetStage:
    def __init__(self, service):
        self._svc = service

    @staticmethod
    def _resolve_origin_path(origin_path: Path, metadata: dict[str, Any]) -> Path:
        base_dir = metadata.get("asset_base_dir")
        if isinstance(base_dir, str) and base_dir.strip():
            return Path(base_dir.strip())
        return origin_path

    @staticmethod
    def _append_derived_elements(
        metadata: dict[str, Any],
        raw_elements: Any,
        *,
        prefix: str,
    ) -> None:
        if not isinstance(raw_elements, list) or not raw_elements:
            return

        derived = [item for item in (metadata.get("derived_elements") or []) if isinstance(item, dict)]
        page_hint = metadata.get("element_page") or metadata.get("page")
        for raw_element in raw_elements:
            if not isinstance(raw_element, dict):
                continue
            item = dict(raw_element)
            if item.get("page") is None and page_hint is not None:
                item["page"] = page_hint
            if not str(item.get("id") or "").strip():
                page_part = item.get("page") if item.get("page") is not None else "na"
                item["id"] = f"{prefix}:{page_part}:{len(derived)}"
            derived.append(item)
        if derived:
            metadata["derived_elements"] = derived

    def _apply_image_code_enrichment(
        self,
        *,
        content: str,
        origin_path: Path,
        metadata: dict[str, Any],
        stats: _InlineAssetStats,
    ) -> str:
        if not content:
            return content
        try:
            content, added, audit = add_image_code_blocks(content, origin_path=origin_path)
            stats.image_codes_added_total += int(added or 0)
            stats.image_code_audit = audit.to_dict()
            self._append_derived_elements(metadata, getattr(audit, "code_elements", None), prefix="image_code")
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
        return content

    def _apply_formula_enrichment(
        self,
        *,
        content: str,
        origin_path: Path,
        metadata: dict[str, Any],
        formula_url: str,
        enabled: bool,
        stats: _InlineAssetStats,
    ) -> str:
        if not enabled or not content:
            return content
        try:
            content, added, audit = add_formula_latex_blocks(
                content,
                origin_path=origin_path,
                api_url=formula_url,
                timeout_sec=float(getattr(settings, "FORMULA_OCR_TIMEOUT_SEC", 60) or 60),
                max_images=int(getattr(settings, "FORMULA_OCR_MAX_IMAGES", 12) or 12),
                max_image_bytes=int(getattr(settings, "FORMULA_OCR_MAX_IMAGE_BYTES", 5_000_000) or 5_000_000),
                max_latex_chars=int(getattr(settings, "FORMULA_OCR_MAX_LATEX_CHARS", 2000) or 2000),
            )
            stats.formulas_added_total += int(added or 0)
            stats.formula_backend = "formula_http"
            stats.formula_audit = audit.to_dict()
            self._append_derived_elements(metadata, getattr(audit, "formula_elements", None), prefix="formula_ocr")
        except Exception as exc:
            _log_processor_fallback("run", exc)
        return content

    @staticmethod
    def _apply_chart_enrichment(
        *,
        content: str,
        origin_path: Path,
        enabled: bool,
        stats: _InlineAssetStats,
    ) -> str:
        if not enabled or not content:
            return content
        try:
            content, added, audit = add_chart_data_blocks(
                content,
                origin_path=origin_path,
                max_images=int(getattr(settings, "CHART_TO_DATA_MAX_IMAGES", 8) or 8),
                max_image_bytes=int(getattr(settings, "CHART_TO_DATA_MAX_IMAGE_BYTES", 5_000_000) or 5_000_000),
                timeout_sec=float(getattr(settings, "CHART_TO_DATA_TIMEOUT_SEC", 20) or 20),
            )
            stats.charts_added_total += int(added or 0)
            stats.chart_backend = "chart_http"
            stats.chart_audit = audit.to_dict()
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
        return content

    @staticmethod
    def _apply_caption_enrichment(
        *,
        content: str,
        origin_path: Path,
        enabled: bool,
        stats: _InlineAssetStats,
    ) -> str:
        if not enabled:
            return content
        try:
            if (
                bool(getattr(settings, "IMAGE_CAPTION_VLM_ENABLED", False))
                and str(getattr(settings, "IMAGE_CAPTION_VLM_API_URL", "") or "").strip()
            ):
                content, added, audit = add_vlm_image_captions(
                    content,
                    origin_path=origin_path,
                    api_url=str(getattr(settings, "IMAGE_CAPTION_VLM_API_URL", "") or ""),
                    timeout_sec=float(getattr(settings, "IMAGE_CAPTION_VLM_TIMEOUT_SEC", 60) or 60),
                    max_images=int(getattr(settings, "IMAGE_CAPTION_VLM_MAX_IMAGES", 20) or 20),
                    max_image_bytes=int(getattr(settings, "IMAGE_CAPTION_VLM_MAX_IMAGE_BYTES", 5_000_000) or 5_000_000),
                    max_caption_chars=int(getattr(settings, "IMAGE_CAPTION_VLM_MAX_CAPTION_CHARS", 200) or 200),
                )
                stats.captions_added_total += int(added or 0)
                stats.caption_backend = "vlm_http"
                stats.caption_audit = audit.to_dict()
                return content

            content, added = add_image_captions(content)
            stats.captions_added_total += int(added or 0)
            stats.caption_backend = "heuristic"
        except Exception as exc:
            _log_processor_fallback("run", exc)
        return content

    def _upload_inline_assets(
        self,
        *,
        content: str,
        enabled: bool,
        tenant_id: UUID,
        dataset_id: str,
        document_id: UUID,
        inline_cache: dict[str, str],
        asset_idx: int,
        origin_path: Path,
        stats: _InlineAssetStats,
    ) -> tuple[str, int]:
        if not enabled:
            return content, asset_idx

        new_content, new_img_ids, next_asset_index = self._svc._upload_inline_images_to_minio(
            markdown_text=content,
            tenant_id=str(tenant_id),
            dataset_id=dataset_id,
            document_id=str(document_id),
            cache=inline_cache,
            start_index=asset_idx,
            origin_path=origin_path,
        )
        stats.uploaded.extend(list(new_img_ids or []))
        return new_content, next_asset_index

    @staticmethod
    def _build_output_document(
        doc: Document,
        *,
        original_content: str,
        new_content: str,
        original_meta: dict[str, Any],
        new_meta: dict[str, Any],
    ) -> Document:
        if new_content != original_content or new_meta != original_meta:
            page_content = new_content if new_content != original_content else original_content
            return Document(page_content=page_content, metadata=new_meta, id=doc.id)
        return doc

    def run(
        self,
        *,
        documents: list[Document],
        tenant_id: UUID,
        dataset_id: str,
        document_id: UUID,
        origin_path: Path,
        start_index: int = 0,
        image_caption_enabled: bool = False,
    ) -> InlineAssetResult:
        upload_enabled = bool(getattr(settings, "MINIO_ENABLED", False))
        caption_enabled = bool(image_caption_enabled)
        formula_url = str(getattr(settings, "FORMULA_OCR_API_URL", "") or "").strip()
        formula_enabled = bool(getattr(settings, "FORMULA_OCR_ENABLED", False)) and bool(formula_url)
        chart_enabled = bool(getattr(settings, "CHART_TO_DATA_ENABLED", False)) and bool(
            str(getattr(settings, "CHART_TO_DATA_API_URL", "") or "").strip()
        )
        image_code_enabled = True
        if (
            not upload_enabled
            and not caption_enabled
            and not formula_enabled
            and not chart_enabled
            and not image_code_enabled
        ):
            return InlineAssetResult(documents=documents, uploaded_img_ids=[], next_asset_index=int(start_index or 0))

        inline_cache: dict[str, str] = {}
        asset_idx = int(start_index or 0)
        processed_docs: list[Document] = []
        stats = _InlineAssetStats()

        for doc in documents:
            content = doc.page_content or ""
            original_meta = dict(doc.metadata or {})
            origin_for_doc = self._resolve_origin_path(origin_path, original_meta)

            next_content = content
            next_meta = dict(original_meta)
            next_content = self._apply_image_code_enrichment(
                content=next_content,
                origin_path=origin_for_doc,
                metadata=next_meta,
                stats=stats,
            )
            next_content = self._apply_formula_enrichment(
                content=next_content,
                origin_path=origin_for_doc,
                metadata=next_meta,
                formula_url=formula_url,
                enabled=formula_enabled,
                stats=stats,
            )
            next_content = self._apply_chart_enrichment(
                content=next_content,
                origin_path=origin_for_doc,
                enabled=chart_enabled,
                stats=stats,
            )
            next_content = self._apply_caption_enrichment(
                content=next_content,
                origin_path=origin_for_doc,
                enabled=caption_enabled,
                stats=stats,
            )
            new_content, asset_idx = self._upload_inline_assets(
                content=next_content,
                enabled=upload_enabled,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                document_id=document_id,
                inline_cache=inline_cache,
                asset_idx=asset_idx,
                origin_path=origin_for_doc,
                stats=stats,
            )
            processed_docs.append(
                self._build_output_document(
                    doc,
                    original_content=content,
                    new_content=new_content,
                    original_meta=original_meta,
                    new_meta=next_meta,
                )
            )

        return stats.to_result(documents=processed_docs, next_asset_index=asset_idx)


class GovernanceStage:
    def run(
        self,
        *,
        items: list[Document],
        enabled: bool,
        kwargs: dict[str, Any],
    ) -> GovernanceResult:
        if not enabled:
            return GovernanceResult(items=items, stats=None)
        cleaned, stats = governance_processor.clean_documents(items, **kwargs)
        return GovernanceResult(items=cleaned, stats=stats)


class NormalizeStage:
    """
    Apply conservative normalization before governance/chunking.

    Unlike governance cleaning, this stage is always safe to run:
    - Normalizes line endings and Unicode whitespace artifacts
    - Removes zero-width/control characters and soft hyphens
    - Repairs common PDF ligatures
    """

    def run(self, *, items: list[Document]) -> list[Document]:
        if not items:
            return items
        out: list[Document] = []
        for doc in items:
            raw = doc.page_content or ""
            normalized = normalize_text(raw, normalize_line_endings=True, remove_control_chars=True)
            canon = canonicalize_markdown(normalized)
            meta = dict(doc.metadata or {})
            meta["text_normalized"] = True
            meta["text_normalized_changed"] = bool(normalized != raw)
            meta["markdown_canonicalized"] = True
            meta["markdown_canonical_changed"] = bool(canon.changed)
            meta["markdown_canonical_stats"] = {
                "headings_changed": int(canon.headings_changed),
                "list_markers_changed": int(canon.list_markers_changed),
                "ordered_list_markers_changed": int(canon.ordered_list_markers_changed),
                "code_fences_changed": int(canon.code_fences_changed),
                "tables": int(canon.tables),
                "table_rows_changed": int(canon.table_rows_changed),
            }
            out.append(Document(page_content=canon.text, metadata=meta, id=getattr(doc, "id", None)))
        return out


class ChunkingStage:
    @staticmethod
    def _to_bool(value: object) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "y", "on"}:
                return True
            if normalized in {"0", "false", "no", "n", "off"}:
                return False
        return None

    @staticmethod
    def _to_int(value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            try:
                return int(value)
            except (TypeError, ValueError, AttributeError):
                return None
        if isinstance(value, str):
            try:
                return int(float(value.strip()))
            except (TypeError, ValueError, AttributeError):
                return None
        return None

    @staticmethod
    def _to_float(value: object) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            try:
                return float(value)
            except (TypeError, ValueError, AttributeError):
                return None
        if isinstance(value, str):
            try:
                return float(value.strip())
            except (TypeError, ValueError, AttributeError):
                return None
        return None

    @staticmethod
    def _decode_separator_value(raw_value: object) -> str:
        separator = str(raw_value or "") or "\n\n"
        try:
            import json as _json  # local import to keep module deps minimal

            escaped = separator.replace('"', '\\"')
            return str(_json.loads(f'"{escaped}"'))
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
            return separator

    def _build_separator_chunker(
        self,
        *,
        params: dict[str, Any],
        chunk_size: int,
        chunk_overlap: int,
    ) -> SeparatorChunker:
        preset = str(params.get("separator_preset") or "").strip() or "paragraph"
        if preset != "custom":
            separator = SeparatorChunker.PRESET_SEPARATORS.get(preset)
            if separator is None:
                raise ValueError(f"Invalid separator_preset: {preset}")
        else:
            raw_value = params.get("separator")
            if raw_value is None:
                raw_value = params.get("separator_custom")
            separator = self._decode_separator_value(raw_value)

        keep_separator = self._to_bool(params.get("keep_separator"))
        max_chunk_size = self._to_int(params.get("separator_max_chunk_size"))
        if max_chunk_size is None:
            max_chunk_size = self._to_int(params.get("max_chunk_size"))
        return SeparatorChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separator=separator,
            keep_separator=(True if keep_separator is None else keep_separator),
            max_chunk_size=int(max_chunk_size or 0),
        )

    def _coerce_strategy_params(self, params: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(params)
        if "child_ratio" in normalized:
            child_ratio = self._to_float(normalized.get("child_ratio"))
            if child_ratio is not None:
                normalized["child_ratio"] = child_ratio
        if "min_child_size" in normalized:
            min_child_size = self._to_int(normalized.get("min_child_size"))
            if min_child_size is not None:
                normalized["min_child_size"] = min_child_size
        return normalized

    @staticmethod
    def _plugin_chunks(
        *,
        documents: list[Document],
        chunk_strategy: str,
        chunk_size: int,
        chunk_overlap: int,
        plugin_ref: str,
        params: dict[str, Any],
        chunk_python_params: dict[str, Any] | None,
    ) -> list[Document]:
        return apply_chunk_python_plugin(
            documents,
            plugin_ref=plugin_ref,
            params={**params, **dict(chunk_python_params or {})},
            context={
                "chunk_strategy": chunk_strategy,
                "chunk_size": int(chunk_size),
                "chunk_overlap": int(chunk_overlap),
            },
        )

    def run(
        self,
        *,
        documents: list[Document],
        chunk_strategy: str,
        chunk_size: int,
        chunk_overlap: int,
        chunk_strategy_params: dict[str, Any] | None = None,
        chunk_python_plugin: str = "",
        chunk_python_params: dict[str, Any] | None = None,
    ) -> ChunkingResult:
        logger.info("Chunking document into smaller pieces...")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")
        params = dict(chunk_strategy_params or {})
        plugin_ref = str(chunk_python_plugin or "").strip()
        if plugin_ref:
            return ChunkingResult(
                chunks=self._plugin_chunks(
                    documents=documents,
                    chunk_strategy=chunk_strategy,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    plugin_ref=plugin_ref,
                    params=params,
                    chunk_python_params=chunk_python_params,
                )
            )

        # Separator chunking needs preset/custom mapping (preview supports this too).
        if (chunk_strategy or "").strip().lower() == "separator":
            chunker = self._build_separator_chunker(
                params=params,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        else:
            chunker = chunker_factory.get_chunker(
                chunk_strategy,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                **self._coerce_strategy_params(params),
            )
        return ChunkingResult(chunks=chunker.split_documents(documents))


class ChunkDedupStage:
    @staticmethod
    def _chunk_digest_metadata(chunk: Document) -> tuple[str, dict[str, Any]]:
        raw = chunk.page_content or ""
        normalized = normalize_text(raw, normalize_line_endings=True, remove_control_chars=True)
        digest = hashlib.sha256(normalized.strip().encode("utf-8", "ignore")).hexdigest()

        meta = dict(chunk.metadata or {})
        meta.setdefault("content_hash", digest)
        meta.setdefault("content_hash_algo", "sha256")
        meta.setdefault("content_len", len(normalized.strip()))
        return digest, meta

    @staticmethod
    def _chunk_has_asset(meta: dict[str, Any]) -> bool:
        doc_type = str(meta.get("doc_type_kwd") or "").lower()
        return (
            doc_type in {"image", "table"}
            or meta.get("image") is not None
            or bool(meta.get("img_id") or meta.get("image_id") or meta.get("image_url"))
        )

    @staticmethod
    def _record_identity_key(meta: dict[str, Any]) -> str | None:
        record_identity = meta.get("_record_identity")
        if not isinstance(record_identity, dict):
            return None
        key = str(record_identity.get("key") or "").strip()
        return key or None

    @classmethod
    def _duplicate_text_chunk(
        cls,
        *,
        digest: str,
        meta: dict[str, Any],
        seen: set[tuple[str, str | None]],
    ) -> bool:
        if cls._chunk_has_asset(meta):
            return False
        dedup_key = (digest, cls._record_identity_key(meta))
        if dedup_key in seen:
            return True
        seen.add(dedup_key)
        return False

    def run(self, *, chunks: list[Document], enabled: bool) -> ChunkDedupResult:
        """
        Drop exact-duplicate *text* chunks within a single document.

        Notes:
        - Keeps image/table-related chunks even if their text matches (assets matter).
        - Uses a normalized content hash for comparison (line endings/control chars).
        """
        if not enabled or not chunks:
            return ChunkDedupResult(chunks=chunks, duplicates_dropped=0)

        seen: set[tuple[str, str | None]] = set()
        out: list[Document] = []
        dropped = 0

        for c in chunks:
            digest, meta = self._chunk_digest_metadata(c)
            if self._duplicate_text_chunk(digest=digest, meta=meta, seen=seen):
                dropped += 1
                continue

            out.append(Document(page_content=c.page_content, metadata=meta, id=getattr(c, "id", None)))

        return ChunkDedupResult(chunks=out, duplicates_dropped=dropped)


class ChunkAssetStage:
    def __init__(self, service):
        self._svc = service

    @staticmethod
    def _load_deps() -> _ChunkAssetDeps:
        from app.parsing.enrich.image_understanding import (
            append_image_understanding_text,
            decode_image_codes,
            derive_image_caption,
            infer_visual_kind_from_pixels,
            load_image_for_ocr,
            ocr_image,
        )
        from app.parsing.enrich.ocr_redaction import redact_ocr_text
        from app.services.chunk_quality_scoring import score_chunk_quality

        return _ChunkAssetDeps(
            append_image_understanding_text=append_image_understanding_text,
            decode_image_codes=decode_image_codes,
            derive_image_caption=derive_image_caption,
            infer_visual_kind_from_pixels=infer_visual_kind_from_pixels,
            load_image_for_ocr=load_image_for_ocr,
            ocr_image=ocr_image,
            redact_ocr_text=redact_ocr_text,
            score_chunk_quality=score_chunk_quality,
        )

    @staticmethod
    def _initial_ocr_remaining(options: ChunkAssetOptions) -> int | None:
        max_images = max(0, int(options.image_ocr_max_images or 0))
        return max_images if max_images > 0 else None

    @staticmethod
    def _build_runtime(options: ChunkAssetOptions) -> _ChunkAssetRuntime:
        return _ChunkAssetRuntime(
            dataset_id=options.dataset_id,
            resolved_backend=options.resolved_backend,
            resolved_chunk_strategy=options.resolved_chunk_strategy,
            ocr_remaining=ChunkAssetStage._initial_ocr_remaining(options),
        )

    @staticmethod
    def _base_chunk_metadata(
        *,
        chunk: Document,
        document_id: UUID,
        idx: int,
        runtime: _ChunkAssetRuntime,
    ) -> dict[str, Any]:
        metadata = dict(chunk.metadata or {})
        metadata.setdefault("dataset_id", str(runtime.dataset_id))
        metadata["document_id"] = str(document_id)
        metadata["chunk_index"] = idx
        metadata["parser_backend"] = runtime.resolved_backend
        metadata.setdefault("chunk_strategy", runtime.resolved_chunk_strategy)
        metadata["resolved_chunk_strategy"] = runtime.resolved_chunk_strategy
        metadata.setdefault("chunk_key", f"{str(document_id)}:{idx}")
        normalize_section_metadata(metadata)
        ensure_hierarchy_overlay_metadata(metadata, document_id=str(document_id), chunk_index=idx)
        return metadata

    @staticmethod
    def _needs_image_inspection(meta: dict[str, Any], *, image_ocr_enabled: bool, ocr_remaining: int | None) -> bool:
        return (
            not str(meta.get("visual_kind") or "").strip()
            or not str(meta.get("image_code_text") or "").strip()
            or (bool(image_ocr_enabled) and (ocr_remaining is None or ocr_remaining > 0))
        )

    @staticmethod
    def _derive_caption(
        *,
        chunk: Document,
        meta: dict[str, Any],
        enabled: bool,
        deps: _ChunkAssetDeps,
    ) -> str:
        if not enabled:
            return ""
        try:
            return str(deps.derive_image_caption(chunk.page_content or "", meta) or "")
        except Exception as exc:
            _log_processor_fallback("run", exc)
            return ""

    @staticmethod
    def _apply_code_info(meta: dict[str, Any], code_info: Any) -> str:
        if not isinstance(code_info, dict):
            return ""
        image_code_text = str(code_info.get("text") or "").strip()
        if image_code_text:
            meta["image_code_text"] = image_code_text
            raw_values = code_info.get("values")
            if isinstance(raw_values, list):
                meta["image_code_values"] = [str(item).strip() for item in raw_values if str(item).strip()]
        visual_kind = str(code_info.get("visual_kind") or "").strip().lower()
        if visual_kind:
            meta["visual_kind"] = visual_kind
        return image_code_text

    @staticmethod
    def _ensure_visual_kind(meta: dict[str, Any], img: Any, deps: _ChunkAssetDeps) -> None:
        if str(meta.get("visual_kind") or "").strip():
            return
        try:
            visual_kind = str(deps.infer_visual_kind_from_pixels(img) or "").strip().lower()
        except Exception as exc:
            _log_processor_fallback("run", exc)
            visual_kind = ""
        if visual_kind:
            meta["visual_kind"] = visual_kind

    @staticmethod
    def _maybe_read_ocr(
        *,
        img: Any,
        image_ocr_enabled: bool,
        image_ocr_max_chars: int,
        ocr_remaining: int | None,
        deps: _ChunkAssetDeps,
    ) -> tuple[str, int | None]:
        if not image_ocr_enabled or (ocr_remaining is not None and ocr_remaining <= 0):
            return "", ocr_remaining
        ocr_text = str(deps.ocr_image(img, _max_chars=int(image_ocr_max_chars)) or "")
        if ocr_remaining is None:
            return ocr_text, None
        return ocr_text, (ocr_remaining - 1)

    def _inspect_image(
        self,
        *,
        meta: dict[str, Any],
        tenant_id: UUID,
        image_ocr_enabled: bool,
        image_ocr_max_chars: int,
        ocr_remaining: int | None,
        deps: _ChunkAssetDeps,
    ) -> tuple[str, str, int | None]:
        if not self._needs_image_inspection(
            meta,
            image_ocr_enabled=image_ocr_enabled,
            ocr_remaining=ocr_remaining,
        ):
            return "", "", ocr_remaining

        img, should_close = deps.load_image_for_ocr(meta, _tenant_id=str(tenant_id))
        try:
            if img is None:
                return "", "", ocr_remaining
            try:
                code_info = deps.decode_image_codes(img)
            except Exception as exc:
                _log_processor_fallback("run", exc)
                code_info = {}
            image_code_text = self._apply_code_info(meta, code_info)
            self._ensure_visual_kind(meta, img, deps)
            ocr_text, next_remaining = self._maybe_read_ocr(
                img=img,
                image_ocr_enabled=image_ocr_enabled,
                image_ocr_max_chars=image_ocr_max_chars,
                ocr_remaining=ocr_remaining,
                deps=deps,
            )
            return image_code_text, ocr_text, next_remaining
        except Exception as exc:
            _log_processor_fallback("run", exc)
            return "", "", ocr_remaining
        finally:
            if should_close and img is not None:
                try:
                    img.close()
                except Exception as exc:
                    logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

    @staticmethod
    def _redaction_kwargs(options: ChunkAssetOptions) -> dict[str, Any]:
        return {
            "pii_anonymize": bool(options.pii_anonymize),
            "pii_mode": str(options.pii_mode or "mask"),
            "pii_mask": str(options.pii_mask or REDACTED_MASK),
            "secrets_redact": bool(options.secrets_redact),
            "secrets_mode": str(options.secrets_mode or "mask"),
            "secrets_mask": str(options.secrets_mask or SECRET_MASK),
        }

    def _redact_text(
        self,
        *,
        text: str,
        options: ChunkAssetOptions,
        deps: _ChunkAssetDeps,
        meta: dict[str, Any] | None = None,
        pii_key: str | None = None,
        secrets_key: str | None = None,
    ) -> str:
        if not text:
            return ""
        try:
            redacted, pii_hits, secret_hits = deps.redact_ocr_text(text, **self._redaction_kwargs(options))
            if meta is not None and pii_key and pii_hits:
                meta[pii_key] = {str(key): int(value) for key, value in pii_hits.items() if int(value or 0) > 0}
            if meta is not None and secrets_key and secret_hits:
                meta[secrets_key] = {str(key): int(value) for key, value in secret_hits.items() if int(value or 0) > 0}
            return str(redacted or "")
        except Exception as exc:
            _log_processor_fallback("run", exc)
            if bool(options.pii_anonymize) or bool(options.secrets_redact):
                return (
                    str(options.pii_mask or REDACTED_MASK)
                    if bool(options.pii_anonymize)
                    else str(options.secrets_mask or SECRET_MASK)
                )
            return ""

    def _image_understanding(
        self,
        *,
        chunk: Document,
        meta: dict[str, Any],
        tenant_id: UUID,
        options: ChunkAssetOptions,
        deps: _ChunkAssetDeps,
        runtime: _ChunkAssetRuntime,
    ) -> _ImageUnderstandingResult:
        if str(meta.get("doc_type_kwd") or "").strip().lower() != "image":
            return _ImageUnderstandingResult()

        meta.setdefault("chunk_role", "image")
        caption = self._derive_caption(
            chunk=chunk,
            meta=meta,
            enabled=bool(options.image_caption_enabled),
            deps=deps,
        )
        image_code_text, ocr_text, runtime.ocr_remaining = self._inspect_image(
            meta=meta,
            tenant_id=tenant_id,
            image_ocr_enabled=bool(options.image_ocr_enabled),
            image_ocr_max_chars=int(options.image_ocr_max_chars),
            ocr_remaining=runtime.ocr_remaining,
            deps=deps,
        )
        caption = self._redact_text(text=caption, options=options, deps=deps)
        if caption:
            meta["image_caption"] = caption
        ocr_text = self._redact_text(
            text=ocr_text,
            options=options,
            deps=deps,
            meta=meta,
            pii_key="image_ocr_pii_hits",
            secrets_key="image_ocr_secrets_hits",
        )
        if ocr_text:
            meta["image_ocr_text"] = ocr_text
            meta["image_ocr_chars"] = len(ocr_text)
        return _ImageUnderstandingResult(caption=caption, ocr_text=ocr_text, image_code_text=image_code_text)

    @staticmethod
    def _append_understanding_text(
        *,
        content: str,
        info: _ImageUnderstandingResult,
        deps: _ChunkAssetDeps,
    ) -> str:
        if not (info.caption or info.ocr_text or info.image_code_text):
            return content
        return str(
            deps.append_image_understanding_text(
                content,
                caption=info.caption,
                ocr_text=info.ocr_text,
                code_text=info.image_code_text,
            )
            or ""
        )

    @staticmethod
    def _populate_content_metadata(
        *,
        meta: dict[str, Any],
        content_norm: str,
        deps: _ChunkAssetDeps,
        force_hashes: bool = False,
    ) -> None:
        meta.setdefault("content_len", len(content_norm.strip()))
        infer_chunk_structure(meta, content_norm)
        try:
            meta.setdefault("chunk_quality", deps.score_chunk_quality(content_norm, meta=meta))
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
        try:
            meta.setdefault("chunk_semantic_role", classify_chunk_semantic_role(content=content_norm, meta=meta))
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
        try:
            meta.setdefault("chunk_type", classify_chunk_type(content=content_norm, meta=meta))
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
        if force_hashes or not str(meta.get("content_hash") or "").strip():
            meta["content_hash"] = hashlib.sha256(content_norm.strip().encode("utf-8", "ignore")).hexdigest()
            meta.setdefault("content_hash_algo", "sha256")
        if force_hashes or not str(meta.get("simhash64") or "").strip():
            try:
                meta["simhash64"] = simhash64_hex(simhash64(content_norm))
                meta.setdefault("simhash_algo", "simhash64_sha1")
            except Exception as exc:
                _log_processor_fallback("run", exc)

    def _attach_img_id(
        self,
        *,
        meta: dict[str, Any],
        content: str,
        tenant_id: UUID,
        document_id: UUID,
        chunk_index: int,
        runtime: _ChunkAssetRuntime,
    ) -> None:
        img_id = self._svc._extract_and_upload_image_to_minio(
            meta,
            tenant_id=str(tenant_id),
            dataset_id=runtime.dataset_id,
            document_id=str(document_id),
            chunk_index=chunk_index,
        )
        if not img_id:
            img_id = self._svc._extract_img_id_from_content(content)
        if not img_id:
            return
        meta["img_id"] = img_id
        normalize_image_metadata(meta)
        runtime.img_ids.append(img_id)

    def _emit_base_chunk(
        self,
        *,
        chunk: Document,
        content: str,
        meta: dict[str, Any],
        tenant_id: UUID,
        document_id: UUID,
        idx: int,
        runtime: _ChunkAssetRuntime,
        deps: _ChunkAssetDeps,
    ) -> None:
        content_norm = normalize_text(content, normalize_line_endings=True, remove_control_chars=True)
        self._populate_content_metadata(meta=meta, content_norm=content_norm, deps=deps)
        self._attach_img_id(
            meta=meta,
            content=content,
            tenant_id=tenant_id,
            document_id=document_id,
            chunk_index=idx,
            runtime=runtime,
        )
        runtime.out_chunks.append(Document(page_content=content, metadata=meta, id=getattr(chunk, "id", None)))
        runtime.out_idx += 1

    def _emit_ocr_chunk(
        self,
        *,
        ocr_text: str,
        parent_meta: dict[str, Any],
        parent_idx: int,
        document_id: UUID,
        runtime: _ChunkAssetRuntime,
        deps: _ChunkAssetDeps,
    ) -> None:
        if str(parent_meta.get("doc_type_kwd") or "").strip().lower() != "image" or not ocr_text:
            return

        ocr_norm = normalize_text(ocr_text, normalize_line_endings=True, remove_control_chars=True).strip()
        ocr_hash = hashlib.sha256(ocr_norm.encode("utf-8", "ignore")).hexdigest() if ocr_norm else ""
        if not ocr_hash or ocr_hash in runtime.seen_ocr_hashes:
            return

        runtime.seen_ocr_hashes.add(ocr_hash)
        ocr_meta = dict(parent_meta)
        ocr_meta["chunk_index"] = int(runtime.out_idx)
        ocr_meta["chunk_key"] = f"{str(document_id)}:{int(runtime.out_idx)}"
        ocr_meta["doc_type_kwd"] = "ocr"
        ocr_meta["content_type"] = "ocr"
        ocr_meta["chunk_role"] = "ocr"
        ocr_meta["image_parent_chunk_index"] = int(parent_idx)
        ensure_hierarchy_overlay_metadata(
            ocr_meta,
            document_id=str(document_id),
            chunk_index=int(runtime.out_idx),
        )
        for key in (
            "content_hash",
            "content_hash_algo",
            "content_len",
            "simhash64",
            "simhash_algo",
            "structure",
            "chunk_semantic_role",
            "chunk_type",
        ):
            ocr_meta.pop(key, None)
        ocr_meta["ocr_text_hash"] = str(ocr_hash)
        ocr_meta.setdefault("ocr_text_hash_algo", "sha256")
        ocr_content_norm = normalize_text(ocr_text, normalize_line_endings=True, remove_control_chars=True)
        self._populate_content_metadata(meta=ocr_meta, content_norm=ocr_content_norm, deps=deps, force_hashes=True)
        runtime.out_chunks.append(Document(page_content=ocr_text, metadata=ocr_meta))
        runtime.out_idx += 1

    @staticmethod
    def _apply_adjacency_metadata(out_chunks: list[Document], *, document_id: UUID) -> None:
        total_out = len(out_chunks)
        for index, doc in enumerate(out_chunks):
            meta = dict(getattr(doc, "metadata", None) or {})
            prev_idx = (index - 1) if index > 0 else None
            next_idx = (index + 1) if index < (total_out - 1) else None
            doc_id = str(meta.get("document_id") or document_id)
            meta["prev_chunk_index"] = prev_idx
            meta["next_chunk_index"] = next_idx
            meta["prev_chunk_key"] = f"{doc_id}:{prev_idx}" if prev_idx is not None else None
            meta["next_chunk_key"] = f"{doc_id}:{next_idx}" if next_idx is not None else None
            ensure_hierarchy_overlay_metadata(
                meta,
                document_id=doc_id,
                chunk_index=index,
                total_chunks=total_out,
            )
            doc.metadata = meta
        apply_sequence_hierarchy_metadata(
            [doc.metadata for doc in out_chunks if isinstance(getattr(doc, "metadata", None), dict)],
            document_id=str(document_id),
            basis="chunk_sequence",
            level="chunk",
        )

    def run(
        self,
        *,
        chunks: list[Document],
        tenant_id: UUID,
        document_id: UUID,
        options: ChunkAssetOptions,
    ) -> ChunkAssetResult:
        deps = self._load_deps()
        runtime = self._build_runtime(options)
        for chunk in chunks:
            idx = int(runtime.out_idx)
            meta = self._base_chunk_metadata(
                chunk=chunk,
                document_id=document_id,
                idx=idx,
                runtime=runtime,
            )
            info = self._image_understanding(
                chunk=chunk,
                meta=meta,
                tenant_id=tenant_id,
                options=options,
                deps=deps,
                runtime=runtime,
            )
            content = self._append_understanding_text(
                content=chunk.page_content or "",
                info=info,
                deps=deps,
            )
            self._emit_base_chunk(
                chunk=chunk,
                content=content,
                meta=meta,
                tenant_id=tenant_id,
                document_id=document_id,
                idx=idx,
                runtime=runtime,
                deps=deps,
            )
            self._emit_ocr_chunk(
                ocr_text=info.ocr_text,
                parent_meta=meta,
                parent_idx=idx,
                document_id=document_id,
                runtime=runtime,
                deps=deps,
            )

        self._apply_adjacency_metadata(runtime.out_chunks, document_id=document_id)
        return ChunkAssetResult(chunks=runtime.out_chunks, img_ids=runtime.img_ids)
