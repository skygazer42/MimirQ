"""
Vision-native RAG helpers (VLM-as-Reader).

Goal:
- When retrieval injected image evidence (CLIP hits), optionally call a VLM to "read" the
  chart/diagram/screenshot and extract question-relevant facts.
- Inject extracted text back into the RAG context as bounded Documents so the normal
  text LLM can answer with better grounding.

Design principles:
- Feature-flagged and fail-open: never break chat when vision deps are missing or the
  VLM call fails.
- Bounded cost: strict caps on image count, image bytes, and extracted text length.
- OpenAI-compatible API: uses /chat/completions with image_url data URLs.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import uuid
from collections.abc import AsyncGenerator, Iterable
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from langchain_core.documents import Document

from app.core.config import settings
from app.core.openai_compat import normalize_openai_compatible_base_url
from app.rag.core.logging import get_logger
from app.storage.object.minio import MinIOService

logger = get_logger("rag.multimodal.vision_reader")

_NIL_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")
_DEFAULT_IMAGE_MIME_TYPE = "image/jpeg"


def _guess_mime_type(image_bytes: bytes) -> str:
    if not image_bytes:
        return _DEFAULT_IMAGE_MIME_TYPE
    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    # JPEG: FF D8 FF
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return _DEFAULT_IMAGE_MIME_TYPE
    # GIF: GIF87a / GIF89a
    if image_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    # WebP: RIFF....WEBP
    if len(image_bytes) >= 12 and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return _DEFAULT_IMAGE_MIME_TYPE


def _chat_completions_url(api_base: str) -> str:
    base = normalize_openai_compatible_base_url(api_base).rstrip("/")
    if not base:
        return ""
    return f"{base}/chat/completions"


def _stable_vision_reader_chunk_id(origin_chunk_id: str) -> str:
    """
    Deterministic UUID so ChatResponse citation schema remains compatible.

    We keep citations chunk_id UUID-like even though this is a synthetic "doc".
    """

    raw = str(origin_chunk_id or "").strip()
    return str(uuid.uuid5(_NIL_UUID, f"mimirq:vision_reader:{raw}"))


def _iter_local_image_candidates(*, tenant_id: UUID, image_id: str) -> Iterable[Path]:
    base = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
    safe = ""
    try:
        safe = UUID(str(image_id)).hex
    except Exception:
        return []
    exts = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"]
    for ext in exts:
        yield base / f"{safe}{ext}"


def _load_image_bytes_from_local_sync(*, tenant_id: UUID, image_id: str, max_bytes: int) -> bytes | None:
    for p in _iter_local_image_candidates(tenant_id=tenant_id, image_id=image_id):
        try:
            if not p.exists() or not p.is_file():
                continue
            if int(max_bytes or 0) > 0:
                try:
                    st = p.stat()
                    if int(getattr(st, "st_size", 0) or 0) > int(max_bytes):
                        return None
                except Exception as exc:
                    # If stat fails, still try to read boundedly below.
                    logger.debug("Failed to stat local vision image candidate %s; trying bounded read: %s", p, exc)
            with p.open("rb") as f:
                data = f.read(int(max_bytes) if int(max_bytes or 0) > 0 else -1)
            return data or None
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
    return None


def _minio_object_name_for_img_id(img_id: str, *, extension: str = "jpg") -> str | None:
    """
    Best-effort derive MinIO object_name from img_id.

    img_id format: "{tenant_id}:{dataset_id}:{document_id}:{chunk_key}"
    """
    raw = str(img_id or "").strip()
    if ":" not in raw:
        return None
    try:
        tenant, dataset, document, chunk_key = raw.split(":", 3)
    except ValueError:
        return None
    tenant = tenant.strip()
    dataset = dataset.strip()
    document = document.strip()
    chunk_key = chunk_key.strip()
    if not (tenant and dataset and document and chunk_key):
        return None
    ext = (extension or "jpg").strip().lower() or "jpg"
    return f"images/{tenant}/{dataset}/{document}/{chunk_key}.{ext}"


def _load_image_bytes_from_minio_sync(*, img_id: str, max_bytes: int) -> bytes | None:
    if not bool(getattr(settings, "MINIO_ENABLED", False)):
        return None
    obj = _minio_object_name_for_img_id(img_id, extension="jpg")
    if not obj:
        return None
    svc = MinIOService()
    try:
        buf = io.BytesIO()
        total = 0
        for chunk in svc.iter_object_bytes(object_name=obj, chunk_size=256 * 1024):
            if not chunk:
                continue
            buf.write(chunk)
            total += len(chunk)
            if int(max_bytes or 0) > 0 and total > int(max_bytes):
                return None
        data = buf.getvalue()
        return data or None
    except Exception as exc:  # noqa: BLE001
        logger.debug("MinIO image load failed (ignored): %s", str(exc)[:200])
        return None


async def _load_image_bytes(
    *,
    meta: dict[str, Any],
    tenant_id: UUID | None,
    max_bytes: int,
) -> tuple[bytes | None, str]:
    """
    Load image bytes for an injected "image doc".

    Returns: (bytes|None, loader_reason)
    """
    img_id = str(meta.get("img_id") or "").strip() or None
    image_id = str(meta.get("image_id") or "").strip() or None

    if img_id:
        data = await asyncio.to_thread(_load_image_bytes_from_minio_sync, img_id=img_id, max_bytes=max_bytes)
        return data, ("minio" if data else "minio_missing_or_too_large")

    if image_id and tenant_id is not None:
        data = await asyncio.to_thread(
            _load_image_bytes_from_local_sync,
            tenant_id=tenant_id,
            image_id=image_id,
            max_bytes=max_bytes,
        )
        return data, ("local" if data else "local_missing_or_too_large")

    if image_id and tenant_id is None:
        return None, "local_missing_tenant_id"

    return None, "missing_image_ref"


def _build_prompt(*, question: str, meta: dict[str, Any]) -> str:
    doc_name = str(meta.get("source") or meta.get("document_name") or "").strip()
    page = meta.get("page_number") if meta.get("page_number") is not None else meta.get("page")
    try:
        page_i = int(page) if page is not None else None
    except Exception:
        page_i = None

    location = ""
    if doc_name and page_i is not None:
        location = f" (source: {doc_name}, page {page_i})"
    elif doc_name:
        location = f" (source: {doc_name})"
    elif page_i is not None:
        location = f" (page {page_i})"

    q = str(question or "").strip()
    return (
        "You are a careful technical document reader.\n"
        "Read the image and extract ONLY the information relevant to the user's question.\n"
        "- Focus on numbers, units, axis labels, legends, and key relationships.\n"
        "- If the image is a table, preserve row/column meaning.\n"
        "- If the image contains no relevant information, output exactly: NO_RELEVANT_INFO\n"
        "- Do not invent values.\n"
        f"\nUser question{location}:\n{q}\n"
    )


async def _describe_with_vision_llm(
    *,
    http_client: httpx.AsyncClient,
    image_bytes: bytes,
    prompt: str,
) -> str:
    api_key = (getattr(settings, "VISION_LLM_API_KEY", "") or "").strip() or (getattr(settings, "LLM_API_KEY", "") or "").strip()
    api_base = (getattr(settings, "VISION_LLM_API_BASE", "") or "").strip() or (getattr(settings, "LLM_API_BASE", "") or "").strip()
    model = (getattr(settings, "VISION_LLM_MODEL", "") or "").strip()
    if not api_key or not api_base or not model:
        raise RuntimeError("vision_llm_not_configured")

    url = _chat_completions_url(api_base)
    if not url:
        raise RuntimeError("vision_llm_missing_api_base")

    mime_type = _guess_mime_type(image_bytes)
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{mime_type};base64,{encoded}"

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": str(prompt or "")},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "max_tokens": int(getattr(settings, "VISION_LLM_MAX_TOKENS", 4096) or 4096),
        "temperature": float(getattr(settings, "VISION_LLM_TEMPERATURE", 0.0) or 0.0),
        "stream": False,
    }

    timeout = float(getattr(settings, "VISION_LLM_TIMEOUT_SEC", 120) or 120)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    resp = await http_client.post(url, json=payload, headers=headers, timeout=timeout)
    if int(resp.status_code or 0) != 200:
        raise RuntimeError(f"vision_llm_http_{resp.status_code}:{(resp.text or '')[:200]}")

    data = resp.json()
    choice0 = (data.get("choices") or [{}])[0]
    msg = choice0.get("message") if isinstance(choice0, dict) else None
    content = msg.get("content") if isinstance(msg, dict) else None
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    # Some providers return structured content blocks; best-effort stringify.
    return str(content).strip()


async def build_vision_image_blocks(
    *,
    image_docs: list[Document],
    tenant_id: UUID | None,
    max_images: int,
    max_image_bytes: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Build OpenAI-compatible image_url blocks from injected image docs.

    Returns: (blocks, meta)
    """
    max_images_i = max(0, int(max_images or 0))
    max_bytes_i = max(1, int(max_image_bytes or 0))
    meta: dict[str, Any] = {
        "attempted": 0,
        "succeeded": 0,
        "skipped": 0,
        "errors": [],
        "max_images": int(max_images_i),
        "max_image_bytes": int(max_bytes_i),
    }

    if not image_docs or max_images_i <= 0:
        return [], meta

    blocks: list[dict[str, Any]] = []
    errors: list[str] = []
    attempted = 0
    succeeded = 0
    skipped = 0
    for doc in image_docs[:max_images_i]:
        attempted += 1
        meta0 = getattr(doc, "metadata", None)
        meta0 = meta0 if isinstance(meta0, dict) else {}

        raw_bytes, loader_reason = await _load_image_bytes(meta=meta0, tenant_id=tenant_id, max_bytes=max_bytes_i)
        if not raw_bytes:
            skipped += 1
            if len(errors) < 5:
                errors.append(f"skip:{loader_reason}")
            continue

        mime_type = _guess_mime_type(raw_bytes)
        encoded = base64.b64encode(raw_bytes).decode("utf-8")
        data_url = f"data:{mime_type};base64,{encoded}"
        blocks.append({"type": "image_url", "image_url": {"url": data_url}})
        succeeded += 1

    meta.update(
        {
            "attempted": int(attempted),
            "succeeded": int(succeeded),
            "skipped": int(skipped),
            "errors": errors,
        }
    )
    return blocks, meta


