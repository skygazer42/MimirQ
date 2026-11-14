"""Keep scan transactions on one thread while queue checks await the request loop."""

import asyncio
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Literal, Protocol, TypeVar
from uuid import UUID

import anyio
from sqlalchemy.orm import Session

from app.core.async_bridge import _wait_for_worker_after_cancellation, run_blocking_in_thread
from app.models.dataset_precheck_scan import DatasetPrecheckScanRun
from app.models.dataset_profile_scan import DatasetProfileScanRun
from app.rag.core.logging import get_logger
from app.services.rag_runtime_limiter import run_blocking_call_with_managed_session
from app.tasks.queue import is_local_scan_run_active, register_local_scan_run_active, unregister_local_scan_run_active

T = TypeVar("T")
logger = get_logger(__name__)


class ScanTransaction(Protocol):
    async def run(self, operation: Callable[[Session], T]) -> T: ...

    def raise_if_cancelled(self) -> None: ...


class DatasetScanSession:
    """Own one session and executor for expiry, insert and enqueue compensation."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dataset-scan")
        self._session: Session | None = None
        self._cancelled = threading.Event()

    async def __aenter__(self) -> "DatasetScanSession":
        return self

    def raise_if_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise asyncio.CancelledError

    def _run(self, operation: Callable[[Session], T]) -> T:
        self.raise_if_cancelled()
        if self._session is None:
            self._session = self._session_factory()
        return operation(self._session)

    async def run(self, operation: Callable[[Session], T]) -> T:
        self.raise_if_cancelled()
        work = asyncio.get_running_loop().run_in_executor(self._executor, copy_context().run, self._run, operation)
        try:
            return await asyncio.shield(work)
        except asyncio.CancelledError:
            self._cancelled.set()
            # An in-flight SQL call cannot be stopped; settle it before closing its session.
            with anyio.CancelScope(shield=True):
                while not work.done():
                    try:
                        await asyncio.shield(work)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
            if work.done() and not work.cancelled():
                error = work.exception()
                if error is not None and not isinstance(error, asyncio.CancelledError):
                    logger.warning(
                        "Dataset scan operation failed during cancellation",
                        exc_info=(type(error), error, error.__traceback__),
                    )
            raise

    def _close(self) -> None:
        if self._session is not None:
            self._session.close()

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self._cancelled.set()

        async def close_session() -> None:
            await asyncio.get_running_loop().run_in_executor(self._executor, self._close)

        close_task = asyncio.create_task(close_session())
        try:
            with anyio.fail_after(5.0, shield=True):
                try:
                    await asyncio.shield(close_task)
                except asyncio.CancelledError as cancel_error:
                    error = await _wait_for_worker_after_cancellation(close_task)
                    if error is not None:
                        raise error from cancel_error
                    raise
        except Exception:
            if exc_type is None:
                raise
            logger.warning("Dataset scan session close failed", exc_info=True)
        finally:
            await run_blocking_in_thread(self._executor.shutdown, wait=True)


class CurrentThreadScanSession:
    """Adapt the transaction already owned by a synchronous dataset delete route."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def run(self, operation: Callable[[Session], T]) -> T:
        return operation(self._session)

    def raise_if_cancelled(self) -> None:
        pass


def fail_unhanded_scan_run(
    db: Session,
    *,
    kind: Literal["profile", "precheck"],
    tenant_id: UUID,
    dataset_id: UUID,
    scan_run_id: UUID,
    error_message: str,
) -> None:
    model = DatasetProfileScanRun if kind == "profile" else DatasetPrecheckScanRun
    query = db.query(model).filter(
        model.tenant_id == tenant_id, model.dataset_id == dataset_id, model.id == scan_run_id
    )
    row = query.one()
    if row.status != "pending":
        return
    failed_at = datetime.now(UTC)
    updated = query.filter(model.status == "pending").update(
        {
            model.status: "failed",
            model.error_message: error_message[:200],
            model.finished_at: failed_at,
            model.updated_at: failed_at,
        },
        synchronize_session=False,
    )
    if updated:
        db.commit()


def record_unknown_scan_handoff(
    db: Session,
    *,
    kind: Literal["profile", "precheck"],
    tenant_id: UUID,
    dataset_id: UUID,
    scan_run_id: UUID,
    error_message: str,
) -> None:
    model = DatasetProfileScanRun if kind == "profile" else DatasetPrecheckScanRun
    query = db.query(model).filter(
        model.tenant_id == tenant_id, model.dataset_id == dataset_id, model.id == scan_run_id
    )
    row = query.one()
    if row.status != "pending":
        return
    updated = query.filter(model.status == "pending").update(
        {model.error_message: f"task_enqueue_unknown: {error_message[:160]}", model.updated_at: datetime.now(UTC)},
        synchronize_session=False,
    )
    if updated:
        db.commit()


async def persist_scan_handoff_update(update: Callable[[Session], None]) -> None:
    worker = asyncio.create_task(run_blocking_call_with_managed_session(update, request_db=None))
    try:
        await asyncio.shield(worker)
    except asyncio.CancelledError:
        error = await _wait_for_worker_after_cancellation(worker)
        if error is not None:
            logger.error("Cancelled scan handoff update failed", exc_info=(type(error), error, error.__traceback__))
        raise


