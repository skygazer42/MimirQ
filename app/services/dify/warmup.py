"""Schedule and drain Dify retrieval warmup during application lifespan."""

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

import anyio
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.infrastructure.config import settings
from app.infrastructure.database.connection import SessionLocal
from app.infrastructure.runtime.async_bridge import _wait_for_worker_after_cancellation, run_blocking_in_thread
from app.services.dify.citation_records import retrieve_dataset_citations
from app.services.dify.common import _diagnostic_value_hash
from app.services.dify.knowledge_scope import (
    load_knowledge_map,
    primary_scope_dataset_ids,
    resolve_scope,
    resolve_warmup_knowledge_ids,
)
from app.services.dify.response_cache import (
    _acquire_dify_warmup_lease,
    _DifyDistributedLease,
    _maintain_best_effort_dify_lease,
    _release_distributed_dify_response_lease,
)
from app.services.dify.warmup_state import set_dify_external_warmup_status

logger = logging.getLogger("app.api.v1.integrations_dify")
_DEFAULT_QUERY = "warmup probe"
_dify_external_warmup_tasks: set[asyncio.Task[dict[str, Any]]] = set()
_dify_external_warmup_workers: set[asyncio.Task[None]] = set()
_dify_external_warmup_cleanup: set[asyncio.Task[None]] = set()


def _resolve_dify_warmup_tenant_id() -> UUID | None:
    raw_tenant = (settings.DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID or settings.DEFAULT_TENANT_ID).strip()
    if not raw_tenant:
        return None
    try:
        return UUID(raw_tenant)
    except ValueError:
        logger.warning("Skipping Dify external warmup: tenant id is invalid", exc_info=True)
        return None


