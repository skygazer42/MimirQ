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


class ParsingStage:
    def __init__(self, service):
        self._svc = service

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
            resolved_backend = "integrated"
            self._svc._record_processing_metadata(
                db,
                tenant_id,
                document_id,
                parser_backend=resolved_backend,
                chunk_strategy=resolved_chunk_strategy,
            )
            artifact_root = (
                Path(settings.UPLOAD_DIR)
                / str(tenant_id)
                / MIMIRQ_PARSE_DIRNAME
                / f"{str(document_id)}-integrated-{uuid.uuid4().hex}"
            )
            cancel_check = self._svc._build_cancel_check(db=db, tenant_id=tenant_id, document_id=document_id)

            async def cancel_check_worker() -> bool:
                return await cancel_check()

            try:
                result = await run_parser_subprocess(
                    tenant_id=tenant_id,
                    payload={
                        "action": "integrated_chunk",
                        "tenant_id": str(tenant_id),
                        "file_path": str(file_path),
                        "strategy": resolved_chunk_strategy,
                        "mode": "ingest",
                        "artifact_root": str(artifact_root),
                    },
                    cancel_check=cancel_check_worker,
                    timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
                )
            except SubprocessCancelled as exc:
                try:
                    shutil.rmtree(artifact_root, ignore_errors=True)
                except Exception as exc:
                    logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
                raise DocumentCancelledError(str(exc)) from exc
            except asyncio.CancelledError:
                try:
                    shutil.rmtree(artifact_root, ignore_errors=True)
                except Exception as exc:
                    logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
                raise
            except ParsingError as exc:
                raise RuntimeError(f"Integrated pipeline parsing failed: {str(exc)[:200]}") from exc

            chunks = [
                Document(
                    page_content=str(item.get("page_content") or ""),
                    metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                    id=item.get("id") if isinstance(item.get("id"), str) else None,
                )
                for item in (result.get("documents") or [])
                if isinstance(item, dict)
            ]
            return ParseResult(
                resolved_backend=resolved_backend,
                resolved_chunk_strategy=resolved_chunk_strategy,
                chunks=_attach_logical_source_metadata(chunks, db_document=db_document, file_path=file_path),
            )

        logger.info("Parsing document: %s", file_path)
        effective_parser_backend = parser_backend
        file_ext = file_path.suffix.lower()
        pdf_quality = None
        parse_cache_key: str | None = None
        parse_cache_hit = False
        parse_cache_age_ms: int | None = None
        if file_ext == ".pdf":
            requested = (parser_backend or "").strip().lower()
            if not requested or requested == "auto":
                cached_quality = None
                try:
                    m0 = db_document.doc_metadata or {}
                    q0 = m0.get("pdf_quality") if isinstance(m0, dict) else None
                    if isinstance(q0, dict) and q0.get("score") is not None:
                        cached_quality = dict(q0)
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
                    db_document.doc_metadata = metadata
                    db.commit()
                    db.refresh(db_document)

        parsed: dict[str, Any] | None = None
        documents: list[Document] = []

        # Optional: parse cache (MinIO). Best-effort and never blocks ingestion.
        try:
            if bool(getattr(settings, "PARSE_CACHE_ENABLED", False)) and bool(getattr(settings, "MINIO_ENABLED", False)):
                meta0 = dict(db_document.doc_metadata or {})
                file_sha = str(meta0.get("file_sha256") or "").strip().lower()
                pipeline_hash = str(meta0.get("pipeline_hash") or meta0.get("active_pipeline_hash") or "").strip()
                config_hash = pipeline_hash or "unknown"
                backend_key = str(effective_parser_backend or "").strip().lower()
                if file_sha and backend_key:
                    parse_cache_key = build_remote_parse_cache_key(
                        file_sha256=file_sha,
                        resolved_backend=backend_key,
                        config_hash=config_hash,
                        version=str(getattr(settings, "PARSE_CACHE_VERSION", "v1") or "v1"),
                    )
                    cached, age_ms = parse_cache_service.get(
                        tenant_id=str(tenant_id),
                        dataset_id=str(dataset_id),
                        cache_key=parse_cache_key,
                        ttl_sec=int(getattr(settings, "PARSE_CACHE_TTL_SEC", 0) or 0),
                        max_bytes=int(getattr(settings, "PARSE_CACHE_MAX_BYTES", 0) or 0),
                    )
                    if cached is not None and list(getattr(cached, "documents", None) or []):
                        parse_cache_hit = True
                        parse_cache_age_ms = age_ms
                        documents = [
                            Document(
                                page_content=str(item.get("page_content") or ""),
                                metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                                id=item.get("id") if isinstance(item.get("id"), str) else None,
                            )
                            for item in (cached.documents or [])
                            if isinstance(item, dict)
                        ]
                        # Record cache hit for observability (best-effort).
                        try:
                            meta_patch = dict(db_document.doc_metadata or {})
                            meta_patch["parse_cache"] = {
                                "schema": "mimirq.parse_cache_hit.v1",
                                "hit": True,
                                "age_ms": int(parse_cache_age_ms or 0),
                                "backend": backend_key,
                            }
                            db_document.doc_metadata = meta_patch
                            db.commit()
                            db.refresh(db_document)
                        except Exception as exc:
                            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
        except Exception as exc:
            _log_processor_fallback('run', exc)
            parse_cache_hit = False

        if not parse_cache_hit:
            artifact_root = (
                Path(settings.UPLOAD_DIR)
                / str(tenant_id)
                / MIMIRQ_PARSE_DIRNAME
                / f"{str(document_id)}-parse-{uuid.uuid4().hex}"
            )
            cancel_check = self._svc._build_cancel_check(db=db, tenant_id=tenant_id, document_id=document_id)

            async def cancel_check_worker() -> bool:
                return await cancel_check()

            try:
                payload = {
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
                parsed = await run_parser_subprocess(
                    tenant_id=tenant_id,
                    payload=payload,
                    cancel_check=cancel_check_worker,
                    timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
                )
            except SubprocessCancelled as exc:
                try:
                    shutil.rmtree(artifact_root, ignore_errors=True)
                except Exception as exc:
                    logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
                raise DocumentCancelledError(str(exc)) from exc
            except asyncio.CancelledError:
                try:
                    shutil.rmtree(artifact_root, ignore_errors=True)
                except Exception as exc:
                    logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
                raise
            except ParsingError as exc:
                raise RuntimeError(f"Parsing failed: {str(exc)[:200]}") from exc

            documents = [
                Document(
                    page_content=str(item.get("page_content") or ""),
                    metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                    id=item.get("id") if isinstance(item.get("id"), str) else None,
                )
                for item in (parsed.get("documents") or [])
                if isinstance(item, dict)
            ]

        documents = _attach_logical_source_metadata(documents, db_document=db_document, file_path=file_path)

        # Persist parse provenance for audit/debug (best-effort).
        try:
            prov = parsed.get("provenance") if isinstance(parsed, dict) else None
            if isinstance(prov, dict) and prov:
                meta = dict(db_document.doc_metadata or {})
                meta["parse_provenance"] = prov
                db_document.doc_metadata = meta
                db.commit()
                db.refresh(db_document)
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

        # Attach lightweight parsed-text quality metrics for observability/tuning.
        try:
            joined = _join_document_page_content(documents)
            quality = score_parsed_text_quality(joined).to_dict()
            seal_summary = _build_seal_summary(documents)
            specialty_signals = _seal_summary_to_specialty_signals(seal_summary)
            ocr_summary = _build_ocr_quality_summary(
                documents,
                low_confidence_threshold=float(settings.PARSE_QUALITY_OCR_LOW_CONFIDENCE_THRESHOLD),
            )
            meta = dict(db_document.doc_metadata or {})
            meta["parsed_text_quality"] = quality
            meta["parse_quality"] = score_document_parse_quality(
                pdf_quality=(pdf_quality if isinstance(pdf_quality, dict) else None),
                parsed_text_quality=quality,
                specialty_signals=specialty_signals,
            )
            if seal_summary is not None:
                meta["seal_summary"] = seal_summary
            if ocr_summary is not None:
                meta["ocr"] = ocr_summary
            artifact_stats = compute_parsing_artifact_stats(
                documents=documents,
                original_markdown=_join_original_markdown_for_persistence(documents),
                markdown=joined,
                pdf_quality=(pdf_quality if isinstance(pdf_quality, dict) else None),
            )
            meta.update(artifact_stats)
            # Lightweight "document portrait" for UI (best-effort, safe to ignore).
            try:
                meta["document_analytics_raw"] = compute_document_analytics(
                    markdown=joined,
                    documents=documents,
                    pdf_quality=(pdf_quality if isinstance(pdf_quality, dict) else None),
                    detect_language=bool(getattr(settings, "GOVERNANCE_DETECT_LANGUAGE", False)),
                    language_min_chars=int(getattr(settings, "GOVERNANCE_LANGUAGE_MIN_CHARS", 40) or 40),
                ).to_dict()
            except Exception as exc:
                logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
            meta = apply_parse_quality_gate_metadata(meta)
            db_document.doc_metadata = meta
            db.commit()
            db.refresh(db_document)
        except Exception as exc:
            logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

        # Parse cache write-through (best-effort, only when miss).
        if (not parse_cache_hit) and parse_cache_key and documents:
            try:
                meta0 = dict(db_document.doc_metadata or {})
                file_sha = str(meta0.get("file_sha256") or "").strip().lower()
                pipeline_hash = str(meta0.get("pipeline_hash") or meta0.get("active_pipeline_hash") or "").strip()
                config_hash = pipeline_hash or "unknown"
                backend_key = str(effective_parser_backend or "").strip().lower()
                entry = RemoteParseCacheEntry(
                    created_at=dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
                    file_sha256=file_sha,
                    resolved_backend=backend_key,
                    config_hash=config_hash,
                    documents=[
                        {
                            "page_content": str(d.page_content or ""),
                            "metadata": dict(d.metadata or {}),
                            "id": str(d.id) if isinstance(getattr(d, "id", None), str) else None,
                        }
                        for d in (documents or [])
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
        if not upload_enabled and not caption_enabled and not formula_enabled and not chart_enabled and not image_code_enabled:
            return InlineAssetResult(documents=documents, uploaded_img_ids=[], next_asset_index=int(start_index or 0))

        inline_cache: dict[str, str] = {}
        asset_idx = int(start_index or 0)
        uploaded: list[str] = []
        processed_docs: list[Document] = []
        image_codes_added_total = 0
        image_code_audit: dict[str, Any] | None = None
        captions_added_total = 0
        caption_backend: str | None = None
        caption_audit: dict[str, Any] | None = None
        formulas_added_total = 0
        formula_backend: str | None = None
        formula_audit: dict[str, Any] | None = None
        charts_added_total = 0
        chart_backend: str | None = None
        chart_audit: dict[str, Any] | None = None

        for doc in documents:
            content = doc.page_content or ""
            original_meta = dict(doc.metadata or {})
            origin_for_doc = origin_path
            base_dir = original_meta.get("asset_base_dir")
            if isinstance(base_dir, str) and base_dir.strip():
                origin_for_doc = Path(base_dir.strip())

            next_content = content
            next_meta = dict(original_meta)
            if next_content:
                try:
                    next_content, added, audit = add_image_code_blocks(
                        next_content,
                        origin_path=origin_for_doc,
                    )
                    image_codes_added_total += int(added or 0)
                    image_code_audit = audit.to_dict()
                    raw_code_elements = getattr(audit, "code_elements", None)
                    if isinstance(raw_code_elements, list) and raw_code_elements:
                        derived = [item for item in (next_meta.get("derived_elements") or []) if isinstance(item, dict)]
                        page_hint = next_meta.get("element_page") or next_meta.get("page")
                        for raw_element in raw_code_elements:
                            if not isinstance(raw_element, dict):
                                continue
                            item = dict(raw_element)
                            if item.get("page") is None and page_hint is not None:
                                item["page"] = page_hint
                            if not str(item.get("id") or "").strip():
                                page_part = item.get("page") if item.get("page") is not None else "na"
                                item["id"] = f"image_code:{page_part}:{len(derived)}"
                            derived.append(item)
                        if derived:
                            next_meta["derived_elements"] = derived
                except Exception as exc:
                    logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
            # Opt3: Formula OCR / LaTeX conversion (best-effort) before asset rewriting
            # so we can still read local image files.
            if formula_enabled and next_content:
                try:
                    next_content, added, audit = add_formula_latex_blocks(
                        next_content,
                        origin_path=origin_for_doc,
                        api_url=formula_url,
                        timeout_sec=float(getattr(settings, "FORMULA_OCR_TIMEOUT_SEC", 60) or 60),
                        max_images=int(getattr(settings, "FORMULA_OCR_MAX_IMAGES", 12) or 12),
                        max_image_bytes=int(getattr(settings, "FORMULA_OCR_MAX_IMAGE_BYTES", 5_000_000) or 5_000_000),
                        max_latex_chars=int(getattr(settings, "FORMULA_OCR_MAX_LATEX_CHARS", 2000) or 2000),
                    )
                    formulas_added_total += int(added or 0)
                    formula_backend = "formula_http"
                    formula_audit = audit.to_dict()
                    raw_formula_elements = getattr(audit, "formula_elements", None)
                    if isinstance(raw_formula_elements, list) and raw_formula_elements:
                        derived = [item for item in (next_meta.get("derived_elements") or []) if isinstance(item, dict)]
                        page_hint = next_meta.get("element_page") or next_meta.get("page")
                        for raw_element in raw_formula_elements:
                            if not isinstance(raw_element, dict):
                                continue
                            item = dict(raw_element)
                            if item.get("page") is None and page_hint is not None:
                                item["page"] = page_hint
                            if not str(item.get("id") or "").strip():
                                page_part = item.get("page") if item.get("page") is not None else "na"
                                item["id"] = f"formula_ocr:{page_part}:{len(derived)}"
                            derived.append(item)
                        if derived:
                            next_meta["derived_elements"] = derived
                except Exception as exc:
                    _log_processor_fallback('run', exc)
                    # Never fail ingest due to optional enrichment.

            # Best-effort chart -> structured data extraction.
            if chart_enabled and next_content:
                try:
                    next_content, added, audit = add_chart_data_blocks(
                        next_content,
                        origin_path=origin_for_doc,
                        max_images=int(getattr(settings, "CHART_TO_DATA_MAX_IMAGES", 8) or 8),
                        max_image_bytes=int(getattr(settings, "CHART_TO_DATA_MAX_IMAGE_BYTES", 5_000_000) or 5_000_000),
                        timeout_sec=float(getattr(settings, "CHART_TO_DATA_TIMEOUT_SEC", 20) or 20),
                    )
                    charts_added_total += int(added or 0)
                    chart_backend = "chart_http"
                    chart_audit = audit.to_dict()
                except Exception as exc:
                    logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

            # Opt5: image captions (best-effort) before asset rewriting so we can still
            # read local image files when using an external VLM backend.
            if caption_enabled:
                try:
                    if bool(getattr(settings, "IMAGE_CAPTION_VLM_ENABLED", False)) and str(
                        getattr(settings, "IMAGE_CAPTION_VLM_API_URL", "") or ""
                    ).strip():
                        next_content, added, audit = add_vlm_image_captions(
                            next_content,
                            origin_path=origin_for_doc,
                            api_url=str(getattr(settings, "IMAGE_CAPTION_VLM_API_URL", "") or ""),
                            timeout_sec=float(getattr(settings, "IMAGE_CAPTION_VLM_TIMEOUT_SEC", 60) or 60),
                            max_images=int(getattr(settings, "IMAGE_CAPTION_VLM_MAX_IMAGES", 20) or 20),
                            max_image_bytes=int(getattr(settings, "IMAGE_CAPTION_VLM_MAX_IMAGE_BYTES", 5_000_000) or 5_000_000),
                            max_caption_chars=int(getattr(settings, "IMAGE_CAPTION_VLM_MAX_CAPTION_CHARS", 200) or 200),
                        )
                        captions_added_total += int(added or 0)
                        caption_backend = "vlm_http"
                        # Keep last audit (best-effort); do not grow unbounded.
                        caption_audit = audit.to_dict()
                    else:
                        next_content, added = add_image_captions(next_content)
                        captions_added_total += int(added or 0)
                        caption_backend = "heuristic"
                except Exception as exc:
                    _log_processor_fallback('run', exc)
                    # Never fail ingest due to optional captioning.

            if upload_enabled:
                new_content, new_img_ids, asset_idx = self._svc._upload_inline_images_to_minio(
                    markdown_text=next_content,
                    tenant_id=str(tenant_id),
                    dataset_id=dataset_id,
                    document_id=str(document_id),
                    cache=inline_cache,
                    start_index=asset_idx,
                    origin_path=origin_for_doc,
                )
                uploaded.extend(list(new_img_ids or []))
            else:
                new_content = next_content
                new_img_ids = []

            if new_content != content:
                processed_docs.append(
                    Document(
                        page_content=new_content,
                        metadata=next_meta,
                        id=doc.id,
                    )
                )
            elif next_meta != original_meta:
                processed_docs.append(
                    Document(
                        page_content=content,
                        metadata=next_meta,
                        id=doc.id,
                    )
                )
            else:
                processed_docs.append(doc)

        return InlineAssetResult(
            documents=processed_docs,
            uploaded_img_ids=uploaded,
            next_asset_index=asset_idx,
            image_codes_added=int(image_codes_added_total),
            image_code_audit=(dict(image_code_audit) if isinstance(image_code_audit, dict) else None),
            captions_added=int(captions_added_total),
            caption_backend=caption_backend,
            caption_audit=(dict(caption_audit) if isinstance(caption_audit, dict) else None),
            formulas_added=int(formulas_added_total),
            formula_backend=formula_backend,
            formula_audit=(dict(formula_audit) if isinstance(formula_audit, dict) else None),
            charts_added=int(charts_added_total),
            chart_backend=chart_backend,
            chart_audit=(dict(chart_audit) if isinstance(chart_audit, dict) else None),
        )


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
            plugin_params = {**params, **dict(chunk_python_params or {})}
            chunks = apply_chunk_python_plugin(
                documents,
                plugin_ref=plugin_ref,
                params=plugin_params,
                context={
                    "chunk_strategy": chunk_strategy,
                    "chunk_size": int(chunk_size),
                    "chunk_overlap": int(chunk_overlap),
                },
            )
            return ChunkingResult(chunks=chunks)

        def _to_bool(v: object) -> bool | None:
            if v is None:
                return None
            if isinstance(v, bool):
                return v
            if isinstance(v, (int, float)):
                return bool(v)
            if isinstance(v, str):
                s = v.strip().lower()
                if s in {"1", "true", "yes", "y", "on"}:
                    return True
                if s in {"0", "false", "no", "n", "off"}:
                    return False
            return None

        def _to_int(v: object) -> int | None:
            if v is None:
                return None
            if isinstance(v, bool):
                return int(v)
            if isinstance(v, (int, float)):
                try:
                    return int(v)
                except (TypeError, ValueError, AttributeError):
                    return None
            if isinstance(v, str):
                try:
                    return int(float(v.strip()))
                except (TypeError, ValueError, AttributeError):
                    return None
            return None

        def _to_float(v: object) -> float | None:
            if v is None:
                return None
            if isinstance(v, bool):
                return float(v)
            if isinstance(v, (int, float)):
                try:
                    return float(v)
                except (TypeError, ValueError, AttributeError):
                    return None
            if isinstance(v, str):
                try:
                    return float(v.strip())
                except (TypeError, ValueError, AttributeError):
                    return None
            return None

        # Separator chunking needs preset/custom mapping (preview supports this too).
        if (chunk_strategy or "").strip().lower() == "separator":
            preset = str(params.get("separator_preset") or "").strip() or "paragraph"
            if preset != "custom":
                sep_value = SeparatorChunker.PRESET_SEPARATORS.get(preset)
                if sep_value is None:
                    raise ValueError(f"Invalid separator_preset: {preset}")
            else:
                raw = params.get("separator")
                if raw is None:
                    raw = params.get("separator_custom")
                sep_value = str(raw or "")
                if not sep_value:
                    sep_value = "\n\n"
                # Support common escaped inputs like "\\n\\n" (match frontend behavior).
                try:
                    import json as _json  # local import to keep module deps minimal

                    escaped = sep_value.replace("\"", "\\\"")
                    sep_value = _json.loads(f"\"{escaped}\"")
                except Exception as exc:
                    logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

            keep_sep = params.get("keep_separator")
            keep_sep_norm = _to_bool(keep_sep)
            if keep_sep_norm is None:
                keep_sep = True
            else:
                keep_sep = keep_sep_norm

            max_chunk_size = _to_int(params.get("separator_max_chunk_size"))
            if max_chunk_size is None:
                max_chunk_size = _to_int(params.get("max_chunk_size"))
            max_chunk_size = int(max_chunk_size or 0)

            chunker = SeparatorChunker(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separator=sep_value,
                keep_separator=bool(keep_sep),
                max_chunk_size=max_chunk_size,
            )
        else:
            # Common numeric coercions for strategy kwargs (avoid accidental string types from patches).
            if "child_ratio" in params:
                r = _to_float(params.get("child_ratio"))
                if r is not None:
                    params["child_ratio"] = r
            if "min_child_size" in params:
                n = _to_int(params.get("min_child_size"))
                if n is not None:
                    params["min_child_size"] = n

            chunker = chunker_factory.get_chunker(
                chunk_strategy,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                **params,
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

    def run(
        self,
        *,
        chunks: list[Document],
        tenant_id: UUID,
        document_id: UUID,
        options: ChunkAssetOptions,
    ) -> ChunkAssetResult:
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

        dataset_id = options.dataset_id
        resolved_backend = options.resolved_backend
        resolved_chunk_strategy = options.resolved_chunk_strategy
        image_caption_enabled = options.image_caption_enabled
        image_ocr_enabled = options.image_ocr_enabled
        image_ocr_max_chars = options.image_ocr_max_chars
        pii_anonymize = options.pii_anonymize
        pii_mode = options.pii_mode
        pii_mask = options.pii_mask
        secrets_redact = options.secrets_redact
        secrets_mode = options.secrets_mode
        secrets_mask = options.secrets_mask

        max_images = max(0, int(options.image_ocr_max_images or 0))
        ocr_remaining: int | None = (max_images if max_images > 0 else None)

        img_ids: list[str] = []
        out_chunks: list[Document] = []
        out_idx = 0
        seen_ocr_hashes: set[str] = set()

        for chunk in chunks:
            # Assign chunk_index in output order (may differ from input order when we emit OCR chunks).
            idx = int(out_idx)
            meta = dict(chunk.metadata or {})
            meta.setdefault("dataset_id", str(dataset_id))
            meta["document_id"] = str(document_id)
            meta["chunk_index"] = idx
            meta["parser_backend"] = resolved_backend
            meta.setdefault("chunk_strategy", resolved_chunk_strategy)
            meta["resolved_chunk_strategy"] = resolved_chunk_strategy
            meta.setdefault("chunk_key", f"{str(document_id)}:{idx}")
            normalize_section_metadata(meta)
            ensure_hierarchy_overlay_metadata(
                meta,
                document_id=str(document_id),
                chunk_index=idx,
            )

            # Image understanding (best-effort): keep it off by default; never fail ingest.
            caption = ""
            ocr_text = ""
            image_code_text = ""
            doc_type = str(meta.get("doc_type_kwd") or "").strip().lower()
            if doc_type == "image":
                # Structural chunk roles: keep this lightweight and deterministic so downstream
                # can filter/rerank image vs OCR chunks explicitly.
                meta.setdefault("chunk_role", "image")
                if bool(image_caption_enabled):
                    try:
                        caption = derive_image_caption(chunk.page_content or "", meta)
                    except Exception as exc:
                        _log_processor_fallback('run', exc)
                        caption = ""
                need_image_inspection = (
                    not str(meta.get("visual_kind") or "").strip()
                    or not str(meta.get("image_code_text") or "").strip()
                    or (bool(image_ocr_enabled) and (ocr_remaining is None or ocr_remaining > 0))
                )
                if need_image_inspection:
                    img, should_close = load_image_for_ocr(meta, _tenant_id=str(tenant_id))
                    try:
                        if img is not None:
                            try:
                                code_info = decode_image_codes(img)
                            except Exception as exc:
                                _log_processor_fallback('run', exc)
                                code_info = {}
                            if isinstance(code_info, dict):
                                image_code_text = str(code_info.get("text") or "").strip()
                                if image_code_text:
                                    meta["image_code_text"] = image_code_text
                                    raw_values = code_info.get("values")
                                    if isinstance(raw_values, list):
                                        meta["image_code_values"] = [str(item).strip() for item in raw_values if str(item).strip()]
                                visual_kind = str(code_info.get("visual_kind") or "").strip().lower()
                                if visual_kind:
                                    meta["visual_kind"] = visual_kind
                            if not str(meta.get("visual_kind") or "").strip():
                                try:
                                    visual_kind = str(infer_visual_kind_from_pixels(img) or "").strip().lower()
                                except Exception as exc:
                                    _log_processor_fallback('run', exc)
                                    visual_kind = ""
                                if visual_kind:
                                    meta["visual_kind"] = visual_kind
                            if bool(image_ocr_enabled) and (ocr_remaining is None or ocr_remaining > 0):
                                ocr_text = ocr_image(img, _max_chars=int(image_ocr_max_chars))
                                if ocr_remaining is not None:
                                    ocr_remaining -= 1
                    except Exception as exc:
                        _log_processor_fallback('run', exc)
                        ocr_text = ""
                    finally:
                        if should_close and img is not None:
                            try:
                                img.close()
                            except Exception as exc:
                                logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

                # Policy-driven safety: OCR/caption text is appended after governance cleaning, so apply
                # PII/secret redactions here (best-effort).
                if caption:
                    try:
                        caption, _pii_hits, _sec_hits = redact_ocr_text(
                            caption,
                            pii_anonymize=bool(pii_anonymize),
                            pii_mode=str(pii_mode or "mask"),
                            pii_mask=str(pii_mask or REDACTED_MASK),
                            secrets_redact=bool(secrets_redact),
                            secrets_mode=str(secrets_mode or "mask"),
                            secrets_mask=str(secrets_mask or SECRET_MASK),
                        )
                    except Exception as exc:
                        _log_processor_fallback('run', exc)
                        # Fail-closed when redaction is enabled: do not emit raw caption.
                        if bool(pii_anonymize) or bool(secrets_redact):
                            caption = str(pii_mask or REDACTED_MASK) if bool(pii_anonymize) else str(secrets_mask or SECRET_MASK)
                if caption:
                    meta["image_caption"] = caption

                if ocr_text:
                    try:
                        ocr_text, pii_hits, sec_hits = redact_ocr_text(
                            ocr_text,
                            pii_anonymize=bool(pii_anonymize),
                            pii_mode=str(pii_mode or "mask"),
                            pii_mask=str(pii_mask or REDACTED_MASK),
                            secrets_redact=bool(secrets_redact),
                            secrets_mode=str(secrets_mode or "mask"),
                            secrets_mask=str(secrets_mask or SECRET_MASK),
                        )
                        if pii_hits:
                            meta["image_ocr_pii_hits"] = {str(k): int(v) for k, v in pii_hits.items() if int(v or 0) > 0}
                        if sec_hits:
                            meta["image_ocr_secrets_hits"] = {str(k): int(v) for k, v in sec_hits.items() if int(v or 0) > 0}
                    except Exception as exc:
                        _log_processor_fallback('run', exc)
                        # Fail-closed when redaction is enabled: do not emit raw OCR.
                        if bool(pii_anonymize) or bool(secrets_redact):
                            ocr_text = str(pii_mask or REDACTED_MASK) if bool(pii_anonymize) else str(secrets_mask or SECRET_MASK)
                        else:
                            ocr_text = ""
                    if ocr_text:
                        meta["image_ocr_text"] = ocr_text
                        meta["image_ocr_chars"] = len(ocr_text)

                # Keep OCR in the image chunk content for backwards compatibility (retrieval expects it),
                # but also emit an OCR-only chunk (role="ocr") to enable dedup and explicit filtering.
                if caption or ocr_text or image_code_text:
                    chunk.page_content = append_image_understanding_text(
                        chunk.page_content or "",
                        caption=caption,
                        ocr_text=ocr_text,
                        code_text=image_code_text,
                    )

            content_norm = normalize_text(chunk.page_content or "", normalize_line_endings=True, remove_control_chars=True)
            meta.setdefault("content_len", len(content_norm.strip()))
            infer_chunk_structure(meta, content_norm)
            # Per-chunk quality scoring (noise/boilerplate) for debug + downstream filtering.
            try:
                meta.setdefault("chunk_quality", score_chunk_quality(content_norm, meta=meta))
            except Exception as exc:
                logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
            # Lightweight semantic role labels (deterministic): helps filtering/reranking.
            # Keep separate from existing `chunk_role` (parent/child/qa/etc).
            try:
                meta.setdefault(
                    "chunk_semantic_role",
                    classify_chunk_semantic_role(content=content_norm, meta=meta),
                )
            except Exception as exc:
                logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
            try:
                meta.setdefault(
                    "chunk_type",
                    classify_chunk_type(content=content_norm, meta=meta),
                )
            except Exception as exc:
                logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
            if not isinstance(meta.get("content_hash"), str) or not str(meta.get("content_hash") or "").strip():
                meta["content_hash"] = hashlib.sha256(content_norm.strip().encode("utf-8", "ignore")).hexdigest()
                meta.setdefault("content_hash_algo", "sha256")
            if not isinstance(meta.get("simhash64"), str) or not str(meta.get("simhash64") or "").strip():
                try:
                    meta["simhash64"] = simhash64_hex(simhash64(content_norm))
                    meta.setdefault("simhash_algo", "simhash64_sha1")
                except Exception as exc:
                    _log_processor_fallback('run', exc)
                    # Best-effort only.
            chunk.metadata = meta

            img_id = self._svc._extract_and_upload_image_to_minio(
                meta,
                tenant_id=str(tenant_id),
                dataset_id=dataset_id,
                document_id=str(document_id),
                chunk_index=idx,
            )
            if not img_id:
                img_id = self._svc._extract_img_id_from_content(chunk.page_content)
            if img_id:
                meta["img_id"] = img_id
                normalize_image_metadata(meta)
                chunk.metadata = meta
                img_ids.append(img_id)

            # Emit the (possibly enriched) base chunk.
            out_chunks.append(Document(page_content=chunk.page_content or "", metadata=meta, id=getattr(chunk, "id", None)))
            out_idx += 1

            # Optional: OCR child chunk (dedup by OCR text hash).
            if doc_type == "image" and ocr_text:
                ocr_norm = normalize_text(ocr_text, normalize_line_endings=True, remove_control_chars=True).strip()
                ocr_hash = hashlib.sha256(ocr_norm.encode("utf-8", "ignore")).hexdigest() if ocr_norm else ""
                if ocr_hash and ocr_hash not in seen_ocr_hashes:
                    seen_ocr_hashes.add(ocr_hash)
                    ocr_meta = dict(meta)
                    ocr_meta["chunk_index"] = int(out_idx)
                    ocr_meta["chunk_key"] = f"{str(document_id)}:{int(out_idx)}"
                    ocr_meta["doc_type_kwd"] = "ocr"
                    ocr_meta["content_type"] = "ocr"
                    ocr_meta["chunk_role"] = "ocr"
                    ocr_meta["image_parent_chunk_index"] = int(idx)
                    ensure_hierarchy_overlay_metadata(
                        ocr_meta,
                        document_id=str(document_id),
                        chunk_index=int(out_idx),
                    )
                    # Recompute content-derived fields for OCR chunk.
                    for k in ("content_hash", "content_hash_algo", "content_len", "simhash64", "simhash_algo", "structure", "chunk_semantic_role", "chunk_type"):
                        ocr_meta.pop(k, None)
                    ocr_meta["ocr_text_hash"] = str(ocr_hash)
                    ocr_meta.setdefault("ocr_text_hash_algo", "sha256")

                    ocr_content_norm = normalize_text(ocr_text, normalize_line_endings=True, remove_control_chars=True)
                    ocr_meta.setdefault("content_len", len(ocr_content_norm.strip()))
                    infer_chunk_structure(ocr_meta, ocr_content_norm)
                    try:
                        ocr_meta.setdefault("chunk_quality", score_chunk_quality(ocr_content_norm, meta=ocr_meta))
                    except Exception as exc:
                        logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
                    try:
                        ocr_meta.setdefault(
                            "chunk_semantic_role",
                            classify_chunk_semantic_role(content=ocr_content_norm, meta=ocr_meta),
                        )
                    except Exception as exc:
                        logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
                    try:
                        ocr_meta.setdefault(
                            "chunk_type",
                            classify_chunk_type(content=ocr_content_norm, meta=ocr_meta),
                        )
                    except Exception as exc:
                        logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)
                    ocr_meta["content_hash"] = hashlib.sha256(ocr_content_norm.strip().encode("utf-8", "ignore")).hexdigest()
                    ocr_meta.setdefault("content_hash_algo", "sha256")
                    try:
                        ocr_meta["simhash64"] = simhash64_hex(simhash64(ocr_content_norm))
                        ocr_meta.setdefault("simhash_algo", "simhash64_sha1")
                    except Exception as exc:
                        logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)

                    out_chunks.append(Document(page_content=ocr_text, metadata=ocr_meta))
                    out_idx += 1

        # Adjacency graph (prev/next) for stitching + UI diagnostics:
        # - Stored in chunk metadata so it survives persistence/indexing.
        # - Computed on the final emitted chunk order (including OCR-only chunks).
        total_out = len(out_chunks)
        for i, doc in enumerate(out_chunks):
            meta = dict(getattr(doc, "metadata", None) or {})
            prev_idx = (i - 1) if i > 0 else None
            next_idx = (i + 1) if i < (total_out - 1) else None
            meta["prev_chunk_index"] = prev_idx
            meta["next_chunk_index"] = next_idx
            doc_id = str(meta.get("document_id") or document_id)
            meta["prev_chunk_key"] = f"{doc_id}:{prev_idx}" if prev_idx is not None else None
            meta["next_chunk_key"] = f"{doc_id}:{next_idx}" if next_idx is not None else None
            ensure_hierarchy_overlay_metadata(
                meta,
                document_id=doc_id,
                chunk_index=i,
                total_chunks=total_out,
            )
            doc.metadata = meta
        apply_sequence_hierarchy_metadata(
            [doc.metadata for doc in out_chunks if isinstance(getattr(doc, "metadata", None), dict)],
            document_id=str(document_id),
            basis="chunk_sequence",
            level="chunk",
        )

        return ChunkAssetResult(chunks=out_chunks, img_ids=img_ids)
