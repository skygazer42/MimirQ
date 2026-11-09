"""Dify warmup operations."""

import asyncio
import contextlib
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.rag.core.logging import get_logger
from app.rag.retrieval.planner import DatasetScopePlan
from app.services.dify_integration import common, evidence_adapter, knowledge_scope, response_cache

logger = get_logger(__name__)

_DIFY_WARMUP_DEFAULT_QUERY = "warmup probe"

_dify_external_warmup_state_lock = threading.Lock()

_dify_external_warmup_tasks: set[asyncio.Task[Any]] = set()

_dify_external_warmup_state: dict[str, Any] = {
    "enabled": False,
    "status": "idle",
    "attempted": 0,
    "completed": 0,
    "failed": 0,
    "elapsed_ms": None,
    "updated_at": None,
}


def _dify_warmup_can_use_retrieval_slot() -> bool:
    try:
        limit = settings.RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY
    except (TypeError, ValueError):
        limit = 1
    return limit <= 0 or limit > 1


def _set_dify_external_warmup_status(**updates: Any) -> None:
    with _dify_external_warmup_state_lock:
        _dify_external_warmup_state.update(updates)
        _dify_external_warmup_state["updated_at"] = datetime.now(UTC).isoformat()


def get_dify_external_knowledge_warmup_status() -> dict[str, Any]:
    with _dify_external_warmup_state_lock:
        return dict(_dify_external_warmup_state)


def dify_external_knowledge_warmup_ready() -> bool:
    if not settings.DIFY_EXTERNAL_KNOWLEDGE_ENABLED:
        return True
    if not settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_ENABLED:
        return True
    return str(get_dify_external_knowledge_warmup_status().get("status") or "idle") == "completed"


def _resolve_dify_warmup_tenant_id() -> UUID | None:
    raw_tenant = (settings.DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID or settings.DEFAULT_TENANT_ID).strip()
    if not raw_tenant:
        return None
    try:
        return UUID(raw_tenant)
    except ValueError:
        logger.warning("Skipping Dify external warmup: tenant id is invalid")
        return None


def _resolve_dify_warmup_query() -> str:
    query = settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_QUERY.strip()
    return query or _DIFY_WARMUP_DEFAULT_QUERY


def _resolve_dify_warmup_top_k() -> int:
    try:
        configured_top_k = settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TOP_K or 1
    except (TypeError, ValueError):
        configured_top_k = 1
    try:
        configured_max = settings.DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX or 5
    except (TypeError, ValueError):
        configured_max = 5
    return max(1, min(configured_top_k, max(1, configured_max)))


def _resolve_dify_warmup_timeout_sec() -> float:
    try:
        timeout_sec = float(settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TIMEOUT_SEC)
    except (TypeError, ValueError):
        timeout_sec = 60.0
    return max(1.0, timeout_sec)


def _resolve_dify_warmup_start_delay_sec() -> float:
    try:
        delay_sec = float(settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_START_DELAY_SEC or 0.0)
    except (TypeError, ValueError):
        delay_sec = 1.0
    return max(0.0, min(60.0, delay_sec))


