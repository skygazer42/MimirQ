"""
Deskew/dewarp helpers for preprocessing (Module 1).

The core backend uses external services for model-based deskew to avoid pulling
heavy ML dependencies in-process.
"""

from pathlib import Path

import httpx


def deskew_via_http(
    *,
    input_path: Path,
    output_path: Path,
    url: str,
    timeout_sec: float,
) -> tuple[bool, str]:
    """Apply the optional synchronous deskew service using owned file/HTTP streams."""
    try:
        with input_path.open("rb") as source, httpx.Client(timeout=timeout_sec) as client:
            with client.stream(
                "POST", url.strip(), files={"file": (input_path.name, source, "application/octet-stream")}
            ) as response:
                if response.status_code >= 400:
                    return False, f"deskew_http_{response.status_code}"
                content = response.read()
    except (httpx.HTTPError, OSError) as exc:
        return False, f"deskew_http_failed:{exc.__class__.__name__}"

    if not content:
        return False, "deskew_empty_response"

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(content)
        return True, "deskew_ok"
    except OSError as exc:
        return False, f"deskew_write_failed:{exc.__class__.__name__}"


__all__ = ["deskew_via_http"]
