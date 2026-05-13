from __future__ import annotations

import contextlib
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from app.models.connector import ConnectorRun, ConnectorRunDocument


def _get_url_batch_run(db: Session, *, run_id: UUID, tenant_id: UUID) -> ConnectorRun | None:
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


def _mark_url_batch_run_running(db: Session, *, run: ConnectorRun) -> None:
    from app.api.v1 import connectors as connectors_module  # Local import to preserve monkeypatch surface.

    run.status = "running"
    if run.started_at is None:
        run.started_at = connectors_module._now()
    run.error_message = None
    run.stats = dict(run.stats or {})
    db.commit()
    db.refresh(run)


def _build_url_batch_run_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    from app.api.v1 import connectors as connectors_module  # Local import to preserve monkeypatch surface.

    access = cfg.get("access") if isinstance(cfg.get("access"), dict) else None
    access_mode = str(access.get("mode") or "inherit").strip().lower() if isinstance(access, dict) else "inherit"
    return {
        "urls": connectors_module._normalize_connector_string_list(cfg.get("urls")),
        "filename": cfg.get("filename") if isinstance(cfg.get("filename"), str) else None,
        "user_agent": cfg.get("user_agent") if isinstance(cfg.get("user_agent"), str) else None,
        "parser_backend": cfg.get("parser_backend") if isinstance(cfg.get("parser_backend"), str) else "auto",
        "chunk_strategy": (
            cfg.get("chunk_strategy") if isinstance(cfg.get("chunk_strategy"), str) else "langchain_recursive"
        ),
        "pipeline": cfg.get("pipeline") if isinstance(cfg.get("pipeline"), dict) else None,
        "access_mode": access_mode,
        "access_members": connectors_module._normalize_connector_principal_list(
            access.get("partial_member_list") if isinstance(access, dict) else None
        ),
        "access_groups": connectors_module._normalize_connector_principal_list(
            access.get("partial_group_list") if isinstance(access, dict) else None
        ),
        "auth_headers": connectors_module._build_auth_headers(cfg),
    }


def _url_batch_processed_refs(documents: list[Any]) -> set[str]:
    processed_refs: set[str] = set()
    for doc in documents:
        ref = str(getattr(doc, "source_ref", "") or "").strip()
        if ref:
            processed_refs.add(ref)
    return processed_refs


def _url_batch_document_ids(*, stats: dict[str, Any], documents: list[Any]) -> list[str]:
    raw_doc_ids = stats.get("document_ids")
    if isinstance(raw_doc_ids, list):
        doc_ids = [str(value).strip() for value in raw_doc_ids if str(value).strip()]
        if doc_ids:
            return doc_ids
    return [
        str(getattr(doc, "document_id", "") or "")
        for doc in documents
        if str(getattr(doc, "document_id", "") or "").strip()
    ]


def _build_url_batch_run_state(*, run: ConnectorRun, urls: list[str]) -> dict[str, Any]:
    documents = list(getattr(run, "documents", None) or [])
    processed_refs = _url_batch_processed_refs(documents)

    stats = dict(run.stats or {})
    cursor_raw = stats.get("cursor", stats.get("processed_urls", 0))
    try:
        cursor = max(0, int(cursor_raw or 0))
    except Exception:
        cursor = 0

    stats.setdefault("total_urls", int(len(urls)))
    stats.setdefault("processed_urls", int(cursor))
    stats.setdefault("cursor", int(cursor))
    stats.setdefault("failed_urls", [])
    stats.setdefault("errors", [])
    stats.setdefault("error_groups", [])

    created_doc_ids = _url_batch_document_ids(stats=stats, documents=documents)
    stats["document_ids"] = created_doc_ids

    def _safe_int(value: object, default: int = 0) -> int:
        try:
            return int(value or 0)
        except Exception:
            return int(default)

    created = _safe_int(stats.get("created"), default=len(created_doc_ids))
    failed = _safe_int(stats.get("failed"), default=0)
    stats.setdefault("created", int(created))
    stats.setdefault("failed", int(failed))

    return {
        "processed_refs": processed_refs,
        "cursor": int(cursor),
        "start_idx": int(max(0, min(cursor, len(urls)))),
        "stats": stats,
        "created_doc_ids": created_doc_ids,
        "created": int(created),
        "failed": int(failed),
    }