async def stream_vision_chat_completions_tokens(
    *,
    http_client: httpx.AsyncClient,
    messages: list[dict[str, Any]],
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> AsyncGenerator[str, None]:
    """
    Stream tokens from an OpenAI-compatible /chat/completions endpoint.

    This is used by the RAG engine when generating an answer directly with a VLM,
    so we can keep the rest of the RAG pipeline (citations, claim-check, etc.) intact.
    """
    api_key = (getattr(settings, "VISION_LLM_API_KEY", "") or "").strip() or (getattr(settings, "LLM_API_KEY", "") or "").strip()
    api_base = (getattr(settings, "VISION_LLM_API_BASE", "") or "").strip() or (getattr(settings, "LLM_API_BASE", "") or "").strip()
    model = (getattr(settings, "VISION_LLM_MODEL", "") or "").strip()
    if not api_key or not api_base or not model:
        raise RuntimeError("vision_llm_not_configured")

    url = _chat_completions_url(api_base)
    if not url:
        raise RuntimeError("vision_llm_missing_api_base")

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": int(max_tokens) if max_tokens is not None else int(getattr(settings, "VISION_LLM_MAX_TOKENS", 4096) or 4096),
        "temperature": float(temperature) if temperature is not None else float(getattr(settings, "VISION_LLM_TEMPERATURE", 0.0) or 0.0),
        "stream": True,
    }

    timeout = float(getattr(settings, "VISION_LLM_TIMEOUT_SEC", 120) or 120)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async with http_client.stream("POST", url, json=payload, headers=headers, timeout=timeout) as resp:
        if int(resp.status_code or 0) != 200:
            body = await resp.aread()
            raise RuntimeError(f"vision_llm_http_{resp.status_code}:{(body or b'')[:200].decode('utf-8','ignore')}")

        async for line in resp.aiter_lines():
            if not line:
                continue
            s = line.strip()
            if not s:
                continue
            if not s.startswith("data:"):
                continue
            data_s = s[5:].strip()
            if not data_s:
                continue
            if data_s == "[DONE]":
                break
            try:
                evt = json.loads(data_s)
            except Exception:
                get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                continue
            if not isinstance(evt, dict):
                continue
            choices = evt.get("choices") if isinstance(evt.get("choices"), list) else []
            if not choices:
                continue
            c0 = choices[0] if isinstance(choices[0], dict) else {}
            delta = c0.get("delta") if isinstance(c0.get("delta"), dict) else {}
            token = delta.get("content")
            if token is None:
                continue
            token_s = token if isinstance(token, str) else str(token)
            if token_s:
                yield token_s