async def warmup_dify_external_knowledge(
    *,
    db_factory: Callable[[], Session] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    disabled_result = _dify_external_warmup_disabled_result()
    if disabled_result is not None:
        return disabled_result
    set_dify_external_warmup_status(
        enabled=True,
        status="running",
        attempted=0,
        completed=0,
        failed=0,
        elapsed_ms=None,
    )

    try:
        knowledge_map = load_knowledge_map()
    except (HTTPException, RecursionError):
        logger.warning("Skipping Dify external warmup: knowledge map is invalid", exc_info=True)
        return _dify_external_warmup_status_result(
            status="failed",
            reason="invalid_knowledge_map",
            started=started,
            failed=1,
        )

    knowledge_ids = resolve_warmup_knowledge_ids(knowledge_map)
    tenant_id = _resolve_dify_warmup_tenant_id()
    if tenant_id is None or not knowledge_ids:
        return _dify_external_warmup_status_result(
            status="skipped",
            reason="tenant_not_configured" if tenant_id is None else "no_knowledge_ids",
            started=started,
        )
    if settings.RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY == 1:
        return _dify_external_warmup_status_result(
            status="skipped",
            reason="warmup_skipped_single_retrieval_slot",
            started=started,
        )
    set_dify_external_warmup_status(enabled=True, status="running", attempted=len(knowledge_ids))

    factory = db_factory if db_factory is not None else SessionLocal
    account_id = settings.DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID.strip()
    query = settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_QUERY.strip() or _DEFAULT_QUERY
    top_k = min(settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TOP_K, settings.DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX)
    timeout_sec = settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TIMEOUT_SEC
    warmup_lease, warmup_lease_ttl_sec = await _acquire_dify_warmup_lease(
        knowledge_count=len(knowledge_ids),
        timeout_sec=timeout_sec,
    )
    if warmup_lease is None:
        return _dify_external_warmup_locked_result(
            started=started,
            warmup_lease_ttl_sec=warmup_lease_ttl_sec,
        )
    lease_heartbeat_task = _dify_external_warmup_lease_task(warmup_lease, warmup_lease_ttl_sec)
    completed = 0
    failed = 0
    lease_workers: set[asyncio.Task[None]] = set()

    try:
        for knowledge_id in knowledge_ids:
            success = await _run_dify_external_warmup_iteration(
                knowledge_id,
                factory=factory,
                tenant_id=tenant_id,
                account_id=account_id,
                query=query,
                top_k=top_k,
                timeout_sec=timeout_sec,
                lease_workers=lease_workers,
            )
            completed += int(success)
            failed += int(not success)
    finally:
        cleanup = asyncio.create_task(
            _finish_dify_warmup_lease(
                tuple(lease_workers),
                heartbeat=lease_heartbeat_task,
                lease=warmup_lease,
            )
        )
        _dify_external_warmup_cleanup.add(cleanup)
        cleanup.add_done_callback(_observe_dify_warmup_cleanup)
        if not lease_workers:
            await asyncio.shield(cleanup)

    result = _dify_external_warmup_status_result(
        status="completed" if failed == 0 else "failed",
        reason="completed",
        started=started,
        attempted=len(knowledge_ids),
        completed=completed,
        failed=failed,
    )
    logger.info(
        "Dify external warmup finished attempted=%s completed=%s failed=%s elapsed_ms=%s",
        result["attempted"],
        completed,
        failed,
        result["elapsed_ms"],
        extra={"event": "dify_external_warmup", "phase": "finished", **result},
    )
    return result


def _dify_external_warmup_disabled_result() -> dict[str, Any] | None:
    enabled = settings.DIFY_EXTERNAL_KNOWLEDGE_ENABLED
    if enabled and settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_ENABLED:
        return None
    set_dify_external_warmup_status(
        enabled=enabled,
        status="disabled",
        attempted=0,
        completed=0,
        failed=0,
        elapsed_ms=0,
    )
    return {
        "enabled": False,
        "reason": "warmup_disabled" if enabled else "external_knowledge_disabled",
        "attempted": 0,
        "completed": 0,
        "failed": 0,
    }


def _dify_external_warmup_status_result(
    *,
    status: str,
    reason: str,
    started: float,
    attempted: int = 0,
    completed: int = 0,
    failed: int = 0,
) -> dict[str, Any]:
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    set_dify_external_warmup_status(
        enabled=True,
        status=status,
        attempted=attempted,
        completed=completed,
        failed=failed,
        elapsed_ms=elapsed_ms,
    )
    return {
        "enabled": True,
        "reason": reason,
        "attempted": attempted,
        "completed": completed,
        "failed": failed,
        "elapsed_ms": elapsed_ms,
    }


def _dify_external_warmup_locked_result(
    *,
    started: float,
    warmup_lease_ttl_sec: int | None,
) -> dict[str, Any]:
    result = _dify_external_warmup_status_result(
        status="skipped",
        reason="warmup_lease_unavailable" if warmup_lease_ttl_sec is None else "warmup_locked",
        started=started,
    )
    if warmup_lease_ttl_sec is not None:
        result["retry_after_sec"] = warmup_lease_ttl_sec
    return result


def _dify_external_warmup_lease_task(
    warmup_lease: _DifyDistributedLease,
    warmup_lease_ttl_sec: int | None,
) -> asyncio.Task[None] | None:
    if warmup_lease_ttl_sec is None:
        return None
    return asyncio.create_task(
        _maintain_best_effort_dify_lease(
            warmup_lease,
            ttl_sec=warmup_lease_ttl_sec,
        )
    )


async def _retrieve_dify_warmup_citations(
    *,
    factory: Callable[[], Session],
    tenant_id: UUID,
    account_id: str,
    dataset_ids: list[UUID],
    query: str,
    top_k: int,
) -> None:
    db = factory()
    try:
        await retrieve_dataset_citations(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_ids=dataset_ids,
            query=query,
            top_k=top_k,
            requested_top_k=top_k,
            score_threshold=0.0,
            enable_kg_query_expansion=False,
            enable_kg_chunk_injection=False,
            enable_kg_chunk_boost=False,
            enable_reranker=False,
        )
    finally:
        await run_blocking_in_thread(db.close)


def _observe_dify_warmup_worker(task: asyncio.Task[None]) -> None:
    _dify_external_warmup_workers.discard(task)
    try:
        task.result()
    except asyncio.CancelledError:
        logger.warning("Dify warmup worker was cancelled before completion")
    except Exception:
        logger.warning("Dify warmup worker failed after report completion", exc_info=True)


async def _run_dify_external_warmup_iteration(
    knowledge_id: str,
    *,
    factory: Callable[[], Session],
    tenant_id: UUID,
    account_id: str,
    query: str,
    top_k: int,
    timeout_sec: float,
    lease_workers: set[asyncio.Task[None]],
) -> bool:
    item_started = time.perf_counter()
    try:
        scope_plan = resolve_scope(knowledge_id, query=query)
        dataset_ids = primary_scope_dataset_ids(
            scope_plan, primary_scope_enabled=settings.DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_SCOPE_ENABLED
        )
        worker = asyncio.create_task(
            _retrieve_dify_warmup_citations(
                factory=factory,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_ids=dataset_ids,
                query=query,
                top_k=top_k,
            )
        )
        _dify_external_warmup_workers.add(worker)
        worker.add_done_callback(_observe_dify_warmup_worker)
        lease_workers.add(worker)
        worker.add_done_callback(lease_workers.discard)
        await asyncio.wait_for(asyncio.shield(worker), timeout=timeout_sec)
        _log_dify_external_warmup_iteration(
            knowledge_id,
            dataset_count=len(dataset_ids),
            item_started=item_started,
            success=True,
        )
        return True
    except Exception:  # noqa: BLE001
        _log_dify_external_warmup_iteration(
            knowledge_id,
            dataset_count=0,
            item_started=item_started,
            success=False,
        )
        return False


def _log_dify_external_warmup_iteration(
    knowledge_id: str,
    *,
    dataset_count: int,
    item_started: float,
    success: bool,
) -> None:
    item_elapsed_ms = round((time.perf_counter() - item_started) * 1000, 2)
    knowledge_id_hash = _diagnostic_value_hash(knowledge_id)
    if success:
        logger.info(
            "Dify external warmup completed knowledge_id_hash=%s dataset_count=%s elapsed_ms=%s",
            knowledge_id_hash,
            dataset_count,
            item_elapsed_ms,
            extra={
                "event": "dify_external_warmup",
                "phase": "knowledge_completed",
                "knowledge_id_hash": knowledge_id_hash,
                "dataset_count": dataset_count,
                "elapsed_ms": item_elapsed_ms,
            },
        )
        return
    logger.warning(
        "Dify external warmup failed knowledge_id_hash=%s elapsed_ms=%s",
        knowledge_id_hash,
        item_elapsed_ms,
        exc_info=True,
        extra={
            "event": "dify_external_warmup",
            "phase": "knowledge_failed",
            "knowledge_id_hash": knowledge_id_hash,
            "elapsed_ms": item_elapsed_ms,
        },
    )


async def _delayed_warmup_dify_external_knowledge(delay_sec: float) -> dict[str, Any]:
    await asyncio.sleep(delay_sec)
    result = await warmup_dify_external_knowledge()
    if result["reason"] != "warmup_locked":
        return result

    await asyncio.sleep(result["retry_after_sec"])
    return await warmup_dify_external_knowledge()


def _log_dify_warmup_task_result(task: asyncio.Task[dict[str, Any]]) -> None:
    _dify_external_warmup_tasks.discard(task)
    try:
        task.result()
    except asyncio.CancelledError:
        logger.info("Dify external warmup task cancelled")
    except Exception:  # noqa: BLE001
        logger.warning("Dify external warmup task failed", exc_info=True)


async def _finish_dify_warmup_lease(
    workers: tuple[asyncio.Task[None], ...],
    *,
    heartbeat: asyncio.Task[None] | None,
    lease: _DifyDistributedLease,
) -> None:
    try:
        await asyncio.gather(*workers, return_exceptions=True)
    finally:
        if heartbeat is not None:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        await _release_distributed_dify_response_lease(lease)


def _observe_dify_warmup_cleanup(task: asyncio.Task[None]) -> None:
    _dify_external_warmup_cleanup.discard(task)
    try:
        task.result()
    except asyncio.CancelledError:
        logger.warning("Dify warmup lease cleanup was cancelled")
    except Exception:
        logger.warning("Dify warmup lease cleanup failed", exc_info=True)


async def stop_dify_external_knowledge_warmup() -> None:
    """Drain scheduled warmup, its actual retrieval workers and their leases."""

    async def drain() -> None:
        parents = tuple(_dify_external_warmup_tasks)
        for task in parents:
            task.cancel()
        await asyncio.gather(*parents, return_exceptions=True)
        await asyncio.gather(*tuple(_dify_external_warmup_workers), return_exceptions=True)
        await asyncio.gather(*tuple(_dify_external_warmup_cleanup), return_exceptions=True)

    waiter = asyncio.create_task(drain())
    try:
        with anyio.CancelScope(shield=True):
            await asyncio.shield(waiter)
    except asyncio.CancelledError:
        with anyio.CancelScope(shield=True):
            error = await _wait_for_worker_after_cancellation(waiter)
        if error is not None:
            logger.warning("Dify warmup shutdown failed while propagating cancellation: %s", type(error).__name__)
        raise


def start_dify_external_knowledge_warmup() -> asyncio.Task[dict[str, Any]] | None:
    enabled = settings.DIFY_EXTERNAL_KNOWLEDGE_ENABLED
    if not enabled or not settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_ENABLED:
        set_dify_external_warmup_status(enabled=enabled, status="disabled")
        return None

    delay_sec = settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_START_DELAY_SEC
    set_dify_external_warmup_status(enabled=True, status="scheduled", start_delay_sec=delay_sec)
    coroutine = _delayed_warmup_dify_external_knowledge(delay_sec)
    try:
        task = asyncio.create_task(coroutine)
    except BaseException:
        coroutine.close()
        raise

    _dify_external_warmup_tasks.add(task)
    task.add_done_callback(_log_dify_warmup_task_result)
    logger.info("Dify external warmup scheduled start_delay_sec=%s", delay_sec)
    return task


__all__ = [
    "start_dify_external_knowledge_warmup",
    "stop_dify_external_knowledge_warmup",
]
