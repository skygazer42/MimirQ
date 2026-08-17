import asyncio
import base64
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any

import fitz
import requests
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

app = FastAPI(title="mimirq-qianfanocr", version="0.1.0")


def _get_bool_env(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def _get_int_env(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_float_env(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


_MAX_CONCURRENT_JOBS = max(1, _get_int_env("QIANFAN_OCR_MAX_CONCURRENT_JOBS", 1))
_MAX_UPLOAD_BYTES = max(1, _get_int_env("QIANFAN_OCR_MAX_UPLOAD_BYTES", 50 * 1024 * 1024))
_PAGE_CONCURRENCY = max(1, _get_int_env("QIANFAN_OCR_PAGE_CONCURRENCY", 1))
_PDF_DPI = max(72, _get_int_env("QIANFAN_OCR_PDF_DPI", 200))
_TIMEOUT_SEC = max(10.0, _get_float_env("QIANFAN_OCR_REQUEST_TIMEOUT_SEC", 120.0))
_SERVER_URL = (os.environ.get("QIANFAN_OCR_SERVER_URL") or "").strip()
_QIANFAN_ONLINE_HOST = "qianfan.baidubce.com"
_DEFAULT_MODEL = "deepseek-ocr" if _QIANFAN_ONLINE_HOST in _SERVER_URL else "baidu/Qianfan-OCR"
_MODEL = (os.environ.get("QIANFAN_OCR_MODEL") or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
_SERVER_API_KEY = (
    os.environ.get("QIANFAN_OCR_SERVER_API_KEY")
    or os.environ.get("QIANFAN_API_KEY")
    or os.environ.get("QIANFAN_API_TOKEN")
    or ""
).strip()
_MAX_TOKENS = max(256, _get_int_env("QIANFAN_OCR_MAX_TOKENS", 4096))
_TEMPERATURE = float(_get_float_env("QIANFAN_OCR_TEMPERATURE", 0.0))
_DEFAULT_LAYOUT_AS_THOUGHT = _get_bool_env("QIANFAN_OCR_LAYOUT_AS_THOUGHT", False)
_LAYOUT_TRIGGER = (os.environ.get("QIANFAN_OCR_LAYOUT_TRIGGER") or "").strip()
_DEFAULT_MARKDOWN_PROMPT = (
    "Convert the document to markdown with correct reading order. Keep tables in HTML and formulas in $$...$$."
)
_QIANFAN_ONLINE_PROMPT = "OCR this image."


def _default_prompt_for_server(server_url: str) -> str:
    if _QIANFAN_ONLINE_HOST in (server_url or ""):
        return _QIANFAN_ONLINE_PROMPT
    return _DEFAULT_MARKDOWN_PROMPT


_PROMPT = (os.environ.get("QIANFAN_OCR_PROMPT") or _default_prompt_for_server(_SERVER_URL)).strip()
_STRIP_THINK_TAGS = _get_bool_env("QIANFAN_OCR_STRIP_THINK_TAGS", True)

_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_JOBS)

_THINK_RE = re.compile(r"<think>.*?</think>", flags=re.IGNORECASE | re.DOTALL)
_REF_RE = re.compile(r"<\|ref\|>.*?<\|/ref\|>", flags=re.DOTALL)
_DET_RE = re.compile(r"<\|det\|>.*?<\|/det\|>", flags=re.DOTALL)


async def _read_upload(file: UploadFile) -> bytes:
    data = bytearray()
    while chunk := await file.read(min(1024 * 1024, _MAX_UPLOAD_BYTES + 1 - len(data))):
        data.extend(chunk)
        if len(data) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="upload too large")
    return bytes(data)


def _build_api_url() -> str:
    base = (_SERVER_URL or "").rstrip("/")
    if not base:
        raise RuntimeError("QIANFAN_OCR_SERVER_URL is empty")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith(("/v1", "/v2")):
        return f"{base}/chat/completions"
    if "qianfan.baidubce.com" in base:
        return f"{base}/v2/chat/completions"
    return f"{base}/v1/chat/completions"


def _render_pdf_pages(pdf_bytes: bytes, *, dpi: int) -> list[bytes]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images: list[bytes] = []
    try:
        for page in doc:
            scale = float(dpi) / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            images.append(pix.tobytes("jpg"))
    finally:
        doc.close()
    return images


def _extract_message_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        parts: list[str] = []
        for item in payload:
            if isinstance(item, str):
                if item.strip():
                    parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


def _normalize_output(text: str) -> str:
    out = str(text or "").strip()
    out = _REF_RE.sub("", out)
    out = _DET_RE.sub("", out)
    if _STRIP_THINK_TAGS:
        out = _THINK_RE.sub("", out)
    return out.strip()


def _build_prompt(*, layout_as_thought: bool) -> str:
    prompt = _PROMPT or "Convert the document to markdown."
    if layout_as_thought and _LAYOUT_TRIGGER:
        return f"{prompt}\n{_LAYOUT_TRIGGER}".strip()
    return prompt


def _call_qianfan_ocr(*, image_bytes: bytes, layout_as_thought: bool) -> str:
    data_url = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "model": _MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": _build_prompt(layout_as_thought=layout_as_thought)},
                ],
            }
        ],
        "max_tokens": _MAX_TOKENS,
        "temperature": _TEMPERATURE,
    }

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if _SERVER_API_KEY:
        headers["Authorization"] = f"Bearer {_SERVER_API_KEY}"

    resp = requests.post(_build_api_url(), headers=headers, json=payload, timeout=float(_TIMEOUT_SEC))
    if int(getattr(resp, "status_code", 0) or 0) != 200:
        raise RuntimeError(f"upstream_error {resp.status_code}: {(resp.text or '')[:500]}")

    data = resp.json()
    raw = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
    return _normalize_output(_extract_message_text(raw))