async def build_vision_reader_context_docs(
    *,
    image_docs: list[Document],
    question: str,
    tenant_id: UUID | None,
    http_client: httpx.AsyncClient,
) -> tuple[list[Document], dict[str, Any]]:
    """
    Turn injected `retrieval_role=image` docs into extra docs produced by a VLM reader.

    Returns: (vision_docs, meta)
    """
    enabled = bool(getattr(settings, "VISION_RAG_READER_ENABLED", False))
    meta: dict[str, Any] = {"enabled": bool(enabled), "used": False, "reason": "not_run"}
    if not enabled:
        meta["reason"] = "VISION_RAG_READER_ENABLED=false"
        return [], meta

    if not bool(getattr(settings, "VISION_LLM_ENABLED", False)):
        meta["reason"] = "VISION_LLM_ENABLED=false"
        return [], meta

    if not image_docs:
        meta["reason"] = "no_image_docs"
        return [], meta

    max_images = max(0, int(getattr(settings, "VISION_RAG_READER_MAX_IMAGES", 2) or 2))
    if max_images <= 0:
        meta["reason"] = "max_images=0"
        return [], meta

    max_image_bytes = max(1, int(getattr(settings, "VISION_RAG_READER_MAX_IMAGE_BYTES", 3_000_000) or 3_000_000))
    max_output_chars = max(0, int(getattr(settings, "VISION_RAG_READER_MAX_OUTPUT_CHARS", 1500) or 1500))

    attempted = 0
    succeeded = 0
    skipped = 0
    errors: list[str] = []

    out: list[Document] = []
    for doc in image_docs[:max_images]:
        attempted += 1
        meta0 = getattr(doc, "metadata", None)
        meta0 = meta0 if isinstance(meta0, dict) else {}

        # Load bytes (best-effort).
        raw_bytes, loader_reason = await _load_image_bytes(meta=meta0, tenant_id=tenant_id, max_bytes=max_image_bytes)
        if not raw_bytes:
            skipped += 1
            if len(errors) < 5:
                errors.append(f"skip:{loader_reason}")
            continue

        prompt = _build_prompt(question=question, meta=meta0)
        try:
            extracted = await _describe_with_vision_llm(http_client=http_client, image_bytes=raw_bytes, prompt=prompt)
        except Exception as exc:  # noqa: BLE001
            skipped += 1
            if len(errors) < 5:
                errors.append(f"vision_exception:{str(exc)[:120]}")
            continue

        text = (extracted or "").strip()
        if not text or text == "NO_RELEVANT_INFO":
            skipped += 1
            continue

        if max_output_chars and len(text) > max_output_chars:
            text = text[:max_output_chars].rstrip() + "\n\n(truncated)"

        origin_chunk_id = str(getattr(doc, "id", None) or meta0.get("chunk_id") or "").strip() or None
        vision_chunk_id = _stable_vision_reader_chunk_id(origin_chunk_id or str(uuid.uuid4()))

        # Keep the image metadata so citations can still render thumbnails via img_id/img_url.
        new_meta: dict[str, Any] = dict(meta0)
        new_meta.update(
            {
                "retrieval_role": "vision_reader",
                "doc_type_kwd": "image",
                "origin_chunk_id": origin_chunk_id,
                "neighbor_of": origin_chunk_id,
            }
        )

        out.append(Document(page_content=text, metadata=new_meta, id=vision_chunk_id))
        succeeded += 1

    if out:
        reason = "ok"
    elif attempted:
        reason = "all_skipped"
    else:
        reason = "not_run"

    meta.update(
        {
            "used": bool(out),
            "reason": reason,
            "attempted": int(attempted),
            "succeeded": int(succeeded),
            "skipped": int(skipped),
            "returned": int(len(out)),
            "max_images": int(max_images),
            "max_image_bytes": int(max_image_bytes),
            "max_output_chars": int(max_output_chars),
            "errors": errors,
            "model": str(getattr(settings, "VISION_LLM_MODEL", "") or "").strip() or None,
        }
    )
    return out, meta


__all__ = [
    "build_vision_image_blocks",
    "build_vision_reader_context_docs",
    "stream_vision_chat_completions_tokens",
]
