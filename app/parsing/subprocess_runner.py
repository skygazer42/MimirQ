import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.parsing.errors import ParsingError, classify_parser_subprocess_error
from app.rag.core.logging import get_logger

logger = get_logger("parsing.subprocess_runner")

DisconnectCheck = Callable[[], Awaitable[bool]]
CancelCheck = Callable[[], Awaitable[bool]]


class SubprocessWorkerError(RuntimeError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None, log_tail: str = "") -> None:
        super().__init__(message)
        self.details = details or {}
        self.log_tail = log_tail


class SubprocessCancelledError(RuntimeError):
    """Raised when we explicitly cancel a running subprocess."""


SubprocessCancelled = SubprocessCancelledError


def _start_subprocess_worker_fallback(
    *,
    payload_path: Path,
    result_path: Path,
    log_file: Any,
) -> subprocess.Popen[bytes]:
    # Fixed internal worker entrypoint; only generated payload/result paths vary.
    return subprocess.Popen(  # noqa: S603  # NOSONAR
        [
            sys.executable,
            "-m",
            "app.parsing.subprocess_worker",
            str(payload_path),
            str(result_path),
        ],
        stdout=log_file,
        stderr=log_file,
        start_new_session=True,
    )


def _get_subprocess_workdir(*, _tenant_id: UUID) -> Path:
    root = Path(getattr(settings, "UPLOAD_DIR", "uploads"))
    return (root / str(_tenant_id) / ".subprocess").resolve(strict=False)


def _process_finished(process: Any) -> bool:
    return getattr(process, "returncode", None) is not None


def _process_pid(process: Any) -> int | None:
    return getattr(process, "pid", None)


def _terminate_process(process: Any) -> None:
    if os.name == "posix":
        os.killpg(process.pid, signal.SIGTERM)
        return
    terminate = getattr(process, "terminate", None)
    if callable(terminate):  # pragma: no cover
        terminate()


def _kill_process(process: Any) -> None:
    if os.name == "posix":
        os.killpg(process.pid, signal.SIGKILL)
        return
    kill = getattr(process, "kill", None)
    if callable(kill):  # pragma: no cover
        kill()


async def _wait_for_process_exit(process: Any, *, timeout: float | None = None) -> None:
    if isinstance(process, asyncio.subprocess.Process):
        if timeout is None:
            await process.wait()
            return
        await asyncio.wait_for(process.wait(), timeout=timeout)
        return

    if timeout is None:
        await asyncio.to_thread(process.wait)
        return
    await asyncio.to_thread(process.wait, timeout)


def _log_subprocess_signal_failure(*, action: str, pid: int, exc: Exception) -> None:
    logger.warning("Failed to %s subprocess %s: %s", action, pid, str(exc)[:200])


def _log_subprocess_wait_timeout(*, pid: int, exc: Exception) -> None:
    if isinstance(exc, subprocess.TimeoutExpired):
        logger.debug("Ignoring subprocess timeout while terminating pid=%s", pid)
    elif isinstance(exc, asyncio.TimeoutError):
        logger.debug("Ignoring async timeout while terminating pid=%s", pid)


async def _wait_for_graceful_exit(process: Any, *, pid: int, grace_sec: float) -> bool:
    try:
        await _wait_for_process_exit(process, timeout=grace_sec)
        return True
    except (subprocess.TimeoutExpired, asyncio.TimeoutError) as exc:
        _log_subprocess_wait_timeout(pid=pid, exc=exc)
        return False
    except Exception:
        return True


async def _terminate_process_group(process: Any, *, grace_sec: float = 2.0) -> None:
    # The default asyncio event loop on Windows (SelectorEventLoop) does not support
    # asyncio subprocess APIs. In that case we fall back to `subprocess.Popen` and
    # this helper must handle both process types.
    if _process_finished(process):
        return

    pid = _process_pid(process)
    if pid is None:
        return

    try:
        _terminate_process(process)
    except ProcessLookupError:
        return
    except Exception as exc:  # noqa: BLE001
        _log_subprocess_signal_failure(action="terminate", pid=pid, exc=exc)

    if await _wait_for_graceful_exit(process, pid=pid, grace_sec=grace_sec):
        return

    try:
        _kill_process(process)
    except ProcessLookupError:
        return
    except Exception as exc:  # noqa: BLE001
        _log_subprocess_signal_failure(action="kill", pid=pid, exc=exc)

    try:
        await _wait_for_process_exit(process)
    except Exception:
        return


def _read_log_tail(path: Path, *, max_bytes: int = 16_000) -> str:
    try:
        if not path.exists():
            return ""
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(-max_bytes, os.SEEK_END)
            raw = f.read()
        return raw.decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


