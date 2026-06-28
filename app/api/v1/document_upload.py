import asyncio
import contextlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentBatchUploadResponse, DocumentDetail
from app.api.v1.documents import UrlUploadRequest
from app.core.config import settings
from app.core.database import get_db
from app.rag.core.logging import get_logger

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@dataclass
class PipelineOverridesFormFields:
    governance_enabled: bool | None = Form(None)
    governance_remove_toc_lines: bool | None = Form(None)
    governance_remove_noise_lines: bool | None = Form(None)
    governance_unwrap_lines: bool | None = Form(None)
    governance_remove_common_lines: bool | None = Form(None)
    governance_unwrap_max_line_length: int | None = Form(None)
    governance_noise_min_chars: int | None = Form(None)
    governance_noise_ratio_threshold: float | None = Form(None)
    governance_common_lines_min_docs: int | None = Form(None)
    governance_common_lines_min_ratio: float | None = Form(None)
    chunk_size: int | None = Form(None)
    chunk_overlap: int | None = Form(None)
    chunk_vector_enabled: bool | None = Form(None)
    bm25_index_enabled: bool | None = Form(None)
    kg_enabled: bool | None = Form(None)
    event_vector_enabled: bool | None = Form(None)
    entity_vector_enabled: bool | None = Form(None)


@dataclass
class UploadDocumentFormFields:
    parser_backend: str = Form(settings.DEFAULT_PARSER_BACKEND)
    chunk_strategy: str = Form(settings.DEFAULT_CHUNK_STRATEGY)
    pipeline: str | None = Form(None)
    dataset_id: UUID | None = Form(None)
    user_metadata: str | None = Form(None)


@dataclass
class UploadDocumentsBatchFormFields:
    parser_backend: str = Form(settings.DEFAULT_PARSER_BACKEND)
    chunk_strategy: str = Form(settings.DEFAULT_CHUNK_STRATEGY)
    pipeline: str | None = Form(None)
    dataset_id: UUID | None = Form(None)
    precheck_first: bool = Form(False)
    precheck_only: bool = Form(False)
    upload_only: bool = Form(False)
    user_metadata_map: str | None = Form(None)
    max_concurrent: int = Form(5)


