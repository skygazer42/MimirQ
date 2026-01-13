import asyncio
import json
import os
import signal
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from uuid import UUID

from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("parsing.subprocess_runner")

DisconnectCheck = Callable[[], Awaitable[bool]]
CancelCheck = Callable[[], Awaitable[bool]]


class SubprocessWorkerError(RuntimeError):
    def __init__(self, message: str, *, details: Optional[dict[str, Any]] = None, log_tail: str = "") -> None:
        super().__init__(message)
        self.details = details or {}
        self.log_tail = log_tail


class SubprocessCancelled(RuntimeError):
    """Raised when we explicitly cancel a running subprocess."""


def _get_subprocess_workdir(*, tenant_id: UUID) -> Path:
    root = Path(getattr(settings, "UPLOAD_DIR", "uploads"))
    return (root / str(tenant_id) / ".subprocess").resolve(strict=False)


async def _terminate_process_group(process: asyncio.subprocess.Process, *, grace_sec: float = 2.0) -> None:
    if process.returncode is not None:
        return

    pid = process.pid
    if pid is None:
        return

    try:
        if os.name == "posix":
            os.killpg(pid, signal.SIGTERM)
        else:  # pragma: no cover
            process.terminate()
    except ProcessLookupError:
        return
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to terminate subprocess %s: %s", pid, str(exc)[:200])

    try:
        await asyncio.wait_for(process.wait(), timeout=grace_sec)
        return
    except asyncio.TimeoutError:
        pass
    except Exception:
        return

    try:
        if os.name == "posix":
            os.killpg(pid, signal.SIGKILL)
        else:  # pragma: no cover
            process.kill()
    except ProcessLookupError:
        return
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to kill subprocess %s: %s", pid, str(exc)[:200])

    try:
        await process.wait()
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
    workdir = _get_subprocess_workdir(tenant_id=tenant_id)
    workdir.mkdir(parents=True, exist_ok=True)

    run_id = uuid.uuid4().hex
    payload_path = workdir / f"{run_id}.payload.json"
    result_path = workdir / f"{run_id}.result.json"
    log_path = workdir / f"{run_id}.log"

    payload_path.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")

    log_file = None
    process: asyncio.subprocess.Process | None = None
    try:
        log_file = log_path.open("wb")
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

        start = time.monotonic()
        while process.returncode is None:
            try:
                if disconnect_check is not None and await disconnect_check():
                    await _terminate_process_group(process)
                    raise SubprocessCancelled("client_disconnected")
                if cancel_check is not None and await cancel_check():
                    await _terminate_process_group(process)
                    raise SubprocessCancelled("cancel_requested")
                if timeout_sec is not None and (time.monotonic() - start) > timeout_sec:
                    await _terminate_process_group(process)
                    raise SubprocessWorkerError("worker_timeout", log_tail=_read_log_tail(log_path))
            except asyncio.CancelledError:
                await _terminate_process_group(process)
                raise

            await asyncio.sleep(poll_interval_sec)

        if not result_path.exists():
            raise SubprocessWorkerError(
                f"worker_did_not_write_result (exit_code={process.returncode})",
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
        except Exception:
            pass

        # Best-effort cleanup.
        for p in (payload_path, result_path, log_path):
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass

