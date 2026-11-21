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

import asyncio
import io
import json
import logging
import uuid
from collections.abc import AsyncGenerator, Iterable
from pathlib import Path
from typing import Any, NamedTuple
from uuid import UUID

import httpx
from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.infrastructure.http.openai import normalize_openai_compatible_base_url
from app.rag.llm.vision_client import VisionImageBlock, build_image_url_block
from app.storage.object.minio import MinIOService
from app.types.document_metadata import is_local_image_id

logger = logging.getLogger("rag.multimodal.vision_reader")


def select_image_evidence(docs: Iterable[Document]) -> list[Document]:
    """Keep image references already returned by authorized document retrieval."""
    return [doc for doc in docs if doc.metadata.get("img_id") or doc.metadata.get("image_id")]


_NIL_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")


class _VisionReaderLimits(NamedTuple):
    max_images: int
    max_image_bytes: int
    max_output_chars: int


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

    raw = origin_chunk_id.strip()
    return str(uuid.uuid5(_NIL_UUID, f"mimirq:vision_reader:{raw}"))


def _iter_local_image_candidates(*, tenant_id: UUID, image_id: str) -> Iterable[Path]:
    base = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
    safe = ""
    try:
        safe = UUID(str(image_id)).hex
    except ValueError:
        return []
    exts = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"]
    for ext in exts:
        yield base / f"{safe}{ext}"


def _load_image_bytes_from_local_sync(*, tenant_id: UUID, image_id: str, max_bytes: int) -> bytes | None:
    for p in _iter_local_image_candidates(tenant_id=tenant_id, image_id=image_id):
        try:
            if not p.exists() or not p.is_file():
                continue
            if max_bytes > 0:
                try:
                    st = p.stat()
                    if st.st_size > max_bytes:
                        return None
                except OSError as exc:
                    # If stat fails, still try to read boundedly below.
                    logger.debug("Failed to stat local vision image candidate %s; trying bounded read: %s", p, exc)
            with p.open("rb") as f:
                data = f.read(max_bytes + 1 if max_bytes > 0 else -1)
            if max_bytes > 0 and len(data) > max_bytes:
                return None
            return data or None
        except OSError:
            logging.getLogger("app.rag.core.vision_reader").debug(
                "Skipping item after non-critical exception", exc_info=True
            )
            continue
    return None


def _minio_object_name_for_img_id(img_id: str, *, extension: str = "jpg") -> str | None:
    """
    Best-effort derive MinIO object_name from img_id.

    img_id format: "{tenant_id}:{dataset_id}:{document_id}:{chunk_key}"
    """
    raw = img_id.strip()
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
    if not settings.MINIO_ENABLED:
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
    img_id = meta.get("img_id")
    image_id = meta.get("image_id")

    if img_id and is_local_image_id(img_id):
        image_id = img_id
        img_id = None

    if img_id and ":" in img_id:
        try:
            image_tenant_id = UUID(img_id.split(":", 1)[0])
        except ValueError:
            return None, "invalid_image_tenant"
        if image_tenant_id != tenant_id:
            return None, "image_tenant_mismatch"

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
    except (OverflowError, TypeError, ValueError):
        page_i = None

    location = ""
    if doc_name and page_i is not None:
        location = f" (source: {doc_name}, page {page_i})"
    elif doc_name:
        location = f" (source: {doc_name})"
    elif page_i is not None:
        location = f" (page {page_i})"

    q = question.strip()
    return (
        "You are a careful technical document reader.\n"
        "Read the image and extract ONLY the information relevant to the user's question.\n"
        "- Focus on numbers, units, axis labels, legends, and key relationships.\n"
        "- If the image is a table, preserve row/column meaning.\n"
        "- If the image contains no relevant information, output exactly: NO_RELEVANT_INFO\n"
        "- Do not invent values.\n"
        f"\nUser question{location}:\n{q}\n"
    )