@router.post("/upload", response_model=DocumentDetail, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(...)],
    form: Annotated[UploadDocumentFormFields, Depends()],
    overrides_form: Annotated[PipelineOverridesFormFields, Depends()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    from app.api.v1 import documents as documents_module  # Local import to avoid router circular import.

    raw_filename = file.filename
    upload_key = documents_module._normalize_upload_key(raw_filename)
    source_path = upload_key if "/" in upload_key else None
    file.filename = documents_module._sanitize_filename(raw_filename)

    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}",
        )

    parser_backend = form.parser_backend
    chunk_strategy = form.chunk_strategy
    pipeline = form.pipeline
    dataset_id = form.dataset_id
    user_metadata = form.user_metadata

    pipeline_parsed = documents_module._parse_pipeline_json(pipeline)
    pipeline_overrides = documents_module.PipelineOptionOverrides(**asdict(overrides_form))
    pipeline_options = documents_module._to_pipeline_options(
        pipeline=pipeline_parsed,
        overrides=pipeline_overrides,
    )
    dataset = documents_module._resolve_writable_dataset(db, tenant_id, account_id, dataset_id)

    dataset_meta = (getattr(dataset, "dataset_metadata", None) or {}) if dataset is not None else {}
    policy = documents_module.parse_ingestion_policy_from_metadata(
        dataset_meta if isinstance(dataset_meta, dict) else {}
    )  # type: ignore[arg-type]
    matched_rule = documents_module.match_ingestion_rule(policy, filename=upload_key or file.filename, file_ext=file_ext)

    ingestion_meta: dict[str, Any] | None = None
    dataset_default_pb = None
    dataset_default_cs = None
    if isinstance(dataset_meta, dict):
        raw_pb = dataset_meta.get("default_parser_backend")
        raw_cs = dataset_meta.get("default_chunk_strategy")
        if isinstance(raw_pb, str) and raw_pb.strip():
            dataset_default_pb = raw_pb.strip().lower()
        if isinstance(raw_cs, str) and raw_cs.strip():
            dataset_default_cs = raw_cs.strip().lower()

    global_default_pb = (
        str(getattr(settings, "DEFAULT_PARSER_BACKEND", "auto") or "auto").strip().lower() or "auto"
    )
    global_default_cs = (
        str(getattr(settings, "DEFAULT_CHUNK_STRATEGY", "langchain_recursive") or "langchain_recursive")
        .strip()
        .lower()
        or "langchain_recursive"
    )
    default_pb_eff = dataset_default_pb or global_default_pb
    default_cs_eff = dataset_default_cs or global_default_cs

    parser_backend_choice: str = parser_backend
    chunk_strategy_choice: str = chunk_strategy

    req_pb = (parser_backend or "").strip().lower()
    if dataset_default_pb and req_pb in {"", "auto", global_default_pb}:
        parser_backend_choice = dataset_default_pb

    req_cs = (chunk_strategy or "").strip().lower()
    if dataset_default_cs and req_cs in {"", global_default_cs}:
        chunk_strategy_choice = dataset_default_cs

    preprocess_steps: list[dict] = []
    policy_patch = documents_module.PipelineOptions()

    if matched_rule is not None:
        default_pb = default_pb_eff
        req_pb = (parser_backend_choice or "").strip().lower()
        if req_pb in {"", "auto", default_pb} and matched_rule.parser_backend:
            parser_backend_choice = str(matched_rule.parser_backend)

        default_cs = default_cs_eff
        req_cs = (chunk_strategy_choice or "").strip().lower()
        if req_cs in {"", default_cs} and matched_rule.chunk_strategy:
            chunk_strategy_choice = str(matched_rule.chunk_strategy)

        pp = getattr(matched_rule, "preprocess", None)
        steps = getattr(pp, "steps", None) if pp is not None and bool(getattr(pp, "enabled", True)) else None
        if isinstance(steps, list) and steps:
            preprocess_steps = [
                {
                    "id": str(getattr(s, "id", "") or "").strip(),
                    "params": dict(getattr(s, "params", {}) or {}),
                }
                for s in steps
            ]

        patch_dict: dict[str, Any] = {}
        profile_ref = getattr(matched_rule, "governance_profile_ref", None)
        if isinstance(profile_ref, str) and profile_ref.strip():
            try:
                resolved = documents_module.resolve_governance_profile_ref(
                    db=db,
                    tenant_id=tenant_id,
                    profile_ref=profile_ref.strip(),
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid governance_profile_ref: {str(exc)[:120]}") from exc
            patch_dict.update(dict(resolved.pipeline_patch or {}))
            if resolved.regex_rules:
                patch_dict["governance_regex_rules"] = list(resolved.regex_rules)

        patch_dict.update(dict(getattr(matched_rule, "pipeline_patch", None) or {}))
        if patch_dict:
            policy_patch = documents_module.PipelineOptions(**patch_dict)

        ingestion_meta = {
            "version": str(getattr(policy, "version", "1") if policy is not None else "1"),
            "rule": {"id": matched_rule.id, "name": matched_rule.name},
            "preprocess": {"enabled": bool(preprocess_steps), "steps": preprocess_steps},
            "governance_profile_ref": (
                profile_ref.strip() if isinstance(profile_ref, str) and profile_ref.strip() else None
            ),
        }

    pipeline_options = documents_module.merge_pipeline_options(policy_patch, pipeline_options)

    try:
        requested_parser_backend = (parser_backend_choice or "").strip().lower()
        if file_ext == ".pdf" and requested_parser_backend in {"", "auto"}:
            resolved_parser_backend = "auto"
        else:
            resolved_parser_backend = documents_module.parser_factory.resolve_backend(
                file_ext,
                parser_backend_choice,
            )
        resolved_chunk_strategy = documents_module.chunker_factory.resolve_strategy(chunk_strategy_choice)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pipeline_effective = documents_module.resolve_pipeline_effective(
        dataset_metadata=(getattr(dataset, "dataset_metadata", None) or {}),
        document_metadata={},
        request_overrides=pipeline_options,
    )
    if resolved_chunk_strategy not in documents_module.chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
        documents_module._validate_chunk_params(
            pipeline_effective.chunk_size,
            pipeline_effective.chunk_overlap,
        )

    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_id = uuid.uuid4()
    file_path = upload_dir / f"{file_id}{file_ext}"

    file_size, file_sha256 = await documents_module.save_upload_file_with_hash(
        file, file_path, max_bytes=settings.MAX_FILE_SIZE
    )

    try:
        from app.services.tenant_quota_service import enforce_tenant_upload_quotas

        enforce_tenant_upload_quotas(
            db,
            tenant_id=tenant_id,
            additional_docs=1,
            additional_bytes=int(file_size or 0),
        )
    except HTTPException:
        with contextlib.suppress(OSError):
            file_path.unlink(missing_ok=True)
        raise

    doc_metadata = {
        "parser_backend": resolved_parser_backend,
        "parser_backend_requested": (parser_backend or "").lower(),
        "chunk_strategy": resolved_chunk_strategy,
        "chunk_strategy_requested": (chunk_strategy or "").lower(),
    }
    if source_path:
        doc_metadata["source_path"] = source_path
    if isinstance(file_sha256, str) and file_sha256:
        doc_metadata["file_sha256"] = file_sha256
    documents_module.upsert_pipeline_metadata(doc_metadata, options=pipeline_options)
    if ingestion_meta:
        doc_metadata["ingestion"] = ingestion_meta

    if isinstance(user_metadata, str) and user_metadata.strip():
        raw = user_metadata.strip()
        max_len = int(getattr(settings, "USER_METADATA_FORM_JSON_MAX_CHARS", 20_000) or 20_000)
        if max_len > 0 and len(raw) > max_len:
            raise HTTPException(status_code=400, detail="user_metadata is too large")
        try:
            obj = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="Invalid user_metadata JSON (expect UTF-8)") from exc
        if not isinstance(obj, dict):
            raise HTTPException(status_code=400, detail="user_metadata must be a JSON object")
        doc_metadata["user"] = documents_module._apply_user_metadata_patch(current={}, patch=obj, replace=True)
    pipeline_hash = documents_module._compute_pipeline_hash(doc_metadata)
    doc_metadata["pipeline_hash"] = pipeline_hash
    doc_metadata.setdefault("active_pipeline_hash", pipeline_hash)
    doc_metadata.setdefault("active_pipeline_ready", False)

    if isinstance(file_sha256, str) and file_sha256 and pipeline_hash and dataset is not None:
        try:
            from app.tasks.locks import acquire_lock, make_lock_value
            from app.tasks.queue import get_queue

            redis = await get_queue()
        except Exception:  # noqa: BLE001
            redis = None

        if redis is not None:
            ingest_lock_key = f"lock:ingest:{tenant_id}:{dataset.id}:{file_sha256}:{pipeline_hash}"
            ingest_lock_value = make_lock_value(account_id)
            lock_ttl = 60 * 40
            acquired = await acquire_lock(
                redis,
                key=ingest_lock_key,
                value=ingest_lock_value,
                ttl_sec=lock_ttl,
            )
            if not acquired:
                with contextlib.suppress(OSError):
                    file_path.unlink(missing_ok=True)
                raise HTTPException(status_code=409, detail="Duplicate ingest in progress")

            doc_metadata["ingest_lock_key"] = ingest_lock_key
            doc_metadata["ingest_lock_value"] = ingest_lock_value

    ingestion_run = None
    try:
        ingestion_run = documents_module.IngestionRunService.create_run(
            db,
            tenant_id=tenant_id,
            dataset_id=getattr(dataset, "id", None),
            requested_by=account_id,
            kind="upload",
            config={
                "filename": str(file.filename or "")[:255],
                "source_path": (str(source_path)[:1000] if source_path else None),
                "file_ext": str(file_ext or "")[:16],
                "parser_backend_requested": str(parser_backend or "")[:80],
                "chunk_strategy_requested": str(chunk_strategy or "")[:80],
                "parser_backend": str(resolved_parser_backend or "")[:80],
                "chunk_strategy": str(resolved_chunk_strategy or "")[:80],
                "pipeline_hash": str(pipeline_hash or "")[:64],
                "ingestion_meta": dict(ingestion_meta or {}),
                "pipeline": (
                    pipeline_parsed.model_dump(exclude_none=True) if pipeline_parsed is not None else None
                ),
            },
            expected_documents=1,
        )
    except Exception:
        ingestion_run = None

    def _attach_doc_to_ingestion_run(doc: documents_module.DBDocument, *, created: bool) -> None:
        if ingestion_run is None or doc is None:
            return
        try:
            meta0 = dict(getattr(doc, "doc_metadata", None) or {})
            if created and not meta0.get("created_by_run_id"):
                meta0["created_by_run_id"] = str(ingestion_run.id)
            meta0["last_ingestion_run_id"] = str(ingestion_run.id)
            meta0["last_ingestion_kind"] = "upload"
            doc.doc_metadata = meta0
            db.commit()
            db.refresh(doc)
        except Exception:
            meta0 = dict(getattr(doc, "doc_metadata", None) or {})

        try:
            documents_module.IngestionRunService.add_document(
                db,
                tenant_id=tenant_id,
                run_id=ingestion_run.id,
                document_id=doc.id,
                source_ref=(source_path or doc.filename),
                initial_status=str(getattr(doc, "status", "") or "created"),
                doc_meta=meta0 if isinstance(meta0, dict) else None,
            )
        except Exception:
            return

    if bool(getattr(settings, "UPLOAD_DEDUP_ENABLED", False)) and isinstance(file_sha256, str) and file_sha256:
        dup = documents_module._find_duplicate_document(
            db,
            tenant_id=tenant_id,
            dataset_id=getattr(dataset, "id", None),
            file_sha256=file_sha256,
            pipeline_hash=pipeline_hash,
        )
        if dup is not None and str(getattr(dup, "status", "") or "").lower() not in {"failed"}:
            documents_module.logger.info(
                "Upload dedup hit tenant_id=%s dataset_id=%s document_id=%s",
                str(tenant_id),
                str(getattr(dataset, "id", None)),
                str(getattr(dup, "id", "")),
            )
            with contextlib.suppress(OSError):
                file_path.unlink(missing_ok=True)
            with contextlib.suppress(Exception):
                _attach_doc_to_ingestion_run(dup, created=False)
            return dup

        dup_any = documents_module._find_duplicate_document_by_sha(
            db,
            tenant_id=tenant_id,
            dataset_id=getattr(dataset, "id", None),
            file_sha256=file_sha256,
        )
        if dup_any is not None:
            status0 = str(getattr(dup_any, "status", "") or "").lower()
            if status0 in {"pending", "processing"}:
                raise HTTPException(status_code=409, detail=documents_module.DUPLICATE_DOCUMENT_PROCESSING_DETAIL)

            with contextlib.suppress(OSError):
                file_path.unlink(missing_ok=True)

            meta_any = dict(getattr(dup_any, "doc_metadata", None) or {})
            meta_any["parser_backend"] = resolved_parser_backend
            meta_any["parser_backend_requested"] = (parser_backend or "").lower()
            meta_any["chunk_strategy"] = resolved_chunk_strategy
            meta_any["chunk_strategy_requested"] = (chunk_strategy or "").lower()
            if source_path and not meta_any.get("source_path"):
                meta_any["source_path"] = source_path
            meta_any["file_sha256"] = str(file_sha256).strip().lower()
            documents_module.upsert_pipeline_metadata(meta_any, options=pipeline_options)
            if ingestion_meta:
                meta_any["ingestion"] = ingestion_meta

            if isinstance(user_metadata, str) and user_metadata.strip():
                raw = user_metadata.strip()
                max_len = int(getattr(settings, "USER_METADATA_FORM_JSON_MAX_CHARS", 20_000) or 20_000)
                if max_len > 0 and len(raw) > max_len:
                    raise HTTPException(status_code=400, detail="user_metadata is too large")
                try:
                    obj = json.loads(raw)
                except Exception as exc:  # noqa: BLE001
                    raise HTTPException(status_code=400, detail="Invalid user_metadata JSON (expect UTF-8)") from exc
                if not isinstance(obj, dict):
                    raise HTTPException(status_code=400, detail="user_metadata must be a JSON object")
                current_user = meta_any.get("user") if isinstance(meta_any.get("user"), dict) else {}
                meta_any["user"] = documents_module._apply_user_metadata_patch(
                    current=current_user,
                    patch=obj,
                    replace=False,
                )

            if "active_pipeline_hash" not in meta_any:
                meta_any["active_pipeline_hash"] = str(meta_any.get("pipeline_hash") or "").strip() or None
            if "active_pipeline_ready" not in meta_any:
                meta_any["active_pipeline_ready"] = bool(status0 == "completed")

            dup_any.doc_metadata = meta_any
            db.commit()
            db.refresh(dup_any)

            await documents_module.retry_document_processing(
                document_id=dup_any.id,
                background_tasks=background_tasks,
                force=True,
                skip_if_unchanged=True,
                tenant_id=tenant_id,
                account_id=account_id,
                db=db,
            )
            db.refresh(dup_any)
            with contextlib.suppress(Exception):
                _attach_doc_to_ingestion_run(dup_any, created=False)
            return dup_any

    db_document = documents_module.DBDocument(
        id=file_id,
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        filename=file.filename,
        file_type=file_ext.lstrip("."),
        file_size=file_size,
        file_path=str(file_path),
        owner_id=account_id,
        access_mode=None,
        status="pending",
        processing_progress=0,
        doc_metadata=doc_metadata,
    )

    db.add(db_document)
    db.commit()
    db.refresh(db_document)
    with contextlib.suppress(Exception):
        _attach_doc_to_ingestion_run(db_document, created=True)

    job_id = f"doc:{tenant_id}:{file_id}:{pipeline_hash}"
    task_id = await documents_module.enqueue_document_processing(
        tenant_id=tenant_id,
        document_id=file_id,
        requested_by=account_id,
        job_id=job_id,
    )
    if task_id:
        meta = dict(db_document.doc_metadata or {})
        meta["task_id"] = task_id
        db_document.doc_metadata = meta
        db.commit()
        db.refresh(db_document)
    else:
        background_tasks.add_task(
            documents_module.run_document_processing_limited,
            file_path,
            file_id,
            tenant_id,
            resolved_parser_backend,
            resolved_chunk_strategy,
        )

    return db_document


