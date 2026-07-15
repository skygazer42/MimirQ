"""
Image embedding indexing + search (CLIP).

Design goals:
- Optional and fail-open: never block ingest/retrieval when image embedding deps are missing.
- PII-minimal: do not persist raw image bytes or OCR text; store only embeddings + stable ids/metadata.
- Deterministic-ish: indexing is stable given the same (image bytes, model, settings).
"""


import contextlib
import io
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.rag.core.metadata import normalize_image_metadata
from app.rag.embedding.clip_embedder import encode_clip_image, encode_clip_text
from app.storage.object.minio import MinIOService
from app.storage.vector.milvus import get_milvus_adapter, resolve_collection_name

logger = get_logger("rag.multimodal.clip")


@dataclass(frozen=True)
class ImageIndexStats:
    indexed: int = 0
    skipped: int = 0
    failed: int = 0
    dim: int = 0
    errors: list[str] | None = None


@dataclass(frozen=True)
class ImageSearchHit:
    chunk_id: str
    score: float
    metadata: dict[str, Any]


def _is_image_chunk(meta: dict[str, Any]) -> bool:
    doc_type = str(meta.get("doc_type_kwd") or "").strip().lower()
    if doc_type == "image":
        return True
    # Heuristic: many parsers store image refs even when doc_type_kwd is missing.
    return bool(meta.get("img_id") or meta.get("image_id") or meta.get("image_url") or meta.get("img_url"))


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


def _load_image_bytes_from_local(*, tenant_id: UUID, image_id: str, max_bytes: int) -> bytes | None:
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
                    logger.debug("Ignoring local image size check failure: %s", exc)
            with p.open("rb") as f:
                data = f.read(int(max_bytes) if int(max_bytes or 0) > 0 else -1)
            return data or None
        except Exception as exc:
            logger.debug("Ignoring local image load failure: %s", exc)
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


def _load_image_bytes_from_minio(*, img_id: str, max_bytes: int) -> bytes | None:
    if not bool(getattr(settings, "MINIO_ENABLED", False)):
        return None
    obj = _minio_object_name_for_img_id(img_id, extension="jpg")
    if not obj:
        return None
    svc = MinIOService()
    try:
        # Stream into memory with an optional max_bytes cap.
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


def _load_pil_image_from_bytes(raw: bytes) -> Any | None:
    if not raw:
        return None
    try:
        from PIL import Image as PILImage  # type: ignore

        img = PILImage.open(io.BytesIO(raw))
        # Force decode now so downstream embeds do not depend on open file handles.
        img.load()
        # Normalize mode to keep embeddings stable across formats.
        if getattr(img, "mode", None) not in {"RGB", "RGBA"}:
            img = img.convert("RGB")
        return img
    except Exception:
        return None


def _image_ref_from_chunk_meta(meta: dict[str, Any]) -> tuple[str | None, str | None]:
    """
    Return (img_id, image_id) best-effort from chunk metadata.
    """
    normalize_image_metadata(meta)
    img_id = str(meta.get("img_id") or "").strip() or None
    image_id = str(meta.get("image_id") or meta.get("img_id") or "").strip() or None
    # Prefer MinIO img_id when present; local image_id is preview-time only.
    if img_id:
        return img_id, None
    return None, image_id


def index_clip_image_embeddings_for_dataset(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    max_chunks: int = 3000,
    max_image_bytes: int | None = None,
    upsert: bool = True,
) -> ImageIndexStats:
    """
    Index CLIP embeddings for image chunks in a dataset into a Milvus collection.

    Notes:
    - Uses chunk_id as the vector primary key so results can be turned into citations.
    - Best-effort: skips chunks when images can't be loaded or embeddings fail.
    """
    if not bool(getattr(settings, "IMAGE_EMBEDDING_ENABLED", False)):
        return ImageIndexStats(indexed=0, skipped=0, failed=0, dim=0, errors=["IMAGE_EMBEDDING_ENABLED=false"])

    from app.models.document import Document as DBDocument  # noqa: WPS433
    from app.models.document import DocumentChunk  # noqa: WPS433

    limit = max(1, min(int(max_chunks or 0), 20_000))
    max_bytes = int(max_image_bytes) if max_image_bytes is not None else int(getattr(settings, "MINIO_IMAGE_MAX_BYTES", 0) or 0)
    # Fallback cap to keep memory bounded in case MINIO_IMAGE_MAX_BYTES is unset.
    if max_bytes <= 0:
        max_bytes = 10_000_000

    # Pull recent chunks first; image chunks tend to be sparse.
    rows = (
        db.query(DocumentChunk)
        .join(DBDocument, and_(DBDocument.id == DocumentChunk.document_id, DBDocument.tenant_id == DocumentChunk.tenant_id))
        .filter(DocumentChunk.tenant_id == tenant_id, DBDocument.dataset_id == dataset_id)
        .order_by(DocumentChunk.updated_at.desc().nullslast(), DocumentChunk.created_at.desc().nullslast())
        .limit(limit)
        .all()
    )

    collection = str(getattr(settings, "IMAGE_EMBEDDING_COLLECTION_NAME", "") or "").strip() or "image_chunks"
    adapter = get_milvus_adapter(collection_name=resolve_collection_name(collection), vector_field="embedding", text_field="content")

    items: list[dict[str, Any]] = []
    embeddings: list[list[float]] = []
    errors: list[str] = []

    indexed = 0
    skipped = 0
    failed = 0
    dim = 0

    for chunk in rows:
        meta = dict(getattr(chunk, "doc_metadata", None) or {})
        if not _is_image_chunk(meta):
            skipped += 1
            continue

        img_id, image_id = _image_ref_from_chunk_meta(meta)
        raw_bytes: bytes | None = None
        if img_id:
            raw_bytes = _load_image_bytes_from_minio(img_id=img_id, max_bytes=max_bytes)
        elif image_id:
            raw_bytes = _load_image_bytes_from_local(tenant_id=tenant_id, image_id=image_id, max_bytes=max_bytes)

        if not raw_bytes:
            skipped += 1
            continue

        pil = _load_pil_image_from_bytes(raw_bytes)
        if pil is None:
            skipped += 1
            continue

        vec = encode_clip_image(pil)
        if not vec:
            failed += 1
            continue

        if dim <= 0:
            dim = int(len(vec))

        chunk_id = getattr(chunk, "id", None)
        if chunk_id is None:
            skipped += 1
            continue

        normalize_image_metadata(meta)
        items.append(
            {
                "id": str(chunk_id),
                "content": "image",
                "metadata": {
                    "tenant_id": str(tenant_id),
                    "dataset_id": str(dataset_id),
                    "document_id": str(getattr(chunk, "document_id", "") or ""),
                    "chunk_id": str(chunk_id),
                    "chunk_index": int(getattr(chunk, "chunk_index", 0) or 0),
                    "page_number": int(getattr(chunk, "page_number", 0) or 0),
                    # Best-effort image refs for citations/UI.
                    "img_id": meta.get("img_id") or meta.get("image_id") or "",
                    "image_id": meta.get("image_id") or "",
                    "image_url": meta.get("image_url") or meta.get("img_url") or "",
                    "index_kind": "image",
                },
            }
        )
        embeddings.append(vec)

        indexed += 1
        # Batch insert size cap to avoid huge Milvus writes; flush opportunistically.
        if indexed % 256 == 0:
            try:
                adapter.add_vectors(items, embeddings=embeddings, upsert=bool(upsert))
            except Exception as exc:  # noqa: BLE001
                failed += len(items)
                errors.append(str(exc)[:200])
            items = []
            embeddings = []

    if items:
        try:
            adapter.add_vectors(items, embeddings=embeddings, upsert=bool(upsert))
        except Exception as exc:  # noqa: BLE001
            failed += len(items)
            errors.append(str(exc)[:200])

    return ImageIndexStats(
        indexed=int(indexed),
        skipped=int(skipped),
        failed=int(failed),
        dim=int(dim),
        errors=errors or None,
    )


