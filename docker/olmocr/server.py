
import asyncio
import importlib.util
import os
import shlex
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated, Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile

app = FastAPI(title="mimirq-olmocr", version="0.1.0")


def _get_int_env(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


_MAX_CONCURRENT_JOBS = max(1, _get_int_env("OLMOCR_MAX_CONCURRENT_JOBS", 1))
_PIPELINE_WORKERS = max(1, _get_int_env("OLMOCR_PIPELINE_WORKERS", 1))
_PIPELINE_MAX_CONCURRENT_REQUESTS = max(1, _get_int_env("OLMOCR_PIPELINE_MAX_CONCURRENT_REQUESTS", 32))
_PIPELINE_TIMEOUT_SEC = max(30, _get_int_env("OLMOCR_PIPELINE_TIMEOUT_SEC", 1800))
_LOG_TAIL_BYTES = max(8_000, _get_int_env("OLMOCR_LOG_TAIL_BYTES", 24_000))
_ERROR_TAIL_CHARS = max(2_000, _get_int_env("OLMOCR_ERROR_TAIL_CHARS", 6_000))

_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_JOBS)


def _get_float_env(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _optional_env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _gpu_free_memory_gib() -> tuple[float | None, str | None]:
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception as exc:
        return None, str(exc)[:200]

    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip()
        return None, message[:200] or f"nvidia-smi exited {proc.returncode}"

    values: list[float] = []
    for line in (proc.stdout or "").splitlines():
        raw = line.strip().split(",", 1)[0].strip()
        if not raw:
            continue
        try:
            values.append(float(raw) / 1024.0)
        except ValueError:
            continue
    if not values:
        return None, "nvidia-smi returned no parseable memory rows"
    return round(max(values), 2), None


def _runtime_status() -> dict[str, Any]:
    server_url = _optional_env("OLMOCR_SERVER_URL")
    if server_url:
        return {
            "ok": True,
            "mode": "external",
            "server_url_configured": True,
            "vllm_available": None,
            "reason": None,
        }

    vllm_available = _module_available("vllm")
    status: dict[str, Any] = {
        "ok": False,
        "mode": "local_vllm",
        "server_url_configured": False,
        "vllm_available": vllm_available,
        "reason": None,
    }
    if not vllm_available:
        status["reason"] = "vllm_unavailable"
        return status

    min_free_gib = max(0.0, _get_float_env("OLMOCR_MIN_FREE_GPU_GIB", 10.0))
    free_gib, free_error = _gpu_free_memory_gib()
    status["gpu_free_gib"] = free_gib
    status["min_free_gpu_gib"] = min_free_gib
    if free_error:
        status["gpu_free_error"] = free_error
    if min_free_gib > 0.0:
        if free_gib is None:
            status["reason"] = "gpu_memory_unknown"
            return status
        if free_gib < min_free_gib:
            status["reason"] = "insufficient_gpu_memory"
            return status

    status["ok"] = True
    status["reason"] = None
    return status


async def _terminate_process_group(process: asyncio.subprocess.Process, *, grace_sec: float = 3.0) -> None:
    if process.returncode is not None:
        return
    pid = process.pid
    if pid is None:
        return

    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        try:
            process.terminate()
        except Exception:
            return

    try:
        await asyncio.wait_for(process.wait(), timeout=grace_sec)
        return
    except asyncio.TimeoutError:
        pass
    except Exception:
        return

    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except Exception:
        try:
            process.kill()
        except Exception:
            return

    try:
        await process.wait()
    except Exception:
        return


def _pick_markdown_path(workspace: Path) -> Optional[Path]:
    default = workspace / "markdown" / "input.md"
    if default.exists():
        return default
    candidates = sorted((workspace / "markdown").rglob("*.md")) if (workspace / "markdown").exists() else []
    return candidates[0] if candidates else None


def _append_optional_arg(cmd: list[str], env_name: str, flag: str) -> None:
    value = _optional_env(env_name)
    if value:
        cmd.extend([flag, value])


def _build_pipeline_command(*, workspace: Path, input_name: str) -> list[str]:
    server_url = _optional_env("OLMOCR_SERVER_URL")
    api_key = _optional_env("OLMOCR_API_KEY")
    model = _optional_env("OLMOCR_MODEL")

    cmd: list[str] = [
        "python3",
        "-m",
        "olmocr.pipeline",
        str(workspace),
        "--markdown",
        "--workers",
        str(_PIPELINE_WORKERS),
        "--max_concurrent_requests",
        str(_PIPELINE_MAX_CONCURRENT_REQUESTS),
        "--pdfs",
        input_name,
    ]

    # Optional external OpenAI-compatible server mode.
    if server_url:
        cmd.extend(["--server", server_url])
        if api_key:
            cmd.extend(["--api_key", api_key])
        if model:
            cmd.extend(["--model", model])
    elif model:
        # Internal vLLM mode ignores this value later, but passing it is harmless.
        cmd.extend(["--model", model])

    _append_optional_arg(cmd, "OLMOCR_GPU_MEMORY_UTILIZATION", "--gpu-memory-utilization")
    _append_optional_arg(cmd, "OLMOCR_MAX_MODEL_LEN", "--max_model_len")
    _append_optional_arg(cmd, "OLMOCR_MAX_SERVER_READY_TIMEOUT", "--max_server_ready_timeout")
    _append_optional_arg(cmd, "OLMOCR_TENSOR_PARALLEL_SIZE", "--tensor-parallel-size")
    _append_optional_arg(cmd, "OLMOCR_DATA_PARALLEL_SIZE", "--data-parallel-size")
    _append_optional_arg(cmd, "OLMOCR_VLLM_PORT", "--port")

    extra_args = _optional_env("OLMOCR_EXTRA_ARGS")
    if extra_args:
        cmd.extend(shlex.split(extra_args))

    return cmd


async def _run_pipeline(
    *,
    request: Request,
    workspace: Path,
    input_name: str,
) -> tuple[int, str]:
    cmd = _build_pipeline_command(workspace=workspace, input_name=input_name)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(workspace),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )

    log_tail = bytearray()
    try:
        while True:
            if await request.is_disconnected():
                await _terminate_process_group(process)
                raise HTTPException(status_code=499, detail="client_disconnected")

            if process.stdout is None:
                break

            try:
                chunk = await asyncio.wait_for(process.stdout.read(4096), timeout=0.2)
            except asyncio.TimeoutError:
                chunk = b""

            if chunk:
                log_tail.extend(chunk)
                if len(log_tail) > _LOG_TAIL_BYTES:
                    del log_tail[: len(log_tail) - _LOG_TAIL_BYTES]

            if process.returncode is not None:
                break

            await asyncio.sleep(0.05)

        try:
            await asyncio.wait_for(process.wait(), timeout=2.0)
        except Exception:
            pass

        return int(process.returncode or 0), log_tail.decode("utf-8", errors="ignore").strip()
    finally:
        try:
            if process.returncode is None:
                await _terminate_process_group(process)
        except Exception:
            pass