def _url_batch_run_cancelled(db: Session, *, run: ConnectorRun) -> bool:
    with contextlib.suppress(Exception):
        db.refresh(run)
    return str(run.status or "").lower() == "cancelled"


async def _ingest_url_batch_url(
    db: Session,
    *,
    run: ConnectorRun,
    run_id: UUID,
    tenant_id: UUID,
    requested_by: str,
    url: str,
    settings_map: dict[str, Any],
) -> str:
    from app.api.v1 import connectors as connectors_module  # Local import to preserve monkeypatch surface.
    from app.api.v1.documents import UrlUploadRequest

    body = UrlUploadRequest(
        url=url,
        dataset_id=run.dataset_id,
        filename=settings_map.get("filename"),
        fetch_headers=settings_map.get("auth_headers") or None,
        user_agent=settings_map.get("user_agent"),
        parser_backend=settings_map.get("parser_backend"),
        chunk_strategy=settings_map.get("chunk_strategy"),
        pipeline=settings_map.get("pipeline"),  # type: ignore[arg-type]
    )
    doc = await connectors_module._ingest_url_upload_request(
        background_tasks=None,
        body=body,
        tenant_id=tenant_id,
        account_id=requested_by,
        db=db,
    )

    connectors_module._apply_document_access_from_config(
        db,
        tenant_id=tenant_id,
        requested_by=requested_by,
        doc=doc,
        access={
            "mode": settings_map.get("access_mode"),
            "partial_member_list": list(settings_map.get("access_members") or []),
            "partial_group_list": list(settings_map.get("access_groups") or []),
        },
        connector_id="url_batch",
    )
    connectors_module._apply_connector_identity_metadata(
        doc=doc,
        run=run,
        connector_id="url_batch",
        source_ref=url,
        source_id=url,
    )

    db.add(
        ConnectorRunDocument(
            tenant_id=tenant_id,
            run_id=run_id,
            document_id=doc.id,
            source_ref=url,
            status="created",
        )
    )
    return str(doc.id)


def _persist_url_batch_progress(
    db: Session,
    *,
    run: ConnectorRun,
    urls: list[str],
    processed: int,
    created: int,
    failed: int,
    created_doc_ids: list[str],
) -> None:
    from app.api.v1 import connectors as connectors_module  # Local import to preserve monkeypatch surface.

    stats = dict(run.stats or {})
    stats.update(
        {
            "total_urls": int(len(urls)),
            "processed_urls": int(processed),
            "cursor": int(processed),
            "created": int(created),
            "failed": int(failed),
            "document_ids": list(created_doc_ids),
        }
    )
    run.stats = connectors_module._finalize_connector_stats(stats)
    db.commit()


