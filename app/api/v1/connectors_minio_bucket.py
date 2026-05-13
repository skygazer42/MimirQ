from __future__ import annotations

import contextlib
import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from app.models.connector import ConnectorRun, ConnectorRunDocument


def _resolve_connectors_attr(name: str):  # noqa: ANN202
    leader_module = globals().get("_leader_module")
    if leader_module is not None and hasattr(leader_module, name):
        return getattr(leader_module, name)

    preferred_modules = (
        "test_saved_state_connectors",
        "test_support_connectors_module",
        "app.api.v1.connectors",
    )
    for module_name in preferred_modules:
        for key, module in sys.modules.items():
            if key == module_name or key.startswith(f"{module_name}_"):
                if module is not None and hasattr(module, name):
                    return getattr(module, name)

    for module in reversed(tuple(sys.modules.values())):
        path = str(getattr(module, "__file__", "") or "")
        if not path.endswith("/app/api/v1/connectors.py"):
            continue
        if hasattr(module, name):
            return getattr(module, name)

    raise RuntimeError(f"connectors attribute not available: {name}")


def _resolve_connectors_helper(name: str):  # noqa: ANN202
    helper = _resolve_connectors_attr(name)
    if callable(helper):
        return helper
    raise RuntimeError(f"connectors helper not callable: {name}")


def _get_minio_bucket_run(db: Session, *, run_id: UUID, tenant_id: UUID) -> ConnectorRun | None:
    run = (
        db.query(ConnectorRun)
        .options(selectinload(ConnectorRun.documents))
        .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
        .first()
    )
    if not run:
        return None
    if str(run.status or "").lower() in {"cancelled", "completed", "failed"}:
        return None
    return run


def _mark_minio_bucket_run_running(db: Session, *, run: ConnectorRun) -> None:
    run.status = "running"
    run.started_at = _resolve_connectors_helper("_now")()
    run.error_message = None
    run.stats = dict(run.stats or {})
    db.commit()
    db.refresh(run)


def _normalize_minio_include_set(values: object) -> set[str]:
    include_exts = _resolve_connectors_helper("_normalize_connector_string_list")(values)
    normalized = [("." + ext if not ext.startswith(".") else ext).lower() for ext in include_exts]
    return set(normalized) if normalized else {".pdf", ".md", ".txt"}


def _minio_connector_config_id(run_stats: dict[str, Any]) -> UUID | None:
    cfg_id = run_stats.get("config_id")
    try:
        return UUID(str(cfg_id)) if cfg_id else None
    except Exception:
        return None


def _minio_source_scope_hash(*, bucket_name: str, prefix: str | None, include_set: set[str]) -> str:
    scope_parts = [
        f"bucket={str(bucket_name or '').strip()}",
        f"prefix={str(prefix or '').strip()}",
        f"include={','.join(sorted(include_set or set()))}",
    ]
    return hashlib.sha256("|".join(scope_parts).encode("utf-8")).hexdigest()[:16]