async def settle_scan_enqueue(
    worker: asyncio.Task[str | None],
    *,
    kind: Literal["profile", "precheck"],
    tenant_id: UUID,
    dataset_id: UUID,
    scan_run_id: UUID,
) -> str | None:
    from app.tasks.queue import TaskEnqueueRejectedError

    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        error = await _wait_for_worker_after_cancellation(worker)
        if error is None and not worker.cancelled():
            if worker.result() is not None:
                raise
            update = partial(
                fail_unhanded_scan_run,
                kind=kind,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                scan_run_id=scan_run_id,
                error_message="scan_request_cancelled_before_local_handoff",
            )
        elif isinstance(error, TaskEnqueueRejectedError):
            update = partial(
                fail_unhanded_scan_run,
                kind=kind,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                scan_run_id=scan_run_id,
                error_message=f"task_enqueue_failed: {error}",
            )
        else:
            message = str(error) if error is not None else "enqueue task cancelled before receipt"
            update = partial(
                record_unknown_scan_handoff,
                kind=kind,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                scan_run_id=scan_run_id,
                error_message=message,
            )
        cleanup = asyncio.create_task(persist_scan_handoff_update(update))
        cleanup_error = await _wait_for_worker_after_cancellation(cleanup)
        if cleanup_error is not None:
            logger.error(
                "Cancelled scan enqueue recovery failed",
                exc_info=(type(cleanup_error), cleanup_error, cleanup_error.__traceback__),
            )
        raise
    except Exception as error:
        if isinstance(error, TaskEnqueueRejectedError):
            update = partial(
                fail_unhanded_scan_run,
                kind=kind,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                scan_run_id=scan_run_id,
                error_message=f"task_enqueue_failed: {error}",
            )
        else:
            update = partial(
                record_unknown_scan_handoff,
                kind=kind,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                scan_run_id=scan_run_id,
                error_message=str(error),
            )
        try:
            await persist_scan_handoff_update(update)
        except Exception:
            logger.warning("Failed to persist scan enqueue outcome: scan_run_id=%s", scan_run_id, exc_info=True)
        raise


def submit_local_scan_run(
    operation: Callable[[], None],
    *,
    kind: Literal["profile", "precheck"],
    tenant_id: UUID,
    dataset_id: UUID,
    scan_run_id: UUID,
) -> None:
    register_local_scan_run_active(kind=kind, tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id)
    try:
        worker = asyncio.get_running_loop().run_in_executor(None, copy_context().run, operation)
    except BaseException:
        unregister_local_scan_run_active(kind=kind, tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id)
        raise

    def finished(future: asyncio.Future[None]) -> None:
        try:
            if not future.cancelled():
                error = future.exception()
                if error is not None:
                    logger.error("Local dataset scan failed", exc_info=(type(error), error, error.__traceback__))
        finally:
            unregister_local_scan_run_active(
                kind=kind, tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id
            )

    worker.add_done_callback(finished)


_PENDING_STALE_AFTER = timedelta(minutes=15)
_RUNNING_STALE_AFTER = timedelta(hours=2)
_PENDING_HARD_STALE_AFTER = timedelta(hours=2)
_RUNNING_HARD_STALE_AFTER = timedelta(hours=24)


@dataclass(frozen=True)
class _ScanRunState:
    id: UUID
    status: str
    created_at: datetime | None
    updated_at: datetime | None


async def expire_stale_scan_runs(
    transaction: ScanTransaction,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    now: datetime,
    kind: Literal["profile", "precheck"],
    queue_enabled: bool,
    get_job_status: Callable[[str], Awaitable[str | None]],
) -> int:
    model = DatasetProfileScanRun if kind == "profile" else DatasetPrecheckScanRun

    def candidates(db: Session) -> list[_ScanRunState]:
        rows = (
            db.query(model)
            .filter(
                model.tenant_id == tenant_id, model.dataset_id == dataset_id, model.status.in_(["pending", "running"])
            )
            .all()
        )
        return [_ScanRunState(row.id, row.status, row.created_at, row.updated_at) for row in rows]

    expired: dict[UUID, _ScanRunState] = {}
    for state in await transaction.run(candidates):
        status = state.status.strip().lower()
        reference = state.updated_at or state.created_at
        if reference is None or status not in {"pending", "running"}:
            continue
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=now.tzinfo)
        stale_after = _PENDING_STALE_AFTER if status == "pending" else _RUNNING_STALE_AFTER
        if reference + stale_after > now:
            continue
        if is_local_scan_run_active(kind=kind, tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=state.id):
            continue
        if queue_enabled:
            try:
                job_status = await get_job_status(f"dataset_{kind}_scan:{tenant_id}:{dataset_id}:{state.id}")
            except Exception as exc:
                logger.warning(
                    "Could not verify stale dataset %s job %s: %s", kind, state.id, str(exc)[:160], exc_info=True
                )
                hard_after = _PENDING_HARD_STALE_AFTER if status == "pending" else _RUNNING_HARD_STALE_AFTER
                if reference + hard_after > now:
                    continue
                job_status = None
            if job_status in {"deferred", "queued", "in_progress"}:
                continue
        expired[state.id] = state
    if not expired:
        return 0

    def apply_expiry(db: Session) -> int:
        rows = (
            db.query(model)
            .filter(model.tenant_id == tenant_id, model.dataset_id == dataset_id, model.id.in_(expired))
            .populate_existing()
            .all()
        )
        transaction.raise_if_cancelled()
        count = 0
        for row in rows:
            state = expired.get(row.id)
            if state is None or row.status != state.status or row.updated_at != state.updated_at:
                continue
            row.status = "failed"
            row.error_message = (
                "stale_running_scan_replaced"
                if state.status.strip().lower() == "running"
                else "stale_pending_scan_replaced"
            )
            row.finished_at = row.updated_at = now
            count += 1
        if count:
            transaction.raise_if_cancelled()
            db.flush()
        return count

    return await transaction.run(apply_expiry)
