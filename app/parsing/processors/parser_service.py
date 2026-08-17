"""
Unified document parsing entry point:
- Route by file type (office/html -> auto/Pandoc/MarkItDown; PDF -> score then choose the best backend)
- Extract Markdown, save images to disk, and return preview
"""

import base64
import hashlib
import re
import uuid
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote
from uuid import UUID

from langchain_core.documents import Document

from app.core.config import settings
from app.core.constants import NON_CRITICAL_EXCEPTION_LOG_MESSAGE
from app.core.optional_deps import optional_import
from app.parsing.backends import normalize_parser_backend
from app.parsing.factory import parser_factory
from app.parsing.routing import route_pdf_backend
from app.rag.core.logging import get_logger
from app.services.document_preview_utils import (
    PREVIEW_HTML_IMAGE_REF_RE,
    PREVIEW_MD_IMAGE_REF_RE,
    _preview_content_image_refs,
    _preview_doc_asset_base_dir,
    _preview_local_image_limits,
    _write_preview_owner_binding,
)

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _get_pil_image():  # noqa: ANN202
    # Cache to avoid repeated warnings during large ingests when Pillow isn't installed.
    return optional_import("PIL.Image", feature="parse_preview_inline_images", pip_name="Pillow")


def _rewrite_preview_image_refs(
    content: str,
    md_pat: re.Pattern[str],
    html_pat: re.Pattern[str],
    replacements: dict[str, str],
) -> str:
    def _md_repl(match: re.Match[str]) -> str:
        raw = match.group(1) or ""
        new = replacements.get(raw.strip())
        if not new:
            return match.group(0)
        return match.group(0).replace(raw, new, 1)

    def _html_repl(match: re.Match[str]) -> str:
        raw = match.group(1) or ""
        new = replacements.get(raw.strip())
        if not new:
            return match.group(0)
        return match.group(0).replace(raw, new, 1)

    rewritten = md_pat.sub(_md_repl, content)
    return html_pat.sub(_html_repl, rewritten or "")


def _preview_images_dir(tenant_id: UUID) -> Path:
    images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    return images_dir


def _preview_ref_skippable(ref: str) -> bool:
    ref_lower = ref.lower()
    ref_scheme = ref.split(":", 1)[0].lower()
    return (
        ref_scheme in {"http", "https", "data", "blob"}
        or "/api/v1/documents/image-url/" in ref_lower
        or "/api/v1/documents/image/" in ref_lower
    )


def _preview_ref_candidates(ref: str) -> list[str]:
    ref_path = ref.split("?", 1)[0].split("#", 1)[0].strip()
    if not ref_path:
        return []

    try:
        ref_path_decoded = unquote(ref_path)
    except Exception:
        ref_path_decoded = ref_path

    candidates = [ref_path_decoded]
    if ref_path_decoded.startswith("/") and not ref_path_decoded.startswith("/api/"):
        candidates.insert(0, ref_path_decoded.lstrip("/"))
    return candidates


def _resolve_preview_local_image_path(ref: str, *, base_dir_resolved: Path) -> Path | None:
    ref_stripped = ref.strip()
    if not ref_stripped or _preview_ref_skippable(ref_stripped):
        return None

    for candidate in _preview_ref_candidates(ref_stripped):
        if not candidate:
            continue
        try:
            path_obj = Path(candidate)
            path_obj = (
                path_obj.resolve(strict=False)
                if path_obj.is_absolute()
                else (base_dir_resolved / path_obj).resolve(strict=False)
            )
            path_obj.relative_to(base_dir_resolved)
            if path_obj.exists() and path_obj.is_file():
                return path_obj
        except Exception:
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
    return None


def _read_preview_local_image(path: Path, *, max_image_bytes: int) -> tuple[bytes, str] | None:
    try:
        if path.stat().st_size > max_image_bytes:
            return None
    except Exception:
        get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
        return None

    try:
        raw_bytes = path.read_bytes()
    except Exception:
        get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
        return None

    if not raw_bytes or len(raw_bytes) > max_image_bytes:
        return None
    return raw_bytes, path.suffix.lower()


