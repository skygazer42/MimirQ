from __future__ import annotations

import asyncio
import os
import signal
import tempfile
from pathlib import Path
from typing import Any, Optional

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

_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_JOBS)


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


async def _run_pipeline(
    *,
    request: Request,
    workspace: Path,
    input_name: str,
) -> tuple[int, str]:
    server_url = (os.environ.get("OLMOCR_SERVER_URL") or "").strip()
    api_key = (os.environ.get("OLMOCR_API_KEY") or "").strip()
    model = (os.environ.get("OLMOCR_MODEL") or "").strip()

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
    return {"ok": True}


@app.post("/convert")
async def convert(
    request: Request,
    file: UploadFile = File(...),
    output_format: str = Form("markdown"),  # kept for parity; ignored (always markdown)
) -> dict[str, Any]:
    name = (file.filename or "").lower()
    if not (name.endswith(".pdf") or name.endswith(".png") or name.endswith(".jpg") or name.endswith(".jpeg")):
        raise HTTPException(status_code=400, detail="Only PDF/PNG/JPG is supported")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    async with _semaphore:
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
                    detail=f"olmocr_pipeline_failed (exit={return_code}): {log_tail[-2000:]}",
                )

            md_path = _pick_markdown_path(workspace)
            if md_path is None:
                raise HTTPException(status_code=500, detail=f"olmocr_no_markdown_output: {log_tail[-1000:]}")

            markdown = md_path.read_text(encoding="utf-8", errors="ignore")
            return {"markdown": markdown, "output_format": "markdown"}