def search_clip_images(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    query: str,
    top_k: int = 8,
    metadata_filter: dict[str, Any] | None = None,
) -> list[ImageSearchHit]:
    """
    Search image chunks by text query using CLIP (text->image embedding space).
    """
    _ = db
    if not bool(getattr(settings, "IMAGE_EMBEDDING_ENABLED", False)):
        return []

    q = str(query or "").strip()
    if not q:
        return []

    vec = encode_clip_text(q)
    if not vec:
        return []

    collection = str(getattr(settings, "IMAGE_EMBEDDING_COLLECTION_NAME", "") or "").strip() or "image_chunks"
    adapter = get_milvus_adapter(collection_name=resolve_collection_name(collection), vector_field="embedding", text_field="content")

    eff_filter = dict(metadata_filter or {})
    eff_filter.setdefault("tenant_id", str(tenant_id))
    eff_filter.setdefault("dataset_id", str(dataset_id))

    # Milvus metadata pushdown might not be available depending on schema; client-side filtering is enforced anyway.
    try:
        raw = adapter.search(query_vector=vec, top_k=max(1, min(int(top_k or 0), 50)), metadata_filter=eff_filter)
    except Exception as exc:  # noqa: BLE001
        logger.debug("CLIP image search failed (ignored): %s", str(exc)[:200])
        return []

    out: list[ImageSearchHit] = []
    for row in raw or []:
        cid = str(row.get("id") or "").strip()
        if not cid:
            continue
        meta = row.get("metadata")
        meta_d = meta if isinstance(meta, dict) else {}
        try:
            score = float(row.get("score") or 0.0)
        except Exception:
            score = 0.0
        out.append(ImageSearchHit(chunk_id=cid, score=score, metadata=dict(meta_d)))
    return out


def build_image_citations(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str | None = None,
    dataset_id: UUID,
    hits: list[ImageSearchHit],
    max_items: int = 12,
) -> list[dict[str, Any]]:
    """
    Convert image search hits into citation-like dicts (chunk-aware).
    """
    lim = max(0, int(max_items or 0))
    if lim <= 0 or not hits:
        return []

    from app.models.document import Document as DBDocument  # noqa: WPS433
    from app.models.document import DocumentChunk  # noqa: WPS433

    # Fetch chunk rows for stable citations and ACL/dataset scoping.
    want_ids: list[UUID] = []
    for h in hits[:lim]:
        with contextlib.suppress(Exception):
            want_ids.append(UUID(str(h.chunk_id)))
    if not want_ids:
        return []

    rows_q = (
        db.query(DocumentChunk, DBDocument.filename)
        .join(DBDocument, and_(DBDocument.id == DocumentChunk.document_id, DBDocument.tenant_id == DocumentChunk.tenant_id))
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.id.in_(want_ids),
            DBDocument.dataset_id == dataset_id,
        )
    )
    # Defense-in-depth: apply document-level ACL ("security trimming") when an account_id is available.
    if str(account_id or "").strip():
        from app.services.dataset_profile_service import build_dataset_documents_query  # noqa: WPS433

        _ds, doc_q = build_dataset_documents_query(
            db,
            tenant_id=tenant_id,
            account_id=str(account_id),
            dataset_id=dataset_id,
        )
        doc_ids_subq = doc_q.with_entities(DBDocument.id).subquery()
        rows_q = rows_q.filter(DBDocument.id.in_(select(doc_ids_subq.c.id)))

    rows = rows_q.all()
    by_id: dict[str, tuple[Any, str]] = {}
    for chunk, filename in rows:
        cid = getattr(chunk, "id", None)
        if cid is None:
            continue
        by_id[str(cid)] = (chunk, str(filename or "").strip())

    out: list[dict[str, Any]] = []
    for h in hits[:lim]:
        item = by_id.get(str(h.chunk_id))
        if item is None:
            continue
        row, filename = item
        meta = dict(getattr(row, "doc_metadata", None) or {})
        normalize_image_metadata(meta)
        doc_name = filename or str(meta.get("source") or "").strip() or str(getattr(row, "document_id", "") or "")
        out.append(
            {
                "document_id": str(getattr(row, "document_id", "") or ""),
                "document_name": doc_name,
                "chunk_id": str(getattr(row, "id", "") or ""),
                "chunk_index": int(getattr(row, "chunk_index", 0) or 0),
                "page_number": getattr(row, "page_number", None),
                # Keep content bounded; image chunks often have OCR/caption text.
                "chunk_content": str(getattr(row, "content", "") or "")[:2000],
                "relevance_score": float(h.score),
                "has_image": True,
                "img_id": meta.get("img_id") or None,
                "img_url": meta.get("img_url") or meta.get("image_url") or None,
                "image_id": meta.get("image_id") or None,
            }
        )
    return out