def _convert_preview_local_image(
    raw_bytes: bytes,
    *,
    ext: str,
    pil_image: object | None,
    pillow_ok: bool,
) -> tuple[bytes, str] | None:
    supported_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
    out_ext = ext if ext in supported_exts else ".jpg"
    if out_ext != ".jpg" or ext in supported_exts:
        return raw_bytes, out_ext
    if not pillow_ok or pil_image is None:
        return None

    try:
        img = pil_image.open(BytesIO(raw_bytes))  # type: ignore[attr-defined]
        try:
            if getattr(img, "mode", None) != "RGB":
                img = img.convert("RGB")
        except Exception as exc:
            logger.debug("Ignoring preview image mode normalization failure: %s", exc)
        out = BytesIO()
        img.save(out, format="JPEG", quality=85, optimize=True)
        return out.getvalue(), out_ext
    except Exception:
        get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
        return None


def _persist_preview_local_image(
    image_bytes: bytes,
    *,
    out_ext: str,
    images_dir: Path,
    owner_binding: dict[str, str] | None,
    digest_cache: dict[str, tuple[str, str]],
) -> tuple[str, str] | None:
    digest = hashlib.sha256(image_bytes).hexdigest()
    cached = digest_cache.get(digest)
    if cached:
        return cached

    preview_id = uuid.uuid4().hex
    out_path = images_dir / f"{preview_id}{out_ext}"
    try:
        out_path.write_bytes(image_bytes)
        _write_preview_owner_binding(
            images_dir=images_dir,
            preview_id=preview_id,
            binding=owner_binding,
        )
    except Exception:
        get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
        return None

    digest_cache[digest] = (preview_id, out_ext)
    return preview_id, out_ext


def _saved_preview_image_payload(*, preview_id: str, out_ext: str, images_dir: Path) -> dict[str, str]:
    return {
        "id": preview_id,
        "filename": f"{preview_id}{out_ext}",
        "path": str(images_dir / f"{preview_id}{out_ext}"),
        "url": f"/api/v1/documents/image/{preview_id}",
    }


def _preview_doc_content_and_base_dir(doc: Document) -> tuple[str, Path] | None:
    content = doc.page_content or ""
    if not isinstance(content, str) or not content:
        return None

    lowered = content.lower()
    if "![" not in lowered and "<img" not in lowered:
        return None

    base_dir_resolved = _preview_doc_asset_base_dir(doc)
    if base_dir_resolved is None:
        return None

    return content, base_dir_resolved


def _preview_materialized_ref(
    ref: str,
    *,
    base_dir_resolved: Path,
    max_image_bytes: int,
    pil_image: object | None,
    pillow_ok: bool,
    images_dir: Path,
    owner_binding: dict[str, str] | None,
    digest_cache: dict[str, tuple[str, str]],
) -> tuple[str, tuple[str, str] | None] | None:
    resolved_path = _resolve_preview_local_image_path(ref, base_dir_resolved=base_dir_resolved)
    if resolved_path is None:
        return None

    image_payload = _read_preview_local_image(resolved_path, max_image_bytes=max_image_bytes)
    if image_payload is None:
        return None

    converted = _convert_preview_local_image(
        image_payload[0],
        ext=image_payload[1],
        pil_image=pil_image,
        pillow_ok=pillow_ok,
    )
    if converted is None:
        return None

    persisted = _persist_preview_local_image(
        converted[0],
        out_ext=converted[1],
        images_dir=images_dir,
        owner_binding=owner_binding,
        digest_cache=digest_cache,
    )
    if persisted is None:
        return None

    return f"/api/v1/documents/image/{persisted[0]}", persisted


