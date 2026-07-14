
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from app.core.async_bridge import run_coroutine_sync as _run_coroutine_sync

_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HTML_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_HTML_IMG_ATTR_RE = re.compile(r"(src|alt)\s*=\s*([\"'])(.*?)\2", re.IGNORECASE)
_FENCE_RE = re.compile(r"^\s*(```+|~~~+)")
_MINIO_URL_HINT = "/api/v1/documents/image-url/"
_CHART_HINT_RE = re.compile(r"\b(chart|plot|graph|bar|line|pie|trend)\b", re.IGNORECASE)
CHART_DATA_SCHEMA_V1 = "mimirq.chart_data.v1"


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    except Exception:
        return str(value)


def _stable_hash(*parts: Any, length: int = 24) -> str:
    h = hashlib.sha256()
    for part in parts:
        if isinstance(part, bytes):
            data = part
        else:
            data = str(part or "").encode("utf-8", errors="ignore")
        h.update(data)
        h.update(b"\0")
    return h.hexdigest()[: max(8, int(length or 24))]


def _coerce_confidence(value: Any) -> float | None:
    try:
        if value is None:
            return None
        out = float(value)
    except Exception:
        return None
    if out < 0:
        return 0.0
    if out > 1:
        return 1.0
    return out


def build_chart_data_v1_payload(
    payload: dict[str, Any],
    *,
    src: str,
    alt: str,
    image_bytes: bytes,
) -> dict[str, Any]:
    """
    Normalize backend-specific chart extraction into a stable v1 sidecar schema.

    The raw backend payload is preserved so existing downstream consumers still
    see vendor-specific fields, while common fields get stable names for Golden
    eval, caching and citation rendering.
    """
    raw = dict(payload or {})
    digest = _stable_hash(src, image_bytes, _stable_json(raw), length=32)
    source_image = str(src or "").strip()
    out: dict[str, Any] = {
        "schema": CHART_DATA_SCHEMA_V1,
        "chart_id": f"chart_{digest[:16]}",
        "cache_key": f"chart_data:v1:{digest}",
        "source_image": source_image,
        "alt": str(alt or "").strip(),
        "page": raw.get("page"),
        "title": raw.get("title"),
        "series": raw.get("series") if isinstance(raw.get("series"), list) else [],
        "units": raw.get("units") or raw.get("unit"),
        "confidence": _coerce_confidence(raw.get("confidence")),
        "raw_payload": raw,
    }
    return out


def _extract_md_images(line: str) -> list[tuple[str, str]]:
    return [(alt or "", src or "") for alt, src in _MD_IMAGE_RE.findall(line or "")]


def _extract_html_imgs(line: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for tag in _HTML_IMG_TAG_RE.findall(line or ""):
        alt = ""
        src = ""
        for key, _q, val in _HTML_IMG_ATTR_RE.findall(tag):
            k = (key or "").strip().lower()
            if k == "alt":
                alt = val
            elif k == "src":
                src = val
        out.append((alt or "", src or ""))
    return out


def _is_chart_candidate(*, alt: str, src: str) -> bool:
    hint = f"{alt or ''} {src or ''}".strip()
    return bool(hint and _CHART_HINT_RE.search(hint))


def _safe_read_local_image_bytes(*, src: str, origin_path: Path, max_bytes: int) -> tuple[bytes | None, str]:
    raw = str(src or "").strip()
    if not raw:
        return None, "empty_src"
    if raw.startswith("data:"):
        return None, "data_url_unsupported"
    if urlparse(raw).scheme in {"http", "https"}:
        return None, "remote_url_unsupported"
    if _MINIO_URL_HINT in raw:
        return None, "already_minio_url"

    resolved_ref = raw
    if raw.lower().startswith("file://"):
        parsed = urlparse(raw)
        if str(parsed.scheme or "").lower() != "file":
            return None, "unsupported_scheme"
        netloc = str(parsed.netloc or "").strip().lower()
        if netloc and netloc not in {"localhost", "127.0.0.1"}:
            return None, "remote_file_url"
        resolved_ref = unquote(str(parsed.path or ""))
        if re.match(r"^/[a-zA-Z]:/", resolved_ref):
            resolved_ref = resolved_ref[1:]
    else:
        resolved_ref = unquote(resolved_ref)

    base_dir = origin_path.resolve(strict=False)
    if base_dir.is_file():
        base_dir = base_dir.parent
    base_dir_resolved = base_dir.resolve(strict=False)
    path_obj = Path(resolved_ref)
    if not path_obj.is_absolute():
        path_obj = (base_dir_resolved / path_obj).resolve(strict=False)
    else:
        path_obj = path_obj.resolve(strict=False)

    try:
        path_obj.relative_to(base_dir_resolved)
    except Exception:
        return None, "path_outside_origin"
    if not path_obj.exists() or not path_obj.is_file():
        return None, "missing_file"
    try:
        if int(path_obj.stat().st_size) > int(max_bytes):
            return None, "too_large"
        data = path_obj.read_bytes()
    except Exception:
        return None, "read_failed"
    if len(data) > int(max_bytes):
        return None, "too_large"
    return data, "ok"


async def _call_chart_backend_async(
    *,
    api_url: str,
    image_bytes: bytes,
    filename: str,
    timeout_sec: float,
) -> tuple[dict[str, Any] | None, str]:
    timeout = float(timeout_sec)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(
                str(api_url).strip(),
                files={"file": (filename or "chart.png", image_bytes, "application/octet-stream")},
            )
        except Exception as exc:  # noqa: BLE001
            return None, f"http_failed:{exc.__class__.__name__}"

        if int(resp.status_code) >= 400:
            return None, f"http_{int(resp.status_code)}"

        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            return None, f"parse_failed:{exc.__class__.__name__}"
        if isinstance(data, dict):
            return data, "ok_json"
        return None, "invalid_payload"


def _call_chart_backend(
    *,
    api_url: str,
    image_bytes: bytes,
    filename: str,
    timeout_sec: float,
) -> tuple[dict[str, Any] | None, str]:
    return _run_coroutine_sync(
        lambda: _call_chart_backend_async(
            api_url=api_url,
            image_bytes=image_bytes,
            filename=filename,
            timeout_sec=timeout_sec,
        )
    )


@dataclass(frozen=True, slots=True)
class ChartToDataAudit:
    applied: bool
    charts_added: int
    images_attempted: int
    images_succeeded: int
    elapsed_ms: int
    backend: str
    error: str | None = None
    chart_elements: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": bool(self.applied),
            "charts_added": int(self.charts_added),
            "images_attempted": int(self.images_attempted),
            "images_succeeded": int(self.images_succeeded),
            "elapsed_ms": int(self.elapsed_ms),
            "backend": str(self.backend or ""),
            "error": (str(self.error)[:200] if self.error else None),
            "chart_elements": list(self.chart_elements or []),
        }


