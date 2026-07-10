"""
Deskew/dewarp helpers for preprocessing (Module 1).

The core backend uses external services for model-based deskew to avoid pulling
heavy ML dependencies in-process.
"""


import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx


def _run_coroutine_sync(factory):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(factory())).result()


async def _deskew_via_http_async(
    *,
    input_path: Path,
    output_path: Path,
    url: str,
    timeout_sec: float,
) -> tuple[bool, str]:
    try:
        file_bytes = input_path.read_bytes()
        timeout = float(timeout_sec)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                str(url).strip(),
                files={"file": (input_path.name, file_bytes, "application/octet-stream")},
            )
    except Exception as exc:  # noqa: BLE001
        return False, f"deskew_http_failed:{exc.__class__.__name__}"

    if int(resp.status_code) >= 400:
        return False, f"deskew_http_{int(resp.status_code)}"
    if not resp.content:
        return False, "deskew_empty_response"

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(resp.content)
        return True, "deskew_ok"
    except Exception as exc:  # noqa: BLE001
        return False, f"deskew_write_failed:{exc.__class__.__name__}"


def deskew_via_http(
    *,
    input_path: Path,
    output_path: Path,
    url: str,
    timeout_sec: float,
) -> tuple[bool, str]:
    """
    Generic deskew via an external service.

    Contract (best-effort):
    - POST multipart form with file field "file"
    - Response body is treated as the processed file bytes (PDF or image).
    """
    return _run_coroutine_sync(
        lambda: _deskew_via_http_async(
            input_path=input_path,
            output_path=output_path,
            url=url,
            timeout_sec=timeout_sec,
        )
    )


__all__ = ["deskew_via_http"]
