"""
Deskew/dewarp helpers for preprocessing (Module 1).

The core backend uses external services for model-based deskew to avoid pulling
heavy ML dependencies in-process.
"""

from __future__ import annotations

from pathlib import Path

import requests


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
    try:
        file_bytes = input_path.read_bytes()
        resp = requests.post(
            str(url).strip(),
            files={"file": (input_path.name, file_bytes, "application/octet-stream")},
            timeout=float(timeout_sec),
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


__all__ = ["deskew_via_http"]