def add_chart_data_blocks(
    markdown: str,
    *,
    origin_path: Path,
    max_images: int = 8,
    max_image_bytes: int = 5_000_000,
    timeout_sec: float = 20.0,
) -> tuple[str, int, ChartToDataAudit]:
    from app.core.config import settings

    raw = str(markdown or "")
    if not bool(getattr(settings, "CHART_TO_DATA_ENABLED", False)):
        return raw, 0, ChartToDataAudit(
            applied=False,
            charts_added=0,
            images_attempted=0,
            images_succeeded=0,
            elapsed_ms=0,
            backend="chart_to_data",
            chart_elements=[],
            error=None,
        )

    api_url = str(getattr(settings, "CHART_TO_DATA_API_URL", "") or "").strip()
    if not api_url:
        return raw, 0, ChartToDataAudit(
            applied=False,
            charts_added=0,
            images_attempted=0,
            images_succeeded=0,
            elapsed_ms=0,
            backend="chart_to_data",
            chart_elements=[],
            error="api_url_missing",
        )

    t0 = time.perf_counter()
    out_lines: list[str] = []
    in_fence = False
    charts_added = 0
    images_attempted = 0
    images_succeeded = 0
    chart_elements: list[dict[str, Any]] = []

    for line in raw.splitlines():
        if _FENCE_RE.match(line or ""):
            in_fence = not in_fence
            out_lines.append(line)
            continue
        out_lines.append(line)
        if in_fence or charts_added >= max(0, int(max_images or 0)):
            continue

        images = _extract_md_images(line) + _extract_html_imgs(line)
        if not images:
            continue
        for alt, src in images:
            if charts_added >= max(0, int(max_images or 0)):
                break
            if not _is_chart_candidate(alt=alt, src=src):
                continue
            image_bytes, _ = _safe_read_local_image_bytes(
                src=src,
                origin_path=origin_path,
                max_bytes=int(max_image_bytes or 0),
            )
            if image_bytes is None:
                continue
            images_attempted += 1
            payload, backend_status = _call_chart_backend(
                api_url=api_url,
                image_bytes=image_bytes,
                filename=Path(src).name or "chart.png",
                timeout_sec=float(timeout_sec or 20.0),
            )
            if not payload:
                continue
            images_succeeded += 1
            chart_payload = build_chart_data_v1_payload(
                payload,
                src=src,
                alt=alt,
                image_bytes=image_bytes,
            )
            block = json.dumps(chart_payload, ensure_ascii=False, indent=2)
            out_lines.append("")
            out_lines.append("Chart data:")
            out_lines.append("```json")
            out_lines.append(block)
            out_lines.append("```")
            charts_added += 1
            chart_elements.append(
                {
                    "src": src,
                    "alt": alt,
                    "schema": CHART_DATA_SCHEMA_V1,
                    "chart_id": chart_payload["chart_id"],
                    "cache_key": chart_payload["cache_key"],
                    "backend_status": backend_status,
                }
            )

    out = "\n".join(out_lines)
    audit = ChartToDataAudit(
        applied=bool(charts_added > 0),
        charts_added=int(charts_added),
        images_attempted=int(images_attempted),
        images_succeeded=int(images_succeeded),
        elapsed_ms=int(round((time.perf_counter() - t0) * 1000)),
        backend="chart_to_data",
        chart_elements=chart_elements,
        error=None,
    )
    return out, charts_added, audit


__all__ = ["CHART_DATA_SCHEMA_V1", "ChartToDataAudit", "add_chart_data_blocks", "build_chart_data_v1_payload"]