def _materialize_preview_doc_local_images(
    doc: Document,
    *,
    images_dir: Path,
    owner_binding: dict[str, str] | None,
    max_inline_images: int,
    max_image_bytes: int,
    pil_image: object | None,
    pillow_ok: bool,
    digest_cache: dict[str, tuple[str, str]],
    seen_saved_ids: set[str],
) -> list[dict[str, str]]:
    doc_context = _preview_doc_content_and_base_dir(doc)
    if doc_context is None:
        return []
    content, base_dir_resolved = doc_context

    found = _preview_content_image_refs(content)
    if max_inline_images and len(found) > max_inline_images:
        found = found[:max_inline_images]
    if not found:
        return []

    replacements: dict[str, str] = {}
    saved_images: list[dict[str, str]] = []

    for ref in found:
        materialized = _preview_materialized_ref(
            ref,
            base_dir_resolved=base_dir_resolved,
            max_image_bytes=max_image_bytes,
            pil_image=pil_image,
            pillow_ok=pillow_ok,
            images_dir=images_dir,
            owner_binding=owner_binding,
            digest_cache=digest_cache,
        )
        if materialized is None:
            continue

        url, persisted = materialized
        preview_id, out_ext = persisted
        if preview_id not in seen_saved_ids:
            seen_saved_ids.add(preview_id)
            saved_images.append(
                _saved_preview_image_payload(
                    preview_id=preview_id,
                    out_ext=out_ext,
                    images_dir=images_dir,
                )
            )
        replacements[ref] = url

    if replacements:
        doc.page_content = _rewrite_preview_image_refs(
            content,
            PREVIEW_MD_IMAGE_REF_RE,
            PREVIEW_HTML_IMAGE_REF_RE,
            replacements,
        )

    return saved_images