async def warmup_dify_external_knowledge(
    *,
    db_factory: Callable[[], Session] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    disabled_result = _dify_external_warmup_disabled_result()
    if disabled_result is not None:
        return disabled_result
    _set_dify_external_warmup_status(
        enabled=True,
        status="running",
        attempted=0,
        completed=0,
        failed=0,
        elapsed_ms=None,
    )

    try:
        knowledge_map = knowledge_scope.load_knowledge_map()
    except Exception:  # noqa: BLE001
        logger.warning("Skipping Dify external warmup: knowledge map is invalid", exc_info=True)
        return _dify_external_warmup_status_result(
            enabled=True,
            status="failed",
            reason="invalid_knowledge_map",
            started=started,
            failed=1,
        )

    knowledge_ids = knowledge_scope.resolve_warmup_knowledge_ids(knowledge_map)
    tenant_id = _resolve_dify_warmup_tenant_id()
    skip_reason = _dify_external_warmup_skip_reason(
        knowledge_ids,
        tenant_id=tenant_id,
    )
    if skip_reason is not None:
        return _dify_external_warmup_status_result(
            enabled=True,
            status="skipped",
            reason=skip_reason,
            started=started,
        )
    if not _dify_warmup_can_use_retrieval_slot():
        return _dify_external_warmup_status_result(
            enabled=True,
            status="skipped",
            reason="warmup_skipped_single_retrieval_slot",
            started=started,
        )
    _set_dify_external_warmup_status(enabled=True, status="running", attempted=len(knowledge_ids))

    factory = db_factory or SessionLocal
    account_id = (settings.DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID or "system:dify").strip()
    query = _resolve_dify_warmup_query()
    top_k = _resolve_dify_warmup_top_k()
    score_threshold = 0.0
    timeout_sec = _resolve_dify_warmup_timeout_sec()
    warmup_lease, warmup_lease_ttl_sec = await response_cache._acquire_dify_warmup_lease(
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

    try:
        for knowledge_id in knowledge_ids:
            success = await _run_dify_external_warmup_iteration(
                knowledge_id,
                factory=factory,
                tenant_id=tenant_id,
                account_id=account_id,
                query=query,
                top_k=top_k,
                score_threshold=score_threshold,
                timeout_sec=timeout_sec,
            )
            completed += int(success)
            failed += int(not success)
    finally:
        if lease_heartbeat_task is not None:
            lease_heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await lease_heartbeat_task
        await response_cache._release_distributed_dify_response_lease(warmup_lease)

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    result = {
        "enabled": True,
        "reason": "completed",
        "attempted": len(knowledge_ids),
        "completed": completed,
        "failed": failed,
        "elapsed_ms": elapsed_ms,
    }
    _set_dify_external_warmup_status(
        enabled=True,
        status="completed" if failed == 0 else "failed",
        attempted=len(knowledge_ids),
        completed=completed,
        failed=failed,
        elapsed_ms=elapsed_ms,
    )
    logger.info(
        "Dify external warmup finished attempted=%s completed=%s failed=%s elapsed_ms=%s",
        result["attempted"],
        completed,
        failed,
        elapsed_ms,
        extra={"event": "dify_external_warmup", "phase": "finished", **result},
    )
    return result


def _dify_external_warmup_disabled_result() -> dict[str, Any] | None:
    if not settings.DIFY_EXTERNAL_KNOWLEDGE_ENABLED:
        _set_dify_external_warmup_status(
            enabled=False,
            status="disabled",
            attempted=0,
            completed=0,
            failed=0,
            elapsed_ms=0,
        )
        return {
            "enabled": False,
            "reason": "external_knowledge_disabled",
            "attempted": 0,
            "completed": 0,
            "failed": 0,
        }
    if not settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_ENABLED:
        _set_dify_external_warmup_status(
            enabled=True,
            status="disabled",
            attempted=0,
            completed=0,
            failed=0,
            elapsed_ms=0,
        )
        return {
            "enabled": False,
            "reason": "warmup_disabled",
            "attempted": 0,
            "completed": 0,
            "failed": 0,
        }
    return None


def _dify_external_warmup_skip_reason(
    knowledge_ids: tuple[str, ...],
    *,
    tenant_id: UUID | None,
) -> str | None:
    if tenant_id is None:
        return "tenant_not_configured"
    if not knowledge_ids:
        return "no_knowledge_ids"
    return None


def _dify_external_warmup_status_result(
    *,
    enabled: bool,
    status: str,
    reason: str,
    started: float,
    attempted: int = 0,
    completed: int = 0,
    failed: int = 0,
) -> dict[str, Any]:
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    _set_dify_external_warmup_status(
        enabled=enabled,
        status=status,
        attempted=attempted,
        completed=completed,
        failed=failed,
        elapsed_ms=elapsed_ms,
    )
    return {
        "enabled": enabled,
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
        enabled=True,
        status="skipped",
        reason="warmup_lease_unavailable" if warmup_lease_ttl_sec is None else "warmup_locked",
        started=started,
    )
    if warmup_lease_ttl_sec is not None:
        result["retry_after_sec"] = warmup_lease_ttl_sec
    return result


def _dify_external_warmup_lease_task(
    warmup_lease: response_cache._DifyDistributedLease | None,
    warmup_lease_ttl_sec: int | None,
) -> asyncio.Task[Any] | None:
    if warmup_lease is None or warmup_lease_ttl_sec is None:
        return None
    return asyncio.create_task(
        response_cache._maintain_best_effort_dify_lease(
            warmup_lease,
            ttl_sec=warmup_lease_ttl_sec,
        )
    )


async def _run_dify_external_warmup_iteration(
    knowledge_id: str,
    *,
    factory: Callable[[], Session],
    tenant_id: UUID,
    account_id: str,
    query: str,
    top_k: int,
    score_threshold: float,
    timeout_sec: float,
) -> bool:
    item_started = time.perf_counter()
    db = None
    try:
        scope_plan = knowledge_scope.resolve_scope(knowledge_id, query=query)
        dataset_ids = _warmup_scope_dataset_ids(scope_plan)
        db = factory()
        await asyncio.wait_for(
            evidence_adapter.retrieve_dataset_citations(
                db=db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_ids=dataset_ids,
                query=query,
                top_k=top_k,
                requested_top_k=top_k,
                score_threshold=score_threshold,
                enable_kg_query_expansion=False,
                enable_kg_chunk_injection=False,
                enable_kg_chunk_boost=False,
                enable_reranker=False,
            ),
            timeout=timeout_sec,
        )
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
    finally:
        if db is not None:
            close = getattr(db, "close", None)
            if callable(close):
                close()


def _warmup_scope_dataset_ids(scope_plan: DatasetScopePlan) -> list[UUID]:
    primary_scope_enabled = settings.DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_SCOPE_ENABLED
    dataset_ids = list(scope_plan.primary_dataset_ids if primary_scope_enabled else scope_plan.dataset_ids)
    return dataset_ids or list(scope_plan.dataset_ids)


def _log_dify_external_warmup_iteration(
    knowledge_id: str,
    *,
    dataset_count: int,
    item_started: float,
    success: bool,
) -> None:
    item_elapsed_ms = round((time.perf_counter() - item_started) * 1000, 2)
    if success:
        logger.info(
            "Dify external warmup completed knowledge_id_hash=%s dataset_count=%s elapsed_ms=%s",
            common._diagnostic_value_hash(knowledge_id),
            dataset_count,
            item_elapsed_ms,
            extra={
                "event": "dify_external_warmup",
                "phase": "knowledge_completed",
                "knowledge_id_hash": common._diagnostic_value_hash(knowledge_id),
                "dataset_count": dataset_count,
                "elapsed_ms": item_elapsed_ms,
            },
        )
        return
    logger.warning(
        "Dify external warmup failed knowledge_id_hash=%s elapsed_ms=%s",
        common._diagnostic_value_hash(knowledge_id),
        item_elapsed_ms,
        exc_info=True,
        extra={
            "event": "dify_external_warmup",
            "phase": "knowledge_failed",
            "knowledge_id_hash": common._diagnostic_value_hash(knowledge_id),
            "elapsed_ms": item_elapsed_ms,
        },
    )


async def _delayed_warmup_dify_external_knowledge() -> dict[str, Any]:
    delay_sec = _resolve_dify_warmup_start_delay_sec()
    if delay_sec > 0:
        await asyncio.sleep(delay_sec)
    else:
        # Yield once so lifespan can return before any cold retrieval work runs.
        await asyncio.sleep(0)
    result = await warmup_dify_external_knowledge()
    if result.get("reason") != "warmup_locked":
        return result

    await asyncio.sleep(max(1, int(result.get("retry_after_sec") or 1)))
    return await warmup_dify_external_knowledge()


def _log_dify_warmup_task_result(task: Any) -> None:
    if isinstance(task, asyncio.Task):
        _dify_external_warmup_tasks.discard(task)
    try:
        task.result()
    except asyncio.CancelledError:
        logger.info("Dify external warmup task cancelled")
    except Exception:  # noqa: BLE001
        logger.warning("Dify external warmup task failed", exc_info=True)


def start_dify_external_knowledge_warmup(
    *,
    create_task: Callable[[Any], Any] | None = None,
) -> Any | None:
    if not settings.DIFY_EXTERNAL_KNOWLEDGE_ENABLED:
        _set_dify_external_warmup_status(enabled=False, status="disabled")
        return None
    if not settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_ENABLED:
        _set_dify_external_warmup_status(enabled=True, status="disabled")
        return None

    delay_sec = _resolve_dify_warmup_start_delay_sec()
    _set_dify_external_warmup_status(enabled=True, status="scheduled", start_delay_sec=delay_sec)
    coro = _delayed_warmup_dify_external_knowledge()
    try:
        task = create_task(coro) if create_task is not None else asyncio.create_task(coro)
    except RuntimeError:
        coro.close()
        logger.warning("Dify external warmup was not scheduled: no running event loop")
        return None
    except Exception:  # noqa: BLE001
        coro.close()
        logger.warning("Dify external warmup was not scheduled", exc_info=True)
        return None

    if isinstance(task, asyncio.Task):
        _dify_external_warmup_tasks.add(task)
    add_done_callback = getattr(task, "add_done_callback", None)
    if callable(add_done_callback):
        add_done_callback(_log_dify_warmup_task_result)
    logger.info("Dify external warmup scheduled start_delay_sec=%s", delay_sec)
    return task