@router.post("/upload-url", response_model=DocumentDetail, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def upload_document_from_url(
    background_tasks: BackgroundTasks,
    body: UrlUploadRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Fetch a remote URL and ingest it as a document.

    Notes:
    - Disabled by default: set URL_INGEST_ENABLED=true to enable.
    - SSRF guard: blocks private/loopback/link-local hosts by default.
    """
    from app.api.v1 import documents as documents_module  # Local import to avoid router circular import.

    return await documents_module._ingest_url_upload_request(
        background_tasks=background_tasks,
        body=body,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        ingestion_kind="upload_url",
    )


@router.post("/upload-batch", response_model=DocumentBatchUploadResponse, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def upload_documents_batch(
    background_tasks: BackgroundTasks,
    files: Annotated[list[UploadFile], File(...)],
    form: Annotated[UploadDocumentsBatchFormFields, Depends()],
    overrides_form: Annotated[PipelineOverridesFormFields, Depends()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    from app.api.v1 import documents as documents_module  # Local import to avoid router circular import.

    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    if len(files) > 50:
        raise HTTPException(status_code=400, detail="Too many files. Maximum 50 files per batch.")

    from app.services.tenant_quota_service import enforce_tenant_upload_quotas

    enforce_tenant_upload_quotas(
        db,
        tenant_id=tenant_id,
        additional_docs=int(len(files or [])),
        additional_bytes=0,
    )

    parser_backend = form.parser_backend
    chunk_strategy = form.chunk_strategy
    pipeline = form.pipeline
    dataset_id = form.dataset_id
    precheck_first = form.precheck_first
    precheck_only = form.precheck_only
    upload_only = form.upload_only
    user_metadata_map = form.user_metadata_map

    pipeline_overrides = documents_module.PipelineOptionOverrides(**asdict(overrides_form))
    max_concurrent = min(int(form.max_concurrent or 0), 10)
    semaphore = asyncio.Semaphore(max_concurrent)

    pipeline_parsed = documents_module._parse_pipeline_json(pipeline)

    user_meta_by_key: dict[str, dict] = {}
    if isinstance(user_metadata_map, str) and user_metadata_map.strip():
        raw = user_metadata_map.strip()
        max_len = int(getattr(settings, "USER_METADATA_MAP_FORM_JSON_MAX_CHARS", 200_000) or 200_000)
        if max_len > 0 and len(raw) > max_len:
            raise HTTPException(status_code=400, detail="user_metadata_map is too large")
        try:
            obj = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="Invalid user_metadata_map JSON (expect UTF-8)") from exc
        if not isinstance(obj, dict):
            raise HTTPException(status_code=400, detail="user_metadata_map must be a JSON object")
        for key, value in obj.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            normalized = documents_module._normalize_upload_key(key)
            if normalized:
                user_meta_by_key[normalized] = value

    dataset = documents_module._resolve_writable_dataset(db, tenant_id, account_id, dataset_id)
    dataset_meta = (getattr(dataset, "dataset_metadata", None) or {}) if dataset is not None else {}
    policy = documents_module.parse_ingestion_policy_from_metadata(
        dataset_meta if isinstance(dataset_meta, dict) else {}
    )  # type: ignore[arg-type]

    ingestion_run = None
    if not precheck_only and not upload_only:
        try:
            ingestion_run = documents_module.IngestionRunService.create_run(
                db,
                tenant_id=tenant_id,
                dataset_id=getattr(dataset, "id", None),
                requested_by=account_id,
                kind="upload_batch",
                config={
                    "files": int(len(files or [])),
                    "parser_backend_requested": str(parser_backend or "")[:80],
                    "chunk_strategy_requested": str(chunk_strategy or "")[:80],
                    "pipeline": (pipeline_parsed.model_dump(exclude_none=True) if pipeline_parsed is not None else None),
                },
                expected_documents=int(len(files or [])),
            )
        except Exception:
            ingestion_run = None

    dataset_default_pb = None
    dataset_default_cs = None
    if isinstance(dataset_meta, dict):
        raw_pb = dataset_meta.get("default_parser_backend")
        raw_cs = dataset_meta.get("default_chunk_strategy")
        if isinstance(raw_pb, str) and raw_pb.strip():
            dataset_default_pb = raw_pb.strip().lower()
        if isinstance(raw_cs, str) and raw_cs.strip():
            dataset_default_cs = raw_cs.strip().lower()

    global_default_pb = (
        str(getattr(settings, "DEFAULT_PARSER_BACKEND", "auto") or "auto").strip().lower() or "auto"
    )
    global_default_cs = (
        str(getattr(settings, "DEFAULT_CHUNK_STRATEGY", "langchain_recursive") or "langchain_recursive")
        .strip()
        .lower()
        or "langchain_recursive"
    )
    default_pb = dataset_default_pb or global_default_pb
    default_cs = dataset_default_cs or global_default_cs

    parser_backend_base = parser_backend
    chunk_strategy_base = chunk_strategy
    req_pb = (parser_backend or "").strip().lower()
    if dataset_default_pb and req_pb in {"", "auto", global_default_pb}:
        parser_backend_base = dataset_default_pb
    req_cs = (chunk_strategy or "").strip().lower()
    if dataset_default_cs and req_cs in {"", global_default_cs}:
        chunk_strategy_base = dataset_default_cs

    if precheck_first or precheck_only:
        if dataset is None:
            raise HTTPException(status_code=400, detail="dataset_id is required for precheck")

        async def _save_upload_only(file: UploadFile) -> dict:
            async with semaphore:
                source_path: str | None = None
                upload_key: str | None = None
                try:
                    raw_filename = file.filename
                    upload_key = documents_module._normalize_upload_key(raw_filename)
                    source_path = upload_key if "/" in upload_key else None
                    file.filename = documents_module._sanitize_filename(raw_filename)

                    file_ext = Path(file.filename).suffix.lower()
                    if file_ext not in settings.allowed_extensions_list:
                        return {
                            "success": False,
                            "filename": file.filename,
                            "source_path": source_path,
                            "error": f"Unsupported file type: {file_ext}",
                        }

                    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
                    upload_dir.mkdir(parents=True, exist_ok=True)

                    file_id = uuid.uuid4()
                    file_path = upload_dir / f"{file_id}{file_ext}"
                    file_size, file_sha256 = await documents_module.save_upload_file_with_hash(
                        file,
                        file_path,
                        max_bytes=settings.MAX_FILE_SIZE,
                    )

                    return {
                        "success": True,
                        "filename": file.filename,
                        "source_path": source_path,
                        "upload_key": upload_key,
                        "file_ext": file_ext,
                        "file_id": file_id,
                        "file_path": str(file_path),
                        "file_size": int(file_size or 0),
                        "file_sha256": str(file_sha256 or "").strip().lower() or None,
                    }
                except HTTPException as exc:
                    return {
                        "success": False,
                        "filename": str(getattr(file, "filename", "") or "unknown"),
                        "source_path": source_path,
                        "error": str(getattr(exc, "detail", "") or str(exc) or "upload_failed"),
                    }
                except Exception as exc:  # noqa: BLE001
                    return {
                        "success": False,
                        "filename": str(getattr(file, "filename", "") or "unknown"),
                        "source_path": source_path,
                        "error": str(exc)[:200],
                    }

        save_tasks = [_save_upload_only(file) for file in files]
        save_results = await asyncio.gather(*save_tasks, return_exceptions=True)

        staged_results: list[dict[str, Any]] = []
        for result in save_results:
            if isinstance(result, Exception):
                staged_results.append({"success": False, "filename": "unknown", "source_path": None, "error": str(result)[:200]})
            elif isinstance(result, dict):
                staged_results.append(result)
            else:
                staged_results.append({"success": False, "filename": "unknown", "source_path": None, "error": "upload_failed"})

        staged_successful = [result for result in staged_results if result.get("success")]
        staged_failed = [result for result in staged_results if not result.get("success")]

        try:
            total_bytes = sum(int(result.get("file_size") or 0) for result in staged_successful)
            enforce_tenant_upload_quotas(
                db,
                tenant_id=tenant_id,
                additional_docs=int(len(staged_successful)),
                additional_bytes=int(total_bytes),
            )
        except HTTPException:
            for result in staged_successful:
                with contextlib.suppress(OSError):
                    Path(str(result.get("file_path") or "")).unlink(missing_ok=True)
            raise

        scan_run = None
        if staged_successful:
            staging_root: Path | None = None
            try:
                upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
                staging_root = (upload_dir / ".tmp" / "precheck_ingest" / uuid.uuid4().hex).resolve(strict=False)
                staging_root.mkdir(parents=True, exist_ok=True)
                staging_root_resolved = staging_root.resolve(strict=False)

                def _safe_staging_relpath(item: dict, *, idx: int) -> Path:
                    raw = str(item.get("upload_key") or item.get("filename") or f"FILE_{idx:06d}").strip()
                    parts = documents_module._normalize_upload_path_parts(raw)
                    if not parts:
                        parts = [str(item.get("filename") or f"FILE_{idx:06d}")]

                    safe_parts: list[str] = []
                    for seg in parts:
                        seg0 = str(seg or "").replace("\\", "/").strip()
                        seg0 = seg0.rsplit("/", 1)[-1]
                        seg0 = "".join(ch for ch in seg0 if ord(ch) >= 32 and ch != "\x7f")
                        if not seg0 or seg0 in {".", ".."}:
                            seg0 = "item"
                        if len(seg0) > 120:
                            seg0 = seg0[:120]
                        safe_parts.append(seg0)

                    file_ext0 = str(item.get("file_ext") or "").strip().lower()
                    if safe_parts:
                        last = safe_parts[-1]
                        if file_ext0 and not last.lower().endswith(file_ext0):
                            safe_parts[-1] = f"{last}{file_ext0}"

                    rel = Path(*safe_parts) if safe_parts else Path(f"FILE_{idx:06d}{file_ext0}")
                    rel = Path(*[p for p in rel.parts if p not in {"", ".."}])
                    return rel

                linked_any = False
                for idx, item in enumerate(staged_successful):
                    src_raw = str(item.get("file_path") or "").strip()
                    if not src_raw:
                        continue
                    src = Path(src_raw).resolve(strict=False)
                    if not src.exists() or not src.is_file():
                        continue

                    rel = _safe_staging_relpath(item, idx=idx)
                    dst = (staging_root / rel).resolve(strict=False)
                    try:
                        dst.relative_to(staging_root_resolved)
                    except Exception:
                        ext0 = str(item.get("file_ext") or "").strip().lower()
                        dst = (staging_root / f"FILE_{idx:06d}{ext0}").resolve(strict=False)

                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if dst.exists():
                        fid = item.get("file_id")
                        suffix = getattr(fid, "hex", None) if fid is not None else uuid.uuid4().hex
                        dst = dst.with_name(f"{dst.stem}.{suffix}{dst.suffix}")
                    try:
                        documents_module.os.link(src, dst)
                        linked_any = True
                    except Exception:
                        try:
                            documents_module.shutil.copy2(src, dst)
                            linked_any = True
                        except Exception:
                            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                            continue

                if linked_any:
                    scan_run = documents_module.DBDatasetPrecheckScanRun(
                        tenant_id=tenant_id,
                        dataset_id=dataset.id,
                        requested_by=account_id,
                        kind="path",
                        status="pending",
                        progress=0,
                        config={
                            "root_path": str(staging_root),
                            "max_files": int(len(staged_successful)),
                            "enable_pdf_quality": True,
                            "enable_text_extract": True,
                            "enable_pii": False,
                            "enable_secrets": False,
                            "compute_file_hash": False,
                            "redact_paths": False,
                            "enable_sampling": True,
                            "sample_size": None,
                            "enable_near_dup": False,
                            "internal_allow_upload_scan": True,
                        },
                        summary={},
                        artifacts={},
                    )
                    db.add(scan_run)
                    db.commit()
                    db.refresh(scan_run)

                    tid0 = tenant_id
                    dsid0 = dataset.id
                    rid0 = scan_run.id

                    def _run_scan_job() -> None:
                        db2 = documents_module.SessionLocal()
                        try:
                            documents_module.run_dataset_precheck_scan(db2, tenant_id=tid0, dataset_id=dsid0, scan_run_id=rid0)
                        except Exception as exc:  # noqa: BLE001
                            try:
                                row = (
                                    db2.query(documents_module.DBDatasetPrecheckScanRun)
                                    .filter(
                                        documents_module.DBDatasetPrecheckScanRun.id == rid0,
                                        documents_module.DBDatasetPrecheckScanRun.tenant_id == tid0,
                                        documents_module.DBDatasetPrecheckScanRun.dataset_id == dsid0,
                                    )
                                    .first()
                                )
                                if row is not None:
                                    row.status = "failed"
                                    row.error_message = str(exc)[:200]
                                    row.finished_at = datetime.now(UTC)
                                    db2.commit()
                            except Exception as mark_exc:  # noqa: BLE001
                                documents_module.logger.warning(
                                    "Failed to mark precheck scan run as failed: %s",
                                    str(mark_exc)[:200],
                                )
                            raise
                        finally:
                            db2.close()

                    try:
                        await asyncio.to_thread(_run_scan_job)
                    except Exception as exc:  # noqa: BLE001
                        documents_module.logger.warning("Precheck-first scan failed: %s", str(exc)[:200])
                    finally:
                        with contextlib.suppress(Exception):
                            documents_module.shutil.rmtree(staging_root)

                    with contextlib.suppress(Exception):
                        db.refresh(scan_run)

                    if not precheck_only:
                        try:
                            documents_module.apply_ingestion_policy_suggestion(
                                db,
                                dataset=dataset,
                                scan_run=scan_run,
                                tenant_id=tenant_id,
                                replace=False,
                            )
                        except HTTPException as exc:
                            if int(getattr(exc, "status_code", 0) or 0) != 409:
                                documents_module.logger.warning(
                                    "Precheck-first policy apply failed: %s",
                                    str(getattr(exc, "detail", exc))[:200],
                                )
                        except Exception as exc:  # noqa: BLE001
                            documents_module.logger.warning("Precheck-first policy apply failed: %s", str(exc)[:200])

                        with contextlib.suppress(Exception):
                            db.refresh(dataset)
                        dataset_meta2 = (getattr(dataset, "dataset_metadata", None) or {}) if dataset is not None else {}
                        policy = documents_module.parse_ingestion_policy_from_metadata(
                            dataset_meta2 if isinstance(dataset_meta2, dict) else {}
                        )  # type: ignore[arg-type]
            except Exception as exc:  # noqa: BLE001
                documents_module.logger.warning(
                    "Precheck-first ingest failed; continuing without precheck: %s",
                    str(exc)[:200],
                )
            finally:
                if staging_root is not None:
                    with contextlib.suppress(Exception):
                        documents_module.shutil.rmtree(staging_root)

        if precheck_only:
            # Precheck-only upload returns scan evidence without creating DBDocument rows
            # or enqueueing the parser/chunker pipeline.
            for result in staged_successful:
                with contextlib.suppress(OSError):
                    Path(str(result.get("file_path") or "")).unlink(missing_ok=True)

            return {
                "total": len(files),
                "successful_count": len(staged_successful),
                "failed_count": len(staged_failed),
                "successful": [],
                "failed": [
                    {
                        "filename": result.get("filename") or "unknown",
                        "source_path": result.get("source_path"),
                        "error": result.get("error") or "upload_failed",
                    }
                    for result in staged_failed
                ],
                "precheck_scan_run_id": str(scan_run.id) if scan_run is not None else None,
            }

        governance_profile_cache: dict[str, Any] = {}

        async def _finalize_staged_file(staged: dict) -> dict:
            async with semaphore:
                source_path = staged.get("source_path")
                upload_key = staged.get("upload_key")
                filename0 = str(staged.get("filename") or "unknown")
                try:
                    file_ext = str(staged.get("file_ext") or "").strip().lower() or Path(filename0).suffix.lower()
                    file_id = staged.get("file_id")
                    file_path = Path(str(staged.get("file_path") or ""))
                    file_size = int(staged.get("file_size") or 0)
                    file_sha256 = staged.get("file_sha256")

                    if not file_ext:
                        raise HTTPException(status_code=400, detail="Missing file extension")
                    if file_ext not in settings.allowed_extensions_list:
                        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_ext}")

                    pipeline_options = documents_module._to_pipeline_options(
                        pipeline=pipeline_parsed,
                        overrides=pipeline_overrides,
                    )

                    matched_rule = documents_module.match_ingestion_rule(
                        policy,
                        filename=str(upload_key or filename0),
                        file_ext=file_ext,
                    )
                    ingestion_meta: dict[str, Any] | None = None
                    parser_backend_choice: str = parser_backend_base
                    chunk_strategy_choice: str = chunk_strategy_base
                    preprocess_steps: list[dict] = []
                    policy_patch = documents_module.PipelineOptions()

                    if matched_rule is not None:
                        req_pb0 = (parser_backend_choice or "").strip().lower()
                        if req_pb0 in {"", "auto", default_pb} and matched_rule.parser_backend:
                            parser_backend_choice = str(matched_rule.parser_backend)

                        req_cs0 = (chunk_strategy_choice or "").strip().lower()
                        if req_cs0 in {"", default_cs} and matched_rule.chunk_strategy:
                            chunk_strategy_choice = str(matched_rule.chunk_strategy)

                        pp = getattr(matched_rule, "preprocess", None)
                        steps = getattr(pp, "steps", None) if pp is not None and bool(getattr(pp, "enabled", True)) else None
                        if isinstance(steps, list) and steps:
                            preprocess_steps = [
                                {
                                    "id": str(getattr(s, "id", "") or "").strip(),
                                    "params": dict(getattr(s, "params", {}) or {}),
                                }
                                for s in steps
                            ]

                        patch_dict: dict[str, Any] = {}
                        profile_ref = getattr(matched_rule, "governance_profile_ref", None)
                        if isinstance(profile_ref, str) and profile_ref.strip():
                            ref = profile_ref.strip()
                            cached = governance_profile_cache.get(ref)
                            if cached is None:
                                try:
                                    cached = documents_module.resolve_governance_profile_ref(
                                        db=db,
                                        tenant_id=tenant_id,
                                        profile_ref=ref,
                                    )
                                except ValueError as exc:
                                    raise HTTPException(status_code=400, detail=f"Invalid governance_profile_ref: {str(exc)[:120]}") from exc
                                governance_profile_cache[ref] = cached
                            patch_dict.update(dict(getattr(cached, "pipeline_patch", None) or {}))
                            rules = getattr(cached, "regex_rules", None) or []
                            if rules:
                                patch_dict["governance_regex_rules"] = list(rules)

                        patch_dict.update(dict(getattr(matched_rule, "pipeline_patch", None) or {}))
                        if patch_dict:
                            policy_patch = documents_module.PipelineOptions(**patch_dict)

                        ingestion_meta = {
                            "version": str(getattr(policy, "version", "1") if policy is not None else "1"),
                            "rule": {"id": matched_rule.id, "name": matched_rule.name},
                            "preprocess": {"enabled": bool(preprocess_steps), "steps": preprocess_steps},
                            "governance_profile_ref": (
                                profile_ref.strip() if isinstance(profile_ref, str) and profile_ref.strip() else None
                            ),
                        }

                    pipeline_options = documents_module.merge_pipeline_options(policy_patch, pipeline_options)

                    requested_parser_backend = (parser_backend_choice or "").strip().lower()
                    if file_ext == ".pdf" and requested_parser_backend in {"", "auto"}:
                        resolved_parser_backend = "auto"
                    else:
                        resolved_parser_backend = documents_module.parser_factory.resolve_backend(
                            file_ext,
                            parser_backend_choice,
                        )
                    resolved_chunk_strategy = documents_module.chunker_factory.resolve_strategy(chunk_strategy_choice)

                    pipeline_effective = documents_module.resolve_pipeline_effective(
                        dataset_metadata=(getattr(dataset, "dataset_metadata", None) or {}) if dataset else {},
                        document_metadata={},
                        request_overrides=pipeline_options,
                    )
                    if resolved_chunk_strategy not in documents_module.chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
                        documents_module._validate_chunk_params(
                            pipeline_effective.chunk_size,
                            pipeline_effective.chunk_overlap,
                        )

                    doc_metadata = {
                        "parser_backend": resolved_parser_backend,
                        "parser_backend_requested": (parser_backend or "").lower(),
                        "chunk_strategy": resolved_chunk_strategy,
                        "chunk_strategy_requested": (chunk_strategy or "").lower(),
                    }
                    if source_path:
                        doc_metadata["source_path"] = source_path
                    if isinstance(file_sha256, str) and file_sha256:
                        doc_metadata["file_sha256"] = file_sha256
                    documents_module.upsert_pipeline_metadata(doc_metadata, options=pipeline_options)
                    if ingestion_meta:
                        doc_metadata["ingestion"] = ingestion_meta

                    user_patch = None
                    if isinstance(upload_key, str) and upload_key:
                        user_patch = user_meta_by_key.get(upload_key)
                        if user_patch is None and "/" in upload_key:
                            user_patch = user_meta_by_key.get(upload_key.rsplit("/", 1)[-1])
                    if user_patch is None:
                        user_patch = user_meta_by_key.get(filename0)
                    if isinstance(user_patch, dict) and user_patch:
                        doc_metadata["user"] = documents_module._apply_user_metadata_patch(
                            current={},
                            patch=user_patch,
                            replace=True,
                        )
                    if upload_only:
                        doc_metadata["ingest_stage"] = "uploaded_only"
                    pipeline_hash = documents_module._compute_pipeline_hash(doc_metadata)
                    doc_metadata["pipeline_hash"] = pipeline_hash
                    doc_metadata.setdefault("active_pipeline_hash", pipeline_hash)
                    doc_metadata.setdefault("active_pipeline_ready", False)

                    if bool(getattr(settings, "UPLOAD_DEDUP_ENABLED", False)) and isinstance(file_sha256, str) and file_sha256:
                        dup = documents_module._find_duplicate_document(
                            db,
                            tenant_id=tenant_id,
                            dataset_id=getattr(dataset, "id", None) if dataset is not None else None,
                            file_sha256=file_sha256,
                            pipeline_hash=pipeline_hash,
                        )
                        if dup is not None and str(getattr(dup, "status", "") or "").lower() not in {"failed"}:
                            with contextlib.suppress(OSError):
                                file_path.unlink(missing_ok=True)
                            return {
                                "success": True,
                                "filename": filename0,
                                "source_path": source_path,
                                "document_id": str(getattr(dup, "id", "")),
                                "document": dup,
                            }

                        dup_any = documents_module._find_duplicate_document_by_sha(
                            db,
                            tenant_id=tenant_id,
                            dataset_id=getattr(dataset, "id", None) if dataset is not None else None,
                            file_sha256=file_sha256,
                        )
                        if dup_any is not None:
                            status0 = str(getattr(dup_any, "status", "") or "").lower()
                            if status0 in {"pending", "processing"}:
                                raise HTTPException(status_code=409, detail=documents_module.DUPLICATE_DOCUMENT_PROCESSING_DETAIL)

                            with contextlib.suppress(OSError):
                                file_path.unlink(missing_ok=True)

                            meta_any = dict(getattr(dup_any, "doc_metadata", None) or {})
                            meta_any["parser_backend"] = resolved_parser_backend
                            meta_any["parser_backend_requested"] = (parser_backend or "").lower()
                            meta_any["chunk_strategy"] = resolved_chunk_strategy
                            meta_any["chunk_strategy_requested"] = (chunk_strategy or "").lower()
                            if source_path and not meta_any.get("source_path"):
                                meta_any["source_path"] = source_path
                            meta_any["file_sha256"] = str(file_sha256).strip().lower()
                            documents_module.upsert_pipeline_metadata(meta_any, options=pipeline_options)
                            if ingestion_meta:
                                meta_any["ingestion"] = ingestion_meta

                            if isinstance(user_patch, dict) and user_patch:
                                current_user = meta_any.get("user") if isinstance(meta_any.get("user"), dict) else {}
                                meta_any["user"] = documents_module._apply_user_metadata_patch(
                                    current=current_user,
                                    patch=user_patch,
                                    replace=False,
                                )

                            if "active_pipeline_hash" not in meta_any:
                                meta_any["active_pipeline_hash"] = (
                                    str(meta_any.get("pipeline_hash") or "").strip() or None
                                )
                            if "active_pipeline_ready" not in meta_any:
                                meta_any["active_pipeline_ready"] = bool(status0 == "completed")

                            dup_any.doc_metadata = meta_any
                            db.commit()
                            db.refresh(dup_any)

                            if upload_only:
                                return {
                                    "success": True,
                                    "filename": filename0,
                                    "source_path": source_path,
                                    "document_id": str(getattr(dup_any, "id", "")),
                                    "document": dup_any,
                                }

                            await documents_module.retry_document_processing(
                                document_id=dup_any.id,
                                background_tasks=background_tasks,
                                force=True,
                                skip_if_unchanged=True,
                                tenant_id=tenant_id,
                                account_id=account_id,
                                db=db,
                            )
                            db.refresh(dup_any)
                            return {
                                "success": True,
                                "filename": filename0,
                                "source_path": source_path,
                                "document_id": str(getattr(dup_any, "id", "")),
                                "document": dup_any,
                            }

                    db_document = documents_module.DBDocument(
                        id=file_id,
                        tenant_id=tenant_id,
                        dataset_id=dataset.id if dataset else None,
                        filename=filename0,
                        file_type=file_ext.lstrip("."),
                        file_size=file_size,
                        file_path=str(file_path),
                        owner_id=account_id,
                        access_mode=None,
                        status="pending",
                        processing_progress=0,
                        doc_metadata=doc_metadata,
                    )

                    db.add(db_document)
                    db.commit()
                    db.refresh(db_document)

                    if upload_only:
                        # Upload-only stores the source document but intentionally does not enqueue parsing.
                        return {
                            "success": True,
                            "filename": filename0,
                            "source_path": source_path,
                            "document_id": str(file_id),
                            "document": db_document,
                        }

                    job_id = f"doc:{tenant_id}:{file_id}:{pipeline_hash}"
                    task_id = await documents_module.enqueue_document_processing(
                        tenant_id=tenant_id,
                        document_id=file_id,
                        requested_by=account_id,
                        job_id=job_id,
                    )
                    if task_id:
                        meta = dict(db_document.doc_metadata or {})
                        meta["task_id"] = task_id
                        db_document.doc_metadata = meta
                        db.commit()
                        db.refresh(db_document)
                    else:
                        background_tasks.add_task(
                            documents_module.run_document_processing_limited,
                            file_path,
                            file_id,
                            tenant_id,
                            resolved_parser_backend,
                            resolved_chunk_strategy,
                        )

                    return {
                        "success": True,
                        "filename": filename0,
                        "source_path": source_path,
                        "document_id": str(file_id),
                        "document": db_document,
                    }
                except Exception as exc:  # noqa: BLE001
                    documents_module.logger.error("Error processing staged file %s: %s", filename0, str(exc)[:200])
                    return {
                        "success": False,
                        "filename": filename0,
                        "source_path": source_path,
                        "error": str(exc)[:200],
                    }

        finalize_tasks = [_finalize_staged_file(item) for item in staged_successful]
        finalize_results = await asyncio.gather(*finalize_tasks, return_exceptions=True)

        processed: list[dict[str, Any]] = []
        for result in finalize_results:
            if isinstance(result, Exception):
                processed.append({"success": False, "filename": "unknown", "source_path": None, "error": str(result)[:200]})
            elif isinstance(result, dict):
                processed.append(result)
            else:
                processed.append({"success": False, "filename": "unknown", "source_path": None, "error": "upload_failed"})

        successful = [result for result in processed if result.get("success")]
        failed = staged_failed + [result for result in processed if not result.get("success")]

        if ingestion_run is not None:
            for result in successful:
                doc = result.get("document")
                if doc is None:
                    continue
                try:
                    meta0 = dict(getattr(doc, "doc_metadata", None) or {})
                    meta0["last_ingestion_run_id"] = str(ingestion_run.id)
                    meta0["last_ingestion_kind"] = "upload_batch"
                    doc.doc_metadata = meta0
                    db.commit()
                    db.refresh(doc)
                except Exception:
                    meta0 = dict(getattr(doc, "doc_metadata", None) or {})

                with contextlib.suppress(Exception):
                    documents_module.IngestionRunService.add_document(
                        db,
                        tenant_id=tenant_id,
                        run_id=ingestion_run.id,
                        document_id=doc.id,
                        source_ref=(result.get("source_path") or getattr(doc, "filename", None)),
                        initial_status=str(getattr(doc, "status", "") or "created"),
                        doc_meta=meta0 if isinstance(meta0, dict) else None,
                    )

        return {
            "total": len(files),
            "successful_count": len(successful),
            "failed_count": len(failed),
            "successful": [
                {
                    "document_id": result["document_id"],
                    "filename": result["filename"],
                    "source_path": result.get("source_path"),
                    "status": result["document"].status,
                }
                for result in successful
            ],
            "failed": [
                {
                    "filename": result.get("filename") or "unknown",
                    "source_path": result.get("source_path"),
                    "error": result.get("error") or "upload_failed",
                }
                for result in failed
            ],
        }

    governance_profile_cache: dict[str, Any] = {}

    async def process_single_file(file: UploadFile) -> dict:
        async with semaphore:
            source_path: str | None = None
            upload_key: str | None = None
            try:
                raw_filename = file.filename
                upload_key = documents_module._normalize_upload_key(raw_filename)
                source_path = upload_key if "/" in upload_key else None
                file.filename = documents_module._sanitize_filename(raw_filename)

                file_ext = Path(file.filename).suffix.lower()
                if file_ext not in settings.allowed_extensions_list:
                    return {
                        "success": False,
                        "filename": file.filename,
                        "source_path": source_path,
                        "error": f"Unsupported file type: {file_ext}",
                    }

                pipeline_options = documents_module._to_pipeline_options(
                    pipeline=pipeline_parsed,
                    overrides=pipeline_overrides,
                )

                matched_rule = documents_module.match_ingestion_rule(
                    policy,
                    filename=upload_key or file.filename,
                    file_ext=file_ext,
                )
                ingestion_meta: dict[str, Any] | None = None
                parser_backend_choice: str = parser_backend_base
                chunk_strategy_choice: str = chunk_strategy_base
                preprocess_steps: list[dict] = []
                policy_patch = documents_module.PipelineOptions()

                if matched_rule is not None:
                    req_pb = (parser_backend_choice or "").strip().lower()
                    if req_pb in {"", "auto", default_pb} and matched_rule.parser_backend:
                        parser_backend_choice = str(matched_rule.parser_backend)

                    req_cs = (chunk_strategy_choice or "").strip().lower()
                    if req_cs in {"", default_cs} and matched_rule.chunk_strategy:
                        chunk_strategy_choice = str(matched_rule.chunk_strategy)

                    pp = getattr(matched_rule, "preprocess", None)
                    steps = getattr(pp, "steps", None) if pp is not None and bool(getattr(pp, "enabled", True)) else None
                    if isinstance(steps, list) and steps:
                        preprocess_steps = [
                            {
                                "id": str(getattr(s, "id", "") or "").strip(),
                                "params": dict(getattr(s, "params", {}) or {}),
                            }
                            for s in steps
                        ]

                    patch_dict: dict[str, Any] = {}
                    profile_ref = getattr(matched_rule, "governance_profile_ref", None)
                    if isinstance(profile_ref, str) and profile_ref.strip():
                        ref = profile_ref.strip()
                        cached = governance_profile_cache.get(ref)
                        if cached is None:
                            try:
                                cached = documents_module.resolve_governance_profile_ref(
                                    db=db,
                                    tenant_id=tenant_id,
                                    profile_ref=ref,
                                )
                            except ValueError as exc:
                                raise HTTPException(status_code=400, detail=f"Invalid governance_profile_ref: {str(exc)[:120]}") from exc
                            governance_profile_cache[ref] = cached
                        patch_dict.update(dict(getattr(cached, "pipeline_patch", None) or {}))
                        rules = getattr(cached, "regex_rules", None) or []
                        if rules:
                            patch_dict["governance_regex_rules"] = list(rules)

                    patch_dict.update(dict(getattr(matched_rule, "pipeline_patch", None) or {}))
                    if patch_dict:
                        policy_patch = documents_module.PipelineOptions(**patch_dict)

                    ingestion_meta = {
                        "version": str(getattr(policy, "version", "1") if policy is not None else "1"),
                        "rule": {"id": matched_rule.id, "name": matched_rule.name},
                        "preprocess": {"enabled": bool(preprocess_steps), "steps": preprocess_steps},
                        "governance_profile_ref": (
                            profile_ref.strip() if isinstance(profile_ref, str) and profile_ref.strip() else None
                        ),
                    }

                pipeline_options = documents_module.merge_pipeline_options(policy_patch, pipeline_options)

                requested_parser_backend = (parser_backend_choice or "").strip().lower()
                if file_ext == ".pdf" and requested_parser_backend in {"", "auto"}:
                    resolved_parser_backend = "auto"
                else:
                    resolved_parser_backend = documents_module.parser_factory.resolve_backend(
                        file_ext,
                        parser_backend_choice,
                    )
                resolved_chunk_strategy = documents_module.chunker_factory.resolve_strategy(chunk_strategy_choice)

                pipeline_effective = documents_module.resolve_pipeline_effective(
                    dataset_metadata=(getattr(dataset, "dataset_metadata", None) or {}) if dataset else {},
                    document_metadata={},
                    request_overrides=pipeline_options,
                )
                if resolved_chunk_strategy not in documents_module.chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
                    documents_module._validate_chunk_params(
                        pipeline_effective.chunk_size,
                        pipeline_effective.chunk_overlap,
                    )

                upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
                upload_dir.mkdir(parents=True, exist_ok=True)

                file_id = uuid.uuid4()
                file_path = upload_dir / f"{file_id}{file_ext}"

                file_size, file_sha256 = await documents_module.save_upload_file_with_hash(
                    file,
                    file_path,
                    max_bytes=settings.MAX_FILE_SIZE,
                )

                try:
                    enforce_tenant_upload_quotas(
                        db,
                        tenant_id=tenant_id,
                        additional_docs=1,
                        additional_bytes=int(file_size or 0),
                    )
                except HTTPException as exc:
                    with contextlib.suppress(OSError):
                        file_path.unlink(missing_ok=True)
                    return {
                        "success": False,
                        "filename": file.filename,
                        "source_path": source_path,
                        "error": str(getattr(exc, "detail", "") or "tenant_quota_exceeded"),
                    }

                doc_metadata = {
                    "parser_backend": resolved_parser_backend,
                    "parser_backend_requested": (parser_backend or "").lower(),
                    "chunk_strategy": resolved_chunk_strategy,
                    "chunk_strategy_requested": (chunk_strategy or "").lower(),
                }
                if source_path:
                    doc_metadata["source_path"] = source_path
                if isinstance(file_sha256, str) and file_sha256:
                    doc_metadata["file_sha256"] = file_sha256
                documents_module.upsert_pipeline_metadata(doc_metadata, options=pipeline_options)
                if ingestion_meta:
                    doc_metadata["ingestion"] = ingestion_meta

                user_patch = None
                if isinstance(upload_key, str) and upload_key:
                    user_patch = user_meta_by_key.get(upload_key)
                    if user_patch is None and "/" in upload_key:
                        user_patch = user_meta_by_key.get(upload_key.rsplit("/", 1)[-1])
                if user_patch is None:
                    user_patch = user_meta_by_key.get(file.filename)
                if isinstance(user_patch, dict) and user_patch:
                    doc_metadata["user"] = documents_module._apply_user_metadata_patch(
                        current={},
                        patch=user_patch,
                        replace=True,
                    )
                if upload_only:
                    doc_metadata["ingest_stage"] = "uploaded_only"
                pipeline_hash = documents_module._compute_pipeline_hash(doc_metadata)
                doc_metadata["pipeline_hash"] = pipeline_hash
                doc_metadata.setdefault("active_pipeline_hash", pipeline_hash)
                doc_metadata.setdefault("active_pipeline_ready", False)

                if bool(getattr(settings, "UPLOAD_DEDUP_ENABLED", False)) and isinstance(file_sha256, str) and file_sha256:
                    dup = documents_module._find_duplicate_document(
                        db,
                        tenant_id=tenant_id,
                        dataset_id=getattr(dataset, "id", None) if dataset is not None else None,
                        file_sha256=file_sha256,
                        pipeline_hash=pipeline_hash,
                    )
                    if dup is not None and str(getattr(dup, "status", "") or "").lower() not in {"failed"}:
                        with contextlib.suppress(OSError):
                            file_path.unlink(missing_ok=True)
                        return {
                            "success": True,
                            "filename": file.filename,
                            "source_path": source_path,
                            "document_id": str(getattr(dup, "id", "")),
                            "document": dup,
                        }

                    dup_any = documents_module._find_duplicate_document_by_sha(
                        db,
                        tenant_id=tenant_id,
                        dataset_id=getattr(dataset, "id", None) if dataset is not None else None,
                        file_sha256=file_sha256,
                    )
                    if dup_any is not None:
                        status0 = str(getattr(dup_any, "status", "") or "").lower()
                        if status0 in {"pending", "processing"}:
                            raise HTTPException(status_code=409, detail=documents_module.DUPLICATE_DOCUMENT_PROCESSING_DETAIL)

                        with contextlib.suppress(OSError):
                            file_path.unlink(missing_ok=True)

                        meta_any = dict(getattr(dup_any, "doc_metadata", None) or {})
                        meta_any["parser_backend"] = resolved_parser_backend
                        meta_any["parser_backend_requested"] = (parser_backend or "").lower()
                        meta_any["chunk_strategy"] = resolved_chunk_strategy
                        meta_any["chunk_strategy_requested"] = (chunk_strategy or "").lower()
                        if source_path and not meta_any.get("source_path"):
                            meta_any["source_path"] = source_path
                        meta_any["file_sha256"] = str(file_sha256).strip().lower()
                        documents_module.upsert_pipeline_metadata(meta_any, options=pipeline_options)
                        if ingestion_meta:
                            meta_any["ingestion"] = ingestion_meta

                        if isinstance(user_patch, dict) and user_patch:
                            current_user = meta_any.get("user") if isinstance(meta_any.get("user"), dict) else {}
                            meta_any["user"] = documents_module._apply_user_metadata_patch(
                                current=current_user,
                                patch=user_patch,
                                replace=False,
                            )

                        if "active_pipeline_hash" not in meta_any:
                            meta_any["active_pipeline_hash"] = (
                                str(meta_any.get("pipeline_hash") or "").strip() or None
                            )
                        if "active_pipeline_ready" not in meta_any:
                            meta_any["active_pipeline_ready"] = bool(status0 == "completed")

                        dup_any.doc_metadata = meta_any
                        db.commit()
                        db.refresh(dup_any)

                        if upload_only:
                            return {
                                "success": True,
                                "filename": file.filename,
                                "source_path": source_path,
                                "document_id": str(getattr(dup_any, "id", "")),
                                "document": dup_any,
                            }

                        await documents_module.retry_document_processing(
                            document_id=dup_any.id,
                            background_tasks=background_tasks,
                            force=True,
                            skip_if_unchanged=True,
                            tenant_id=tenant_id,
                            account_id=account_id,
                            db=db,
                        )
                        db.refresh(dup_any)
                        return {
                            "success": True,
                            "filename": file.filename,
                            "source_path": source_path,
                            "document_id": str(getattr(dup_any, "id", "")),
                            "document": dup_any,
                        }

                db_document = documents_module.DBDocument(
                    id=file_id,
                    tenant_id=tenant_id,
                    dataset_id=dataset.id if dataset else None,
                    filename=file.filename,
                    file_type=file_ext.lstrip("."),
                    file_size=file_size,
                    file_path=str(file_path),
                    owner_id=account_id,
                    access_mode=None,
                    status="pending",
                    processing_progress=0,
                    doc_metadata=doc_metadata,
                )

                db.add(db_document)
                db.commit()
                db.refresh(db_document)

                if upload_only:
                    # Upload-only stores the source document but intentionally does not enqueue parsing.
                    return {
                        "success": True,
                        "filename": file.filename,
                        "source_path": source_path,
                        "document_id": str(file_id),
                        "document": db_document,
                    }

                job_id = f"doc:{tenant_id}:{file_id}:{pipeline_hash}"
                task_id = await documents_module.enqueue_document_processing(
                    tenant_id=tenant_id,
                    document_id=file_id,
                    requested_by=account_id,
                    job_id=job_id,
                )
                if task_id:
                    meta = dict(db_document.doc_metadata or {})
                    meta["task_id"] = task_id
                    db_document.doc_metadata = meta
                    db.commit()
                    db.refresh(db_document)
                else:
                    background_tasks.add_task(
                        documents_module.run_document_processing_limited,
                        file_path,
                        file_id,
                        tenant_id,
                        resolved_parser_backend,
                        resolved_chunk_strategy,
                    )

                return {
                    "success": True,
                    "filename": file.filename,
                    "source_path": source_path,
                    "document_id": str(file_id),
                    "document": db_document,
                }
            except Exception as exc:  # noqa: BLE001
                documents_module.logger.error("Error processing file %s: %s", file.filename, str(exc))
                return {
                    "success": False,
                    "filename": file.filename,
                    "source_path": source_path,
                    "error": str(exc),
                }

    tasks = [process_single_file(file) for file in files]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    processed_results = []
    for result in results:
        if isinstance(result, Exception):
            processed_results.append(
                {
                    "success": False,
                    "filename": "unknown",
                    "source_path": None,
                    "error": str(result),
                }
            )
        else:
            processed_results.append(result)

    successful = [result for result in processed_results if result.get("success")]
    failed = [result for result in processed_results if not result.get("success")]

    if ingestion_run is not None:
        for result in successful:
            doc = result.get("document")
            if doc is None:
                continue
            try:
                meta0 = dict(getattr(doc, "doc_metadata", None) or {})
                meta0["last_ingestion_run_id"] = str(ingestion_run.id)
                meta0["last_ingestion_kind"] = "upload_batch"
                doc.doc_metadata = meta0
                db.commit()
                db.refresh(doc)
            except Exception:
                meta0 = dict(getattr(doc, "doc_metadata", None) or {})

            with contextlib.suppress(Exception):
                documents_module.IngestionRunService.add_document(
                    db,
                    tenant_id=tenant_id,
                    run_id=ingestion_run.id,
                    document_id=doc.id,
                    source_ref=(result.get("source_path") or getattr(doc, "filename", None)),
                    initial_status=str(getattr(doc, "status", "") or "created"),
                    doc_meta=meta0 if isinstance(meta0, dict) else None,
                )

    return {
        "total": len(files),
        "successful_count": len(successful),
        "failed_count": len(failed),
        "successful": [
            {
                "document_id": result["document_id"],
                "filename": result["filename"],
                "source_path": result.get("source_path"),
                "status": result["document"].status,
            }
            for result in successful
        ],
        "failed": [
            {
                "filename": result["filename"],
                "source_path": result.get("source_path"),
                "error": result.get("error", "Unknown error"),
            }
            for result in failed
        ],
    }