class DocumentParserService:
    def _materialize_local_images_for_preview(
        self,
        documents: list[Document],
        tenant_id: UUID,
        *,
        owner_binding: dict[str, str] | None,
    ) -> list[dict]:
        """
        Rewrite local/relative image references in Markdown/HTML into preview-time
        `/api/v1/documents/image/{uuid}` URLs.

        This covers parsers that output markdown such as:
        - ![](images/xxx.png)
        - <img src="images/xxx.png">

        The referenced files must live under metadata["asset_base_dir"] for the doc.
        """
        if not documents:
            return []

        images_dir = _preview_images_dir(tenant_id)
        max_inline_images, max_image_bytes = _preview_local_image_limits()
        digest_cache: dict[str, tuple[str, str]] = {}
        saved_images: list[dict] = []
        seen_saved_ids: set[str] = set()

        pil_image = _get_pil_image()
        pillow_ok = pil_image is not None

        for doc in documents:
            saved_images.extend(
                _materialize_preview_doc_local_images(
                    doc,
                    images_dir=images_dir,
                    owner_binding=owner_binding,
                    max_inline_images=max_inline_images,
                    max_image_bytes=max_image_bytes,
                    pil_image=pil_image,
                    pillow_ok=pillow_ok,
                    digest_cache=digest_cache,
                    seen_saved_ids=seen_saved_ids,
                )
            )

        return saved_images

    def parse_for_preview(
        self,
        file_path: Path,
        tenant_id: UUID,
        account_id: str | None = None,
        parser_backend: str | None = None,
    ) -> dict:
        """
        Parse file and return Markdown plus image list (no persistence).
        """
        file_ext = file_path.suffix.lower()
        is_pdf = file_ext == ".pdf"
        pdf_quality = None
        requested_backend = normalize_parser_backend(parser_backend)
        explicit_pdf_backend = bool(is_pdf and requested_backend and requested_backend != "auto")

        # Score PDF and choose parser.
        if is_pdf:
            parser_backend, pdf_quality = route_pdf_backend(
                file_path,
                parser_backend,
                sample_pages=3,
                use_ocr_validation=settings.RAPIDOCR_ENABLED,
            )
        else:
            # Non-PDF: route by backend (auto prefers Pandoc/Excel when enabled).
            parser_backend = parser_backend or "auto"

        documents, resolved_backend = parser_factory.parse(
            file_path,
            parser_backend=parser_backend,
            tenant_id=str(tenant_id),
            account_id=str(account_id or "").strip() or None,
            pdf_quality=pdf_quality,
            allow_fallback=not explicit_pdf_backend,
        )
        owner_account_id = str(account_id or "").strip()
        owner_binding = {"tenant_id": str(tenant_id), "account_id": owner_account_id} if owner_account_id else None
        local_images = self._materialize_local_images_for_preview(
            documents,
            tenant_id,
            owner_binding=owner_binding,
        )
        markdown_text = self._merge_documents(documents)

        images = self._extract_and_save_inline_images(
            markdown_text,
            tenant_id,
            owner_binding=owner_binding,
        )
        if images:
            # Replace data URIs with local references.
            for img in images:
                markdown_text = markdown_text.replace(img["original"], img["markdown_ref"])

        return {
            "backend": resolved_backend,
            "pdf_quality": pdf_quality,
            "markdown": markdown_text,
            "images": [
                {
                    "id": img["id"],
                    "url": img["url"],
                    "filename": img["filename"],
                }
                for img in [*local_images, *images]
            ],
        }

    def _merge_documents(self, documents: list[Document]) -> str:
        parts = []
        for doc in documents:
            text = doc.page_content or ""
            parts.append(text.strip())
        return "\n\n".join(p for p in parts if p)

    def _extract_and_save_inline_images(
        self,
        markdown_text: str,
        tenant_id: UUID,
        *,
        owner_binding: dict[str, str] | None,
    ) -> list[dict]:
        """
        Find data URI images, save to uploads/{tenant_id}/images, and return mapping info.
        """
        images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        pattern = re.compile(r"!\[[^\]]*\]\((data:image\/[a-zA-Z0-9+\/;=,:.-]+)\)")
        matches = list(pattern.finditer(markdown_text))

        max_inline_images = max(0, int(getattr(settings, "MAX_INLINE_IMAGES", 0) or 0))
        if max_inline_images and len(matches) > max_inline_images:
            matches = matches[:max_inline_images]
        max_image_bytes = int(getattr(settings, "MAX_INLINE_IMAGE_BYTES", 10_000_000) or 10_000_000)
        max_image_bytes = max(1_000_000, max_image_bytes)

        saved = []
        for m in matches:
            data_uri = m.group(1)
            img_id = uuid.uuid4().hex
            ext = "png"
            try:
                mm = re.match(r"^data:image/([a-zA-Z0-9.+-]+);base64,", data_uri)
                if mm:
                    fmt = (mm.group(1) or "").strip().lower()
                    if fmt in {"jpg", "jpeg"}:
                        ext = "jpg"
                    elif fmt in {"png", "webp", "gif", "bmp"}:
                        ext = fmt
            except Exception:
                ext = "png"

            filename = f"{img_id}.{ext}"
            file_path = images_dir / filename

            try:
                b64_part = data_uri.split("base64,")[-1]
                if len(b64_part) > int(max_image_bytes * 4 / 3) + 32:
                    continue
                binary = base64.b64decode(b64_part)
                if len(binary) > max_image_bytes:
                    continue
                file_path.write_bytes(binary)
                _write_preview_owner_binding(
                    images_dir=images_dir,
                    preview_id=img_id,
                    binding=owner_binding,
                )
            except Exception:
                get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
                continue

            url = f"/api/v1/documents/image/{img_id}"
            markdown_ref = f"![image]({url})"
            saved.append(
                {
                    "id": img_id,
                    "filename": filename,
                    "path": str(file_path),
                    "url": url,
                    "original": data_uri,
                    "markdown_ref": markdown_ref,
                }
            )

        return saved


document_parser_service = DocumentParserService()