def _vision_llm_request_target() -> tuple[str, str, dict[str, str]]:
    api_key = settings.VISION_LLM_API_KEY.strip() or settings.LLM_API_KEY.strip()
    api_base = settings.VISION_LLM_API_BASE.strip() or settings.LLM_API_BASE.strip()
    model = settings.VISION_LLM_MODEL.strip()
    if not api_key or not api_base or not model:
        raise RuntimeError("vision_llm_not_configured")

    url = _chat_completions_url(api_base)
    if not url:
        raise RuntimeError("vision_llm_missing_api_base")

    return url, model, {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _resolve_max_tokens(max_tokens: int | None) -> int:
    if max_tokens is not None:
        return int(max_tokens)
    return settings.VISION_LLM_MAX_TOKENS


def _resolve_temperature(temperature: float | None) -> float:
    if temperature is not None:
        return float(temperature)
    return settings.VISION_LLM_TEMPERATURE


def _vision_llm_payload(
    *,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int | None,
    temperature: float | None,
    stream: bool,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": messages,
        "max_tokens": _resolve_max_tokens(max_tokens),
        "temperature": _resolve_temperature(temperature),
        "stream": stream,
    }


def _extract_stream_token(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or not stripped.startswith("data:"):
        return None
    payload = stripped[5:].strip()
    if not payload:
        return None
    if payload == "[DONE]":
        return ""
    event = json.loads(payload)
    if not isinstance(event, dict):
        raise TypeError("Vision stream event must be an object")
    if "error" in event:
        raise RuntimeError(f"vision_llm_stream_error:{str(event['error'])[:200]}")
    choices = event["choices"]
    if not isinstance(choices, list):
        raise TypeError("Vision stream choices must be a list")
    if not choices:
        return None
    delta = choices[0]["delta"]
    if not isinstance(delta, dict):
        raise TypeError("Vision stream delta must be an object")
    token = delta.get("content")
    if token is None:
        return None
    if not isinstance(token, str):
        raise TypeError("Vision stream content must be text")
    return token or None


async def _describe_with_vision_llm(
    *,
    http_client: httpx.AsyncClient,
    image_bytes: bytes,
    prompt: str,
) -> str:
    url, model, headers = _vision_llm_request_target()
    image_block = build_image_url_block(image_bytes)

    payload = _vision_llm_payload(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    image_block,
                ],
            }
        ],
        max_tokens=None,
        temperature=None,
        stream=False,
    )

    timeout = float(settings.VISION_LLM_TIMEOUT_SEC)
    resp = await http_client.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"vision_llm_http_{resp.status_code}:{(resp.text)[:200]}")

    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(block["text"] for block in content if block["type"] == "text").strip()
    raise TypeError("Vision response content must be text or text blocks")


