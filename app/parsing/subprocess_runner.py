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
    return subprocess.Popen(  # noqa: S603
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


async def _terminate_process_group(process: Any, *, grace_sec: float = 2.0) -> None:
    # The default asyncio event loop on Windows (SelectorEventLoop) does not support
    # asyncio subprocess APIs. In that case we fall back to `subprocess.Popen` and
    # this helper must handle both process types.
    if getattr(process, "returncode", None) is not None:
        return

    pid = getattr(process, "pid", None)
    if pid is None:
        return

    try:
        if os.name == "posix":
            os.killpg(pid, signal.SIGTERM)
        else:  # pragma: no cover
            terminate = getattr(process, "terminate", None)
            if callable(terminate):
                terminate()
    except ProcessLookupError:
        return
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to terminate subprocess %s: %s", pid, str(exc)[:200])

    try:
        if isinstance(process, asyncio.subprocess.Process):
            await asyncio.wait_for(process.wait(), timeout=grace_sec)
        else:  # Popen-like
            await asyncio.to_thread(process.wait, grace_sec)
        return
    except subprocess.TimeoutExpired:
        logger.debug("Ignoring subprocess timeout while terminating pid=%s", pid)
    except asyncio.TimeoutError:
        logger.debug("Ignoring async timeout while terminating pid=%s", pid)
    except Exception:
        return

    try:
        if os.name == "posix":
            os.killpg(pid, signal.SIGKILL)
        else:  # pragma: no cover
            kill = getattr(process, "kill", None)
            if callable(kill):
                kill()
    except ProcessLookupError:
        return
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to kill subprocess %s: %s", pid, str(exc)[:200])

    try:
        if isinstance(process, asyncio.subprocess.Process):
            await process.wait()
        else:  # Popen-like
            await asyncio.to_thread(process.wait)
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
    else:
        payload_path.write_text(payload_json, encoding="utf-8")

    log_file = None
    process: Any = None
    try:
        log_file = log_path.open("wb")
        try:
            process = await asyncio.create_subprocess_exec(
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
            process = _start_subprocess_worker_fallback(
                payload_path=payload_path,
                result_path=result_path,
                log_file=log_file,
            )

        start = time.monotonic()
        max_log_bytes = int(getattr(settings, "SUBPROCESS_LOG_MAX_BYTES", 0) or 0)
        while True:
            poll = getattr(process, "poll", None)
            if callable(poll):
                poll()
            if getattr(process, "returncode", None) is not None:
                break
            try:
                disconnected = False
                if disconnect_check is not None:
                    try:
                        disconnected = bool(await disconnect_check())
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("disconnect_check failed (ignored): %s", str(exc)[:200])
                        disconnected = False

                if disconnected:
                    await _terminate_process_group(process)
                    raise SubprocessCancelled("client_disconnected")

                cancel_requested = False
                if cancel_check is not None:
                    try:
                        cancel_requested = bool(await cancel_check())
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("cancel_check failed (ignored): %s", str(exc)[:200])
                        cancel_requested = False

                if cancel_requested:
                    await _terminate_process_group(process)
                    raise SubprocessCancelled("cancel_requested")
                if max_log_bytes > 0:
                    try:
                        log_size = int(log_path.stat().st_size)
                    except Exception:
                        log_size = 0
                    if log_size > max_log_bytes:
                        await _terminate_process_group(process)
                        raise SubprocessWorkerError(
                            "worker_log_too_large",
                            details={"max_bytes": int(max_log_bytes), "actual_bytes": int(log_size)},
                            log_tail=_read_log_tail(log_path),
                        )
                if timeout_sec is not None and (time.monotonic() - start) > timeout_sec:
                    await _terminate_process_group(process)
                    raise SubprocessWorkerError("worker_timeout", log_tail=_read_log_tail(log_path))
            except asyncio.CancelledError:
                await _terminate_process_group(process)
                raise

            await asyncio.sleep(poll_interval_sec)

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
    finally:
        try:
            if log_file is not None:
                log_file.close()
        except (OSError, ValueError) as exc:
            logger.debug("Ignoring non-critical subprocess log close failure: %s", exc)

        # Best-effort cleanup.
        for p in (payload_path, result_path, log_path):
            try:
                p.unlink(missing_ok=True)
            except OSError as exc:
                logger.debug("Ignoring non-critical subprocess cleanup failure: %s", exc)


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