async def _process_url_batch_urls(
    db: Session,
    *,
    run: ConnectorRun,
    run_id: UUID,
    tenant_id: UUID,
    requested_by: str,
    urls: list[str],
    settings_map: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    from app.api.v1 import connectors as connectors_module  # Local import to preserve monkeypatch surface.

    processed_refs = set(state.get("processed_refs") or set())
    created_doc_ids = list(state.get("created_doc_ids") or [])
    created = int(state.get("created") or 0)
    failed = int(state.get("failed") or 0)
    start_idx = int(state.get("start_idx") or 0)

    for idx in range(start_idx, len(urls)):
        url = urls[idx]
        if _url_batch_run_cancelled(db, run=run):
            break

        try:
            if url in processed_refs:
                continue
            doc_id = await _ingest_url_batch_url(
                db,
                run=run,
                run_id=run_id,
                tenant_id=tenant_id,
                requested_by=requested_by,
                url=url,
                settings_map=settings_map,
            )
            created += 1
            created_doc_ids.append(doc_id)
            processed_refs.add(url)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            run.stats = connectors_module._append_connector_error(dict(run.stats or {}), url=url, exc=exc)
        finally:
            _persist_url_batch_progress(
                db,
                run=run,
                urls=urls,
                processed=idx + 1,
                created=created,
                failed=failed,
                created_doc_ids=created_doc_ids,
            )

    return {
        "created": created,
        "failed": failed,
        "created_doc_ids": created_doc_ids,
    }


def _finalize_cancelled_url_batch_run(db: Session, *, run: ConnectorRun) -> None:
    from app.api.v1 import connectors as connectors_module  # Local import to preserve monkeypatch surface.

    if run.finished_at is None:
        run.finished_at = connectors_module._now()
    run.stats = connectors_module._finalize_connector_stats(dict(run.stats or {}))
    db.commit()
    with contextlib.suppress(Exception):
        connectors_module._sync_connector_config_from_run(db, run=run)


def _finalize_url_batch_run_success(
    db: Session,
    *,
    run: ConnectorRun,
    created: int,
    failed: int,
    created_doc_ids: list[str],
) -> None:
    from app.api.v1 import connectors as connectors_module  # Local import to preserve monkeypatch surface.

    stats = dict(run.stats or {})
    stats["document_ids"] = [str(doc_id) for doc_id in created_doc_ids]
    run.stats = connectors_module._finalize_connector_stats(stats)
    run.finished_at = connectors_module._now()
    run.status = connectors_module._connector_run_completion_status(created=created, failed=failed)
    db.commit()
    with contextlib.suppress(Exception):
        connectors_module._sync_connector_config_from_run(db, run=run)


def _mark_url_batch_run_failed(db: Session, *, run_id: UUID, tenant_id: UUID, exc: Exception) -> None:
    from app.api.v1 import connectors as connectors_module  # Local import to preserve monkeypatch surface.

    with contextlib.suppress(Exception):
        run = (
            db.query(ConnectorRun)
            .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
            .first()
        )
        if run is not None:
            run.status = "failed"
            run.finished_at = connectors_module._now()
            run.error_message = str(exc)[:200]
            db.commit()
            with contextlib.suppress(Exception):
                connectors_module._sync_connector_config_from_run(db, run=run)


async def _execute_url_batch_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    from app.api.v1 import connectors as connectors_module  # Local import to preserve monkeypatch surface.

    db = connectors_module.SessionLocal()
    run: ConnectorRun | None = None
    try:
        run = _get_url_batch_run(db, run_id=run_id, tenant_id=tenant_id)
        if run is None:
            return

        _mark_url_batch_run_running(db, run=run)
        cfg = connectors_module.decrypt_connector_config_secrets(dict(run.config or {}))
        settings_map = _build_url_batch_run_settings(cfg)
        urls = list(settings_map.get("urls") or [])
        state = _build_url_batch_run_state(run=run, urls=urls)
        run.stats = dict(state.get("stats") or {})
        db.commit()

        progress = await _process_url_batch_urls(
            db,
            run=run,
            run_id=run_id,
            tenant_id=tenant_id,
            requested_by=requested_by,
            urls=urls,
            settings_map=settings_map,
            state=state,
        )
        if _url_batch_run_cancelled(db, run=run):
            _finalize_cancelled_url_batch_run(db, run=run)
            return

        _finalize_url_batch_run_success(
            db,
            run=run,
            created=int(progress.get("created") or 0),
            failed=int(progress.get("failed") or 0),
            created_doc_ids=list(progress.get("created_doc_ids") or []),
        )
    except Exception as exc:  # noqa: BLE001
        _mark_url_batch_run_failed(db, run_id=run_id, tenant_id=tenant_id, exc=exc)
    finally:
        db.close()