async def build_vision_image_blocks(
    *,
    image_docs: list[Document],
    tenant_id: UUID | None,
    max_images: int,
    max_image_bytes: int,
) -> tuple[list[VisionImageBlock], dict[str, Any]]:
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
        "max_images": max_images_i,
        "max_image_bytes": max_bytes_i,
    }

    if not image_docs or max_images_i <= 0:
        return [], meta

    blocks: list[VisionImageBlock] = []
    errors: list[str] = []
    batch = image_docs[:max_images_i]
    for doc in batch:
        raw_bytes, loader_reason = await _load_image_bytes(
            meta=doc.metadata, tenant_id=tenant_id, max_bytes=max_bytes_i
        )
        if not raw_bytes:
            _append_vision_reader_error(errors=errors, error=f"skip:{loader_reason}")
            continue

        blocks.append(build_image_url_block(raw_bytes))

    meta.update(
        {
            "attempted": len(batch),
            "succeeded": len(blocks),
            "skipped": len(batch) - len(blocks),
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
    url, model, headers = _vision_llm_request_target()
    payload = _vision_llm_payload(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        stream=True,
    )

    timeout = float(settings.VISION_LLM_TIMEOUT_SEC)

    async with http_client.stream("POST", url, json=payload, headers=headers, timeout=timeout) as resp:
        if resp.status_code != 200:
            body = await resp.aread()
            raise RuntimeError(f"vision_llm_http_{resp.status_code}:{(body or b'')[:200].decode('utf-8', 'ignore')}")

        async for line in resp.aiter_lines():
            token = _extract_stream_token(line)
            if token is None:
                continue
            if token == "":
                break
            yield token


def _vision_reader_limits() -> _VisionReaderLimits:
    return _VisionReaderLimits(
        max(0, settings.VISION_RAG_READER_MAX_IMAGES),
        max(1, settings.VISION_RAG_READER_MAX_IMAGE_BYTES),
        max(0, settings.VISION_RAG_READER_MAX_OUTPUT_CHARS),
    )


def _truncate_vision_reader_text(*, text: str, max_output_chars: int) -> str:
    if max_output_chars and len(text) > max_output_chars:
        return text[:max_output_chars].rstrip() + "\n\n(truncated)"
    return text


def _build_vision_reader_doc(*, doc: Document, meta: dict[str, Any], text: str) -> Document:
    origin_chunk_id = doc.id if doc.id is not None else meta.get("chunk_id")
    vision_origin = str(uuid.uuid4()) if origin_chunk_id is None else origin_chunk_id
    vision_chunk_id = _stable_vision_reader_chunk_id(vision_origin)
    new_meta: dict[str, Any] = dict(meta)
    new_meta.update(
        {
            "retrieval_role": "vision_reader",
            "doc_type_kwd": "image",
            "origin_chunk_id": origin_chunk_id,
            "neighbor_of": origin_chunk_id,
        }
    )
    return Document(page_content=text, metadata=new_meta, id=vision_chunk_id)


def _vision_reader_preflight(
    *,
    image_docs: list[Document],
) -> tuple[dict[str, Any], _VisionReaderLimits | None]:
    enabled = settings.VISION_RAG_READER_ENABLED
    meta: dict[str, Any] = {"enabled": enabled, "used": False, "reason": "not_run"}
    if not enabled:
        meta["reason"] = "VISION_RAG_READER_ENABLED=false"
        return meta, None
    if not settings.VISION_LLM_ENABLED:
        meta["reason"] = "VISION_LLM_ENABLED=false"
        return meta, None
    if not image_docs:
        meta["reason"] = "no_image_docs"
        return meta, None
    limits = _vision_reader_limits()
    if limits.max_images <= 0:
        meta["reason"] = "max_images=0"
        return meta, None
    return meta, limits


def _append_vision_reader_error(*, errors: list[str], error: str | None) -> None:
    if error and len(errors) < 5:
        errors.append(error)


async def _build_vision_reader_docs(
    *,
    image_docs: list[Document],
    question: str,
    tenant_id: UUID | None,
    http_client: httpx.AsyncClient,
    max_images: int,
    max_image_bytes: int,
    max_output_chars: int,
) -> tuple[list[Document], int, int, int, list[str]]:
    errors: list[str] = []
    out: list[Document] = []
    batch = image_docs[:max_images]
    for doc in batch:
        vision_doc, error = await _vision_reader_context_doc(
            doc=doc,
            question=question,
            tenant_id=tenant_id,
            http_client=http_client,
            max_image_bytes=max_image_bytes,
            max_output_chars=max_output_chars,
        )
        if vision_doc is None:
            _append_vision_reader_error(errors=errors, error=error)
            continue
        out.append(vision_doc)
    return out, len(batch), len(out), len(batch) - len(out), errors


async def _vision_reader_context_doc(
    *,
    doc: Document,
    question: str,
    tenant_id: UUID | None,
    http_client: httpx.AsyncClient,
    max_image_bytes: int,
    max_output_chars: int,
) -> tuple[Document | None, str | None]:
    meta = doc.metadata
    raw_bytes, loader_reason = await _load_image_bytes(meta=meta, tenant_id=tenant_id, max_bytes=max_image_bytes)
    if not raw_bytes:
        return None, f"skip:{loader_reason}"

    prompt = _build_prompt(question=question, meta=meta)
    try:
        extracted = await _describe_with_vision_llm(
            http_client=http_client,
            image_bytes=raw_bytes,
            prompt=prompt,
        )
    except Exception as exc:  # noqa: BLE001
        return None, f"vision_exception:{str(exc)[:120]}"

    text = (extracted).strip()
    if not text or text == "NO_RELEVANT_INFO":
        return None, None
    text = _truncate_vision_reader_text(text=text, max_output_chars=max_output_chars)
    return _build_vision_reader_doc(doc=doc, meta=meta, text=text), None


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
    meta, limits = _vision_reader_preflight(image_docs=image_docs)
    if limits is None:
        return [], meta
    max_images, max_image_bytes, max_output_chars = limits
    out, attempted, succeeded, skipped, errors = await _build_vision_reader_docs(
        image_docs=image_docs,
        question=question,
        tenant_id=tenant_id,
        http_client=http_client,
        max_images=max_images,
        max_image_bytes=max_image_bytes,
        max_output_chars=max_output_chars,
    )

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
            "attempted": attempted,
            "succeeded": succeeded,
            "skipped": skipped,
            "returned": len(out),
            "max_images": max_images,
            "max_image_bytes": max_image_bytes,
            "max_output_chars": max_output_chars,
            "errors": errors,
            "model": settings.VISION_LLM_MODEL,
        }
    )
    return out, meta


__all__ = [
    "build_vision_image_blocks",
    "build_vision_reader_context_docs",
    "stream_vision_chat_completions_tokens",
]