def _decode_document_pages(file_bytes: bytes, suffix: str) -> list[bytes]:
    suffix = (suffix or "").lower()
    try:
        if suffix == ".pdf":
            return _render_pdf_pages(file_bytes, dpi=_PDF_DPI)
        if suffix in {".png", ".jpg", ".jpeg"}:
            return [file_bytes]
        raise RuntimeError("unsupported_file_type")
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"document_decode_failed: {str(exc)[:200]}") from exc


def _ocr_pages_serial(pages: list[bytes], *, layout_as_thought: bool) -> list[str]:
    return [_call_qianfan_ocr(image_bytes=page, layout_as_thought=layout_as_thought) for page in pages]


def _ocr_pages_parallel(pages: list[bytes], *, layout_as_thought: bool) -> list[str]:
    results = [""] * len(pages)
    with ThreadPoolExecutor(max_workers=min(_PAGE_CONCURRENCY, len(pages))) as pool:
        future_map = {
            pool.submit(_call_qianfan_ocr, image_bytes=img, layout_as_thought=layout_as_thought): idx
            for idx, img in enumerate(pages)
        }
        for future, idx in future_map.items():
            try:
                results[idx] = future.result()
            except Exception as exc:
                raise RuntimeError(f"page_{idx + 1}_failed: {str(exc)[:300]}") from exc
    return results


def _render_page_markdown(results: list[str]) -> tuple[str, int]:
    if len(results) == 1:
        return (results[0] or "").strip(), 1

    blocks: list[str] = []
    for index, text in enumerate(results, start=1):
        text0 = (text or "").strip()
        if not text0:
            continue
        blocks.append(f"<!-- page {index} -->\n{text0}")
    return "\n\n".join(blocks).strip(), len(results)


def _convert_document(file_bytes: bytes, suffix: str, *, layout_as_thought: bool) -> tuple[str, int]:
    pages = _decode_document_pages(file_bytes, suffix)
    if not pages:
        return "", 0

    if len(pages) == 1 or _PAGE_CONCURRENCY <= 1:
        results = _ocr_pages_serial(pages, layout_as_thought=layout_as_thought)
    else:
        results = _ocr_pages_parallel(pages, layout_as_thought=layout_as_thought)
    return _render_page_markdown(results)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "mode": "openai_compatible",
        "model": _MODEL,
        "server_configured": bool(_SERVER_URL),
        "max_concurrent_jobs": _MAX_CONCURRENT_JOBS,
        "page_concurrency": _PAGE_CONCURRENCY,
        "pdf_dpi": _PDF_DPI,
        "layout_trigger_configured": bool(_LAYOUT_TRIGGER),
    }


@app.post(
    "/convert",
    responses={
        400: {"description": "Invalid or empty upload"},
        500: {"description": "Qianfan OCR conversion failed"},
    },
)
async def convert(
    file: Annotated[UploadFile, File()],
    output_format: Annotated[str, Form()] = "markdown",  # kept for parity; ignored (always markdown)
    layout_as_thought: Annotated[str, Form()] = "",
) -> dict[str, Any]:
    _ = output_format
    name = (file.filename or "").lower()
    suffix = os.path.splitext(name)[1].lower()
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg"}:
        raise HTTPException(status_code=400, detail="Only PDF/PNG/JPG is supported")

    file_bytes = await _read_upload(file)
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    layout = _DEFAULT_LAYOUT_AS_THOUGHT
    raw_layout = (layout_as_thought or "").strip().lower()
    if raw_layout:
        layout = raw_layout in {"1", "true", "yes", "y", "on"}

    async with _semaphore:
        try:
            markdown, page_count = await asyncio.to_thread(
                _convert_document,
                file_bytes,
                suffix,
                layout_as_thought=layout,
            )
        except HTTPException:
            raise
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=f"qianfan_ocr_error: {str(exc)[:300]}") from exc

    return {
        "markdown": markdown,
        "output_format": "markdown",
        "pages": int(page_count),
        "layout_as_thought": bool(layout),
    }