def _minio_object_token(obj: object) -> str:
    etag = str(getattr(obj, "etag", "") or "").strip()

    last_modified_raw = getattr(obj, "last_modified", None)
    if isinstance(last_modified_raw, datetime):
        last_modified = (
            last_modified_raw.astimezone(UTC)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    else:
        last_modified = str(last_modified_raw or "").strip()

    parts: list[str] = []
    if etag:
        parts.append(f"etag:{etag}")
    if last_modified:
        parts.append(f"last_modified:{last_modified}")

    size_raw = getattr(obj, "size", None)
    with contextlib.suppress(Exception):
        size = int(size_raw or 0) if size_raw is not None else 0
        if size:
            parts.append(f"size:{size}")

    return "|".join(parts) or "unknown"


def _build_minio_bucket_run_settings(cfg: dict[str, Any], *, minio_service: Any) -> dict[str, Any]:
    bucket = cfg.get("bucket") if isinstance(cfg.get("bucket"), str) else None
    prefix = cfg.get("prefix") if isinstance(cfg.get("prefix"), str) else None
    bucket_name = str(bucket or getattr(minio_service, "_bucket_name", "") or "").strip()
    if not bucket_name:
        raise RuntimeError("minio bucket is required")

    include_set = _normalize_minio_include_set(cfg.get("include_extensions"))
    return {
        "bucket_name": bucket_name,
        "prefix": prefix,
        "max_objects": int(cfg.get("max_objects") or 50),
        "expiry": int(cfg.get("presign_expiry_sec") or 3600),
        "include_set": include_set,
        "parser_backend": cfg.get("parser_backend") if isinstance(cfg.get("parser_backend"), str) else "auto",
        "chunk_strategy": (
            cfg.get("chunk_strategy") if isinstance(cfg.get("chunk_strategy"), str) else "langchain_recursive"
        ),
        "pipeline": cfg.get("pipeline") if isinstance(cfg.get("pipeline"), dict) else None,
        "access": cfg.get("access") if isinstance(cfg.get("access"), dict) else None,
        "scope_hash": _minio_source_scope_hash(bucket_name=bucket_name, prefix=prefix, include_set=include_set),
    }


def _list_minio_bucket_objects(client: Any, *, bucket_name: str, prefix: str | None) -> list[dict[str, str]]:
    listed_objects: list[dict[str, str]] = []
    for obj in client.list_objects(bucket_name=bucket_name, prefix=(prefix or None), recursive=True):
        name = str(getattr(obj, "object_name", "") or "").strip()
        if not name:
            continue
        listed_objects.append({"name": name, "token": _minio_object_token(obj)})
    return listed_objects


def _minio_object_name_is_included(name: str, include_set: set[str]) -> bool:
    ext = Path(name).suffix.lower()
    if ext:
        return ext in include_set
    return "" in include_set


def _build_minio_bucket_execution_plan(
    *,
    run_stats: dict[str, Any],
    state: dict[str, Any],
    listed_objects: list[dict[str, str]],
    include_set: set[str],
    max_objects: int,
    scope_hash: str,
) -> dict[str, Any]:
    existing_manifest = _resolve_connectors_helper("normalize_source_manifest")(state.get("source_manifest"))
    existing_scope_hash = str(state.get("source_scope_hash") or "").strip()
    if existing_scope_hash and existing_scope_hash != scope_hash:
        existing_manifest = {}

    tracked_keys = set(existing_manifest)
    resume_cursor_raw = _resolve_connectors_helper("get_resume_cursor")(state)
    is_resume_run = bool((run_stats or {}).get("resume_of")) or bool((not existing_manifest) and resume_cursor_raw > 0)
    mode = "incremental" if existing_manifest else "full"
    resume_cursor = resume_cursor_raw if (is_resume_run and mode == "full") else 0

    total_objects = 0
    delta_objects_total = 0
    skipped_unchanged = 0
    max_objects_bound = max(1, min(int(max_objects or 0), 200))
    observed_tracked_keys: set[str] = set()
    objects_to_process: list[tuple[str, str]] = []

    for raw in listed_objects:
        name = str(raw.get("name") or "").strip()
        if not name:
            continue

        if name in tracked_keys:
            observed_tracked_keys.add(name)

        if not _minio_object_name_is_included(name, include_set):
            continue

        total_objects += 1
        token = str(raw.get("token") or "unknown")
        if mode == "incremental" and existing_manifest.get(name) == token:
            skipped_unchanged += 1
            continue

        delta_objects_total += 1
        if mode == "full" and delta_objects_total <= resume_cursor:
            continue

        if len(objects_to_process) < max_objects_bound:
            objects_to_process.append((name, token))

    cursor_in = min(max(0, int(resume_cursor or 0)), int(delta_objects_total))
    removed_paths = sorted(tracked_keys - observed_tracked_keys) if mode == "incremental" else []
    source_manifest_state = {path: token for path, token in existing_manifest.items() if path not in removed_paths}
    processed_visible = skipped_unchanged + cursor_in

    return {
        "existing_manifest": existing_manifest,
        "mode": mode,
        "total_objects": int(total_objects),
        "delta_objects_total": int(delta_objects_total),
        "skipped_unchanged": int(skipped_unchanged),
        "objects_to_process": objects_to_process,
        "cursor_in": int(cursor_in),
        "removed_paths": removed_paths,
        "source_manifest_state": source_manifest_state,
        "processed_visible": int(processed_visible),
        "resumed_from_state": bool(cursor_in > 0),
        "scope_hash": str(scope_hash),
    }


def _initialize_minio_bucket_run_stats(*, run: ConnectorRun, plan: dict[str, Any]) -> dict[str, Any]:
    stats = dict(run.stats or {})
    stats.update(
        {
            "mode": plan.get("mode"),
            "total_objects": int(plan.get("total_objects") or 0),
            "delta_objects": int(plan.get("delta_objects_total") or 0),
            "skipped_unchanged": int(plan.get("skipped_unchanged") or 0),
            "processed_objects": int(plan.get("processed_visible") or 0),
            "cursor": int(plan.get("cursor_in") or 0),
            "created": 0,
            "failed": 0,
            "cursor_in": int(plan.get("cursor_in") or 0),
            "resumed_from_state": bool(plan.get("resumed_from_state")),
            "removed_paths": int(len(plan.get("removed_paths") or [])),
            "removed_paths_reconciled": 0,
            "removed_documents_disabled": 0,
            "updated_documents_disabled": 0,
            "source_manifest": dict(plan.get("source_manifest_state") or {}),
            "source_scope_hash": str(plan.get("scope_hash") or ""),
        }
    )
    return stats


def _minio_bucket_run_cancelled(db: Session, *, run: ConnectorRun) -> bool:
    with contextlib.suppress(Exception):
        db.refresh(run)
    return str(run.status or "").lower() == "cancelled"


async def _ingest_minio_bucket_object(
    client: Any,
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    object_name: str,
    settings_map: dict[str, Any],
    connector_config_id: UUID | None,
    source_manifest_state: dict[str, str],
) -> dict[str, Any]:
    url = client.presigned_get_object(
        bucket_name=str(settings_map.get("bucket_name") or ""),
        object_name=object_name,
        expires=int(settings_map.get("expiry") or 3600),
    )
    body = _resolve_connectors_helper("UrlUploadRequest")(
        url=url,
        dataset_id=run.dataset_id,
        filename=Path(object_name).name,
        parser_backend=str(settings_map.get("parser_backend") or "auto"),
        chunk_strategy=str(settings_map.get("chunk_strategy") or "langchain_recursive"),
        pipeline=settings_map.get("pipeline"),
    )
    doc = await _resolve_connectors_helper("_ingest_url_upload_request")(
        background_tasks=None,
        body=body,
        tenant_id=tenant_id,
        account_id=requested_by,
        db=db,
    )
    _resolve_connectors_helper("_apply_document_access_from_config")(
        db,
        tenant_id=tenant_id,
        requested_by=requested_by,
        doc=doc,
        access=settings_map.get("access"),
        connector_id="minio_bucket",
    )
    _resolve_connectors_helper("_apply_connector_identity_metadata")(
        doc=doc,
        run=run,
        connector_id="minio_bucket",
        source_ref=object_name,
        source_id=object_name,
    )
    db.add(
        ConnectorRunDocument(
            tenant_id=tenant_id,
            run_id=run.id,
            document_id=doc.id,
            source_ref=object_name,
            status="created",
        )
    )

    updated_documents_disabled = 0
    if object_name in source_manifest_state:
        with contextlib.suppress(Exception):
            updated_documents_disabled += int(
                _resolve_connectors_helper("_soft_disable_connector_documents_by_source_ref")(
                    db,
                    tenant_id=tenant_id,
                    dataset_id=run.dataset_id,
                    connector_id="minio_bucket",
                    source_ref=object_name,
                    connector_config_id=connector_config_id,
                    exclude_document_id=doc.id,
                )
            )

    return {
        "doc_id": doc.id,
        "updated_documents_disabled": int(updated_documents_disabled),
    }


def _persist_minio_bucket_progress(
    db: Session,
    *,
    run: ConnectorRun,
    plan: dict[str, Any],
    processed: int,
    created: int,
    failed: int,
    created_doc_ids: list[UUID],
    removed_paths_reconciled: int,
    removed_documents_disabled: int,
    updated_documents_disabled: int,
    source_manifest_state: dict[str, str],
) -> None:
    stats = dict(run.stats or {})
    stats.update(
        {
            "mode": plan.get("mode"),
            "total_objects": int(plan.get("total_objects") or 0),
            "delta_objects": int(plan.get("delta_objects_total") or 0),
            "skipped_unchanged": int(plan.get("skipped_unchanged") or 0),
            "processed_objects": int(int(plan.get("skipped_unchanged") or 0) + processed),
            "cursor": int(processed),
            "created": int(created),
            "failed": int(failed),
            "removed_paths": int(len(plan.get("removed_paths") or [])),
            "removed_paths_reconciled": int(removed_paths_reconciled),
            "removed_documents_disabled": int(removed_documents_disabled),
            "updated_documents_disabled": int(updated_documents_disabled),
            "source_manifest": dict(source_manifest_state),
            "source_scope_hash": str(plan.get("scope_hash") or ""),
            "document_ids": [str(doc_id) for doc_id in created_doc_ids],
        }
    )
    run.stats = _resolve_connectors_helper("_finalize_connector_stats")(stats)
    db.commit()


async def _process_minio_bucket_objects(
    client: Any,
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    requested_by: str,
    settings_map: dict[str, Any],
    plan: dict[str, Any],
    connector_config_id: UUID | None,
) -> dict[str, Any]:
    created = 0
    failed = 0
    created_doc_ids: list[UUID] = []
    removed_paths_reconciled = 0
    removed_documents_disabled = 0
    updated_documents_disabled = 0
    source_manifest_state = dict(plan.get("source_manifest_state") or {})
    cursor_in = int(plan.get("cursor_in") or 0)
    mode = str(plan.get("mode") or "")

    for idx, item in enumerate(plan.get("objects_to_process") or []):
        object_name, object_token = item if isinstance(item, tuple) else (str(item or ""), "unknown")
        if _resolve_connectors_helper("_minio_bucket_run_cancelled")(db, run=run):
            break

        try:
            result = await _resolve_connectors_helper("_ingest_minio_bucket_object")(
                client,
                db,
                run=run,
                tenant_id=tenant_id,
                requested_by=requested_by,
                object_name=object_name,
                settings_map={**settings_map, "mode_hint": mode},
                connector_config_id=connector_config_id,
                source_manifest_state=source_manifest_state if mode == "incremental" else {},
            )
            created += 1
            created_doc_ids.append(result["doc_id"])
            updated_documents_disabled += int(result.get("updated_documents_disabled") or 0)
            source_manifest_state[object_name] = object_token
        except Exception as exc:  # noqa: BLE001
            failed += 1
            run.stats = _resolve_connectors_helper("_append_connector_error")(dict(run.stats or {}), url=object_name, exc=exc)
        finally:
            _resolve_connectors_helper("_persist_minio_bucket_progress")(
                db,
                run=run,
                plan=plan,
                processed=cursor_in + idx + 1,
                created=created,
                failed=failed,
                created_doc_ids=created_doc_ids,
                removed_paths_reconciled=removed_paths_reconciled,
                removed_documents_disabled=removed_documents_disabled,
                updated_documents_disabled=updated_documents_disabled,
                source_manifest_state=source_manifest_state,
            )

    return {
        "created": created,
        "failed": failed,
        "created_doc_ids": created_doc_ids,
        "removed_paths_reconciled": removed_paths_reconciled,
        "removed_documents_disabled": removed_documents_disabled,
        "updated_documents_disabled": updated_documents_disabled,
        "source_manifest_state": source_manifest_state,
    }


def _finalize_cancelled_minio_bucket_run(db: Session, *, run: ConnectorRun) -> None:
    if run.finished_at is None:
        run.finished_at = _resolve_connectors_helper("_now")()
    run.stats = _resolve_connectors_helper("_finalize_connector_stats")(dict(run.stats or {}))
    db.commit()
    with contextlib.suppress(Exception):
        _resolve_connectors_helper("_sync_connector_config_from_run")(db, run=run)


def _reconcile_removed_minio_bucket_paths(
    db: Session,
    *,
    run: ConnectorRun,
    tenant_id: UUID,
    removed_paths: list[str],
    connector_config_id: UUID | None,
) -> tuple[int, int]:
    removed_paths_reconciled = 0
    removed_documents_disabled = 0
    for source_ref in removed_paths:
        try:
            disabled = _resolve_connectors_helper("_soft_disable_connector_documents_by_source_ref")(
                db,
                tenant_id=tenant_id,
                dataset_id=run.dataset_id,
                connector_id="minio_bucket",
                source_ref=source_ref,
                connector_config_id=connector_config_id,
            )
        except Exception as exc:  # noqa: BLE001
            stats = _resolve_connectors_helper("_append_connector_error")(dict(run.stats or {}), url=source_ref, exc=exc)
            run.stats = _resolve_connectors_helper("_finalize_connector_stats")(stats)
            db.commit()
            continue
        removed_documents_disabled += int(disabled)
        if disabled:
            removed_paths_reconciled += 1
    return removed_paths_reconciled, removed_documents_disabled


def _finalize_minio_bucket_run_success(
    db: Session,
    *,
    run: ConnectorRun,
    plan: dict[str, Any],
    progress: dict[str, Any],
) -> None:
    stats = dict(run.stats or {})
    stats.update(
        {
            "mode": plan.get("mode"),
            "delta_objects": int(plan.get("delta_objects_total") or 0),
            "skipped_unchanged": int(plan.get("skipped_unchanged") or 0),
            "removed_paths": int(len(plan.get("removed_paths") or [])),
            "removed_paths_reconciled": int(progress.get("removed_paths_reconciled") or 0),
            "removed_documents_disabled": int(progress.get("removed_documents_disabled") or 0),
            "updated_documents_disabled": int(progress.get("updated_documents_disabled") or 0),
            "source_manifest": dict(progress.get("source_manifest_state") or {}),
            "source_scope_hash": str(plan.get("scope_hash") or ""),
            "document_ids": [str(doc_id) for doc_id in (progress.get("created_doc_ids") or [])],
        }
    )
    run.stats = _resolve_connectors_helper("_finalize_connector_stats")(stats)
    run.finished_at = _resolve_connectors_helper("_now")()
    run.status = _resolve_connectors_helper("_connector_run_completion_status")(
        created=int(progress.get("created") or 0),
        failed=int(progress.get("failed") or 0),
    )
    db.commit()
    with contextlib.suppress(Exception):
        _resolve_connectors_helper("_sync_connector_config_from_run")(db, run=run)


def _mark_minio_bucket_run_failed(db: Session, *, run_id: UUID, tenant_id: UUID, exc: Exception) -> None:
    with contextlib.suppress(Exception):
        run = (
            db.query(ConnectorRun)
            .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
            .first()
        )
        if run is not None:
            run.status = "failed"
            run.finished_at = _resolve_connectors_helper("_now")()
            run.error_message = str(exc)[:200]
            db.commit()
            with contextlib.suppress(Exception):
                _resolve_connectors_helper("_sync_connector_config_from_run")(db, run=run)


async def _execute_minio_bucket_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    """
    Background execution for minio_bucket connector.
    """
    db = _resolve_connectors_attr("SessionLocal")()
    run: ConnectorRun | None = None
    try:
        run = _get_minio_bucket_run(db, run_id=run_id, tenant_id=tenant_id)
        if run is None:
            return

        _mark_minio_bucket_run_running(db, run=run)
        cfg = _resolve_connectors_helper("decrypt_connector_config_secrets")(dict(run.config or {}))

        from app.storage.object.minio import minio_service

        client = minio_service._get_client()  # noqa: SLF001
        state = cfg.get("_state") if isinstance(cfg.get("_state"), dict) else {}
        settings_map = _build_minio_bucket_run_settings(cfg, minio_service=minio_service)
        connector_config_id = _minio_connector_config_id(dict(run.stats or {}))
        listed_objects = _list_minio_bucket_objects(
            client,
            bucket_name=str(settings_map.get("bucket_name") or ""),
            prefix=(settings_map.get("prefix") if isinstance(settings_map.get("prefix"), str) else None),
        )
        plan = _build_minio_bucket_execution_plan(
            run_stats=dict(run.stats or {}),
            state=state,
            listed_objects=listed_objects,
            include_set=set(settings_map.get("include_set") or set()),
            max_objects=int(settings_map.get("max_objects") or 50),
            scope_hash=str(settings_map.get("scope_hash") or ""),
        )
        run.stats = _initialize_minio_bucket_run_stats(run=run, plan=plan)
        db.commit()

        progress = await _process_minio_bucket_objects(
            client,
            db,
            run=run,
            tenant_id=tenant_id,
            requested_by=requested_by,
            settings_map=settings_map,
            plan=plan,
            connector_config_id=connector_config_id,
        )
        if _minio_bucket_run_cancelled(db, run=run):
            _finalize_cancelled_minio_bucket_run(db, run=run)
            return

        removed_paths = list(plan.get("removed_paths") or [])
        if plan.get("mode") == "incremental" and removed_paths:
            removed_paths_reconciled, removed_documents_disabled = _reconcile_removed_minio_bucket_paths(
                db,
                run=run,
                tenant_id=tenant_id,
                removed_paths=removed_paths,
                connector_config_id=connector_config_id,
            )
            progress["removed_paths_reconciled"] = int(removed_paths_reconciled)
            progress["removed_documents_disabled"] = int(removed_documents_disabled)

        _finalize_minio_bucket_run_success(
            db,
            run=run,
            plan=plan,
            progress=progress,
        )
    except Exception as exc:  # noqa: BLE001
        _mark_minio_bucket_run_failed(db, run_id=run_id, tenant_id=tenant_id, exc=exc)
    finally:
        db.close()