@app.get("/health")
def health() -> dict[str, Any]:
    return _runtime_status()


@app.post(
    "/convert",
    responses={
        400: {"description": "Invalid or empty upload"},
        499: {"description": "Client disconnected"},
        500: {"description": "OLMoCR conversion failed"},
        503: {"description": "OLMoCR runtime unavailable"},
        504: {"description": "OLMoCR conversion timed out"},
    },
)
async def convert(
    request: Request,
    file: Annotated[UploadFile, File()],
    output_format: Annotated[str, Form()] = "markdown",  # kept for parity; ignored (always markdown)
) -> dict[str, Any]:
    name = (file.filename or "").lower()
    if not name.endswith((".pdf", ".png", ".jpg", ".jpeg")):
        raise HTTPException(status_code=400, detail="Only PDF/PNG/JPG is supported")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    async with _semaphore:
        runtime = _runtime_status()
        if not bool(runtime.get("ok")):
            raise HTTPException(
                status_code=503,
                detail={"error": "olmocr_runtime_unavailable", **runtime},
            )

        with tempfile.TemporaryDirectory(prefix="mimirq_olmocr_") as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            input_path = workspace / f"input{Path(name).suffix.lower()}"
            input_path.write_bytes(file_bytes)

            try:
                return_code, log_tail = await asyncio.wait_for(
                    _run_pipeline(request=request, workspace=workspace, input_name=input_path.name),
                    timeout=float(_PIPELINE_TIMEOUT_SEC),
                )
            except HTTPException:
                raise
            except asyncio.TimeoutError:
                raise HTTPException(status_code=504, detail="olmocr_pipeline_timeout")
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"olmocr_pipeline_error: {str(exc)[:200]}")

            if return_code != 0:
                raise HTTPException(
                    status_code=500,
                    detail=f"olmocr_pipeline_failed (exit={return_code}): {log_tail[-_ERROR_TAIL_CHARS:]}",
                )

            md_path = _pick_markdown_path(workspace)
            if md_path is None:
                raise HTTPException(status_code=500, detail=f"olmocr_no_markdown_output: {log_tail[-1000:]}")

            markdown = md_path.read_text(encoding="utf-8", errors="ignore")
            return {"markdown": markdown, "output_format": "markdown"}