def _write_payload_file(*, payload_path: Path, payload: dict[str, Any]) -> None:
    payload_json = json.dumps(payload, ensure_ascii=False, default=str)
    max_payload_bytes = int(getattr(settings, "SUBPROCESS_PAYLOAD_MAX_BYTES", 0) or 0)
    if max_payload_bytes > 0:
        payload_bytes = payload_json.encode("utf-8", errors="ignore")
        if len(payload_bytes) > max_payload_bytes:
            raise SubprocessWorkerError(
                "payload_too_large",
                details={
                    "max_bytes": int(max_payload_bytes),
                    "actual_bytes": int(len(payload_bytes)),
                },
            )
        payload_path.write_bytes(payload_bytes)
        return
    payload_path.write_text(payload_json, encoding="utf-8")


async def _spawn_subprocess_worker(
    *,
    payload_path: Path,
    result_path: Path,
    log_file: Any,
) -> Any:
    try:
        # Fixed internal worker entrypoint; no caller-provided executable is accepted.
        return await asyncio.create_subprocess_exec(  # NOSONAR
            sys.executable,
            "-m",
            "app.parsing.subprocess_worker",
            str(payload_path),
            str(result_path),
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )
    except NotImplementedError:
        # WindowsSelectorEventLoopPolicy cannot spawn asyncio subprocesses.
        logger.warning(
            "asyncio subprocess API not available on this event loop (%s); falling back to subprocess.Popen",
            asyncio.get_running_loop().__class__.__name__,
        )
        return _start_subprocess_worker_fallback(
            payload_path=payload_path,
            result_path=result_path,
            log_file=log_file,
        )


async def _run_async_check(check: DisconnectCheck | CancelCheck | None, *, label: str) -> bool:
    if check is None:
        return False
    try:
        return bool(await check())
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.debug("%s failed (ignored): %s", label, str(exc)[:200])
        return False


def _worker_log_size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except Exception:
        return 0


def _enforce_worker_log_limit(*, log_path: Path, max_log_bytes: int) -> None:
    if max_log_bytes <= 0:
        return
    log_size = _worker_log_size(log_path)
    if log_size <= max_log_bytes:
        return
    raise SubprocessWorkerError(
        "worker_log_too_large",
        details={"max_bytes": int(max_log_bytes), "actual_bytes": int(log_size)},
        log_tail=_read_log_tail(log_path),
    )


async def _monitor_subprocess_worker(
    *,
    process: Any,
    disconnect_check: DisconnectCheck | None,
    cancel_check: CancelCheck | None,
    timeout_sec: float | None,
    poll_interval_sec: float,
    log_path: Path,
) -> None:
    start = time.monotonic()
    max_log_bytes = int(getattr(settings, "SUBPROCESS_LOG_MAX_BYTES", 0) or 0)
    while True:
        poll = getattr(process, "poll", None)
        if callable(poll):
            poll()
        if _process_finished(process):
            return
        try:
            if await _run_async_check(disconnect_check, label="disconnect_check"):
                await _terminate_process_group(process)
                raise SubprocessCancelled("client_disconnected")
            if await _run_async_check(cancel_check, label="cancel_check"):
                await _terminate_process_group(process)
                raise SubprocessCancelled("cancel_requested")
            _enforce_worker_log_limit(log_path=log_path, max_log_bytes=max_log_bytes)
            if timeout_sec is not None and (time.monotonic() - start) > timeout_sec:
                await _terminate_process_group(process)
                raise SubprocessWorkerError("worker_timeout", log_tail=_read_log_tail(log_path))
        except asyncio.CancelledError:
            await _terminate_process_group(process)
            raise

        await asyncio.sleep(poll_interval_sec)


def _load_worker_result(*, process: Any, result_path: Path, log_path: Path) -> dict[str, Any]:
    if not result_path.exists():
        raise SubprocessWorkerError(
            f"worker_did_not_write_result (exit_code={getattr(process, 'returncode', None)})",
            log_tail=_read_log_tail(log_path),
        )

    max_result_bytes = int(getattr(settings, "SUBPROCESS_RESULT_MAX_BYTES", 0) or 0)
    if max_result_bytes > 0:
        try:
            size = int(result_path.stat().st_size)
        except Exception:
            size = 0
        if size > int(max_result_bytes):
            raise SubprocessWorkerError(
                "worker_result_too_large",
                details={
                    "max_bytes": int(max_result_bytes),
                    "actual_bytes": int(size),
                },
                log_tail=_read_log_tail(log_path),
            )

    raw = result_path.read_text(encoding="utf-8", errors="ignore")
    parsed = json.loads(raw or "{}")
    if not isinstance(parsed, dict):
        raise SubprocessWorkerError("worker_invalid_result_format", log_tail=_read_log_tail(log_path))
    if parsed.get("ok") is True:
        data = parsed.get("data")
        if isinstance(data, dict):
            return data
        raise SubprocessWorkerError("worker_ok_without_data", log_tail=_read_log_tail(log_path))

    err = parsed.get("error") if isinstance(parsed.get("error"), dict) else {}
    msg = str(err.get("message") or "worker_failed")
    raise SubprocessWorkerError(msg, details=err, log_tail=_read_log_tail(log_path))


def _cleanup_worker_files(*, log_file: Any, payload_path: Path, result_path: Path, log_path: Path) -> None:
    try:
        if log_file is not None:
            log_file.close()
    except (OSError, ValueError) as exc:
        logger.debug("Ignoring non-critical subprocess log close failure: %s", exc)

    for path in (payload_path, result_path, log_path):
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.debug("Ignoring non-critical subprocess cleanup failure: %s", exc)


async def run_subprocess_worker(
    *,
    tenant_id: UUID,
    payload: dict[str, Any],
    disconnect_check: DisconnectCheck | None = None,
    cancel_check: CancelCheck | None = None,
    timeout_sec: float | None = None,
    poll_interval_sec: float = 0.2,
) -> dict[str, Any]:
    """
    Run the parsing worker in a separate Python process so we can truly cancel it.

    Cancellation sources:
    - disconnect_check(): usually FastAPI request.is_disconnected
    - cancel_check(): e.g. document status changed to "cancelled"
    - asyncio.CancelledError(): upstream task/job aborted (e.g., arq Job.abort)
    """
    workdir = _get_subprocess_workdir(_tenant_id=tenant_id)
    workdir.mkdir(parents=True, exist_ok=True)

    run_id = uuid.uuid4().hex
    payload_path = workdir / f"{run_id}.payload.json"
    result_path = workdir / f"{run_id}.result.json"
    log_path = workdir / f"{run_id}.log"

    _write_payload_file(payload_path=payload_path, payload=payload)

    log_file = None
    process: Any = None
    try:
        log_file = log_path.open("wb")
        process = await _spawn_subprocess_worker(
            payload_path=payload_path,
            result_path=result_path,
            log_file=log_file,
        )
        await _monitor_subprocess_worker(
            process=process,
            disconnect_check=disconnect_check,
            cancel_check=cancel_check,
            timeout_sec=timeout_sec,
            poll_interval_sec=poll_interval_sec,
            log_path=log_path,
        )
        return _load_worker_result(process=process, result_path=result_path, log_path=log_path)
    except asyncio.CancelledError:
        if process is not None:
            await _terminate_process_group(process)
        raise
    finally:
        _cleanup_worker_files(
            log_file=log_file,
            payload_path=payload_path,
            result_path=result_path,
            log_path=log_path,
        )


def _compute_retry_delay_sec(*, attempt: int, base_delay_sec: float, max_delay_sec: float) -> float:
    """
    Exponential backoff with a hard cap.

    attempt: 1 for the first retry.
    """
    try:
        a = int(attempt)
    except Exception:
        a = 1
    a = max(1, a)
    base = float(base_delay_sec or 0.0)
    cap = float(max_delay_sec or 0.0)
    delay = base * (2 ** (a - 1))
    if cap > 0:
        delay = min(delay, cap)
    if delay < 0:
        delay = 0.0
    return float(delay)


async def run_parser_subprocess(
    *,
    tenant_id: UUID,
    payload: dict[str, Any],
    disconnect_check: DisconnectCheck | None = None,
    cancel_check: CancelCheck | None = None,
    timeout_sec: float | None = None,
    poll_interval_sec: float = 0.2,
    max_attempts: int = 2,
    base_delay_sec: float = 0.5,
    max_delay_sec: float = 5.0,
) -> dict[str, Any]:
    """
    Wrapper around `run_subprocess_worker` with:
    - typed error classification (timeout/unsupported/internal)
    - bounded retries + exponential backoff for retryable failures
    """
    attempts = max(1, int(max_attempts) if max_attempts is not None else 1)
    last_typed: ParsingError | None = None

    for attempt in range(1, attempts + 1):
        try:
            return await run_subprocess_worker(
                tenant_id=tenant_id,
                payload=payload,
                disconnect_check=disconnect_check,
                cancel_check=cancel_check,
                timeout_sec=timeout_sec,
                poll_interval_sec=poll_interval_sec,
            )
        except SubprocessCancelled:
            raise
        except asyncio.CancelledError:
            raise
        except SubprocessWorkerError as exc:
            typed = classify_parser_subprocess_error(exc)
            last_typed = typed

            if not bool(getattr(typed, "retryable", False)) or attempt >= attempts:
                raise typed from exc

            delay = _compute_retry_delay_sec(
                attempt=attempt,
                base_delay_sec=float(base_delay_sec or 0.0),
                max_delay_sec=float(max_delay_sec or 0.0),
            )
            logger.warning(
                "Parser subprocess failed (attempt %s/%s): %s; retrying in %.2fs",
                attempt,
                attempts,
                str(exc)[:200],
                delay,
            )
            await asyncio.sleep(delay)

    # Defensive: should have returned or raised.
    if last_typed is not None:
        raise last_typed
    raise ParsingError("worker_failed", code="internal", retryable=True)
