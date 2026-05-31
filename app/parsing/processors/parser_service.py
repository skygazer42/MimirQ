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
from pathlib import Path
from uuid import UUID

from langchain_core.documents import Document

from app.core.config import settings
from app.core.optional_deps import optional_import
from app.parsing.backends import normalize_parser_backend
from app.parsing.factory import parser_factory
from app.parsing.routing import route_pdf_backend


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


class DocumentParserService:
    def _materialize_local_images_for_preview(self, documents: list[Document], tenant_id: UUID) -> list[dict]:
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

        images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        md_pat = re.compile(
            r"!\[[^\]]*\]\(\s*(?:<)?([^)\s>]+)(?:>)?(?:\s+['\"][^'\"]*['\"])?\s*\)",
            flags=re.IGNORECASE,
        )
        html_pat = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", flags=re.IGNORECASE)

        max_inline_images = max(0, int(getattr(settings, "MAX_INLINE_IMAGES", 0) or 0))
        max_image_bytes = int(getattr(settings, "MAX_INLINE_IMAGE_BYTES", 10_000_000) or 10_000_000)
        max_image_bytes = max(1_000_000, max_image_bytes)

        supported_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

        digest_cache: dict[str, tuple[str, str]] = {}
        saved_images: list[dict] = []
        seen_saved_ids: set[str] = set()

        from io import BytesIO

        pil_image = _get_pil_image()
        pillow_ok = pil_image is not None

        from urllib.parse import unquote

        for doc in documents:
            content = doc.page_content or ""
            if not isinstance(content, str) or not content:
                continue

            lowered = content.lower()
            if "![" not in lowered and "<img" not in lowered:
                continue

            meta = doc.metadata or {}
            base_dir_raw = meta.get("asset_base_dir") if isinstance(meta, dict) else None
            if not isinstance(base_dir_raw, str) or not base_dir_raw.strip():
                continue

            base_dir = Path(base_dir_raw.strip()).resolve(strict=False)
            if not base_dir.exists() or not base_dir.is_dir():
                continue
            base_dir_resolved = base_dir.resolve(strict=False)

            found: list[str] = []
            seen: set[str] = set()
            for pat in (md_pat, html_pat):
                for m in pat.finditer(content):
                    ref = (m.group(1) or "").strip()
                    if not ref or ref in seen:
                        continue
                    seen.add(ref)
                    found.append(ref)

            if not found:
                continue
            if max_inline_images and len(found) > max_inline_images:
                found = found[:max_inline_images]

            replacements: dict[str, str] = {}

            for ref in found:
                ref_stripped = ref.strip()
                if not ref_stripped:
                    continue

                ref_lower = ref_stripped.lower()
                ref_scheme = ref_stripped.split(":", 1)[0].lower()
                if ref_scheme in {"http", "https", "data", "blob"}:
                    continue
                if "/api/v1/documents/image-url/" in ref_lower or "/api/v1/documents/image/" in ref_lower:
                    continue

                ref_path = ref_stripped.split("?", 1)[0].split("#", 1)[0].strip()
                if not ref_path:
                    continue
                try:
                    ref_path_decoded = unquote(ref_path)
                except Exception:
                    ref_path_decoded = ref_path

                candidate_rel = []
                if ref_path_decoded.startswith("/") and not ref_path_decoded.startswith("/api/"):
                    candidate_rel.append(ref_path_decoded.lstrip("/"))
                candidate_rel.append(ref_path_decoded)

                resolved_path: Path | None = None
                for candidate in candidate_rel:
                    if not candidate:
                        continue
                    try:
                        path_obj = Path(candidate)
                        if not path_obj.is_absolute():
                            path_obj = (base_dir_resolved / path_obj).resolve(strict=False)
                        else:
                            path_obj = path_obj.resolve(strict=False)

                        try:
                            path_obj.relative_to(base_dir_resolved)
                        except Exception:
                            continue

                        if path_obj.exists() and path_obj.is_file():
                            resolved_path = path_obj
                            break
                    except Exception:
                        continue

                if resolved_path is None:
                    continue

                try:
                    if resolved_path.stat().st_size > max_image_bytes:
                        continue
                except Exception:
                    continue

                ext = resolved_path.suffix.lower()
                try:
                    raw_bytes = resolved_path.read_bytes()
                except Exception:
                    continue
                if not raw_bytes or len(raw_bytes) > max_image_bytes:
                    continue

                out_ext = ext if ext in supported_exts else ".jpg"
                image_bytes = raw_bytes

                if out_ext == ".jpg" and ext not in supported_exts:
                    if not pillow_ok:
                        continue
                    try:
                        img = pil_image.open(BytesIO(raw_bytes))  # type: ignore[arg-type]
                        try:
                            if getattr(img, "mode", None) != "RGB":
                                img = img.convert("RGB")
                        except Exception:
                            pass
                        out = BytesIO()  # type: ignore[call-arg]
                        img.save(out, format="JPEG", quality=85, optimize=True)
                        image_bytes = out.getvalue()
                    except Exception:
                        continue

                digest = hashlib.sha256(image_bytes).hexdigest()
                cached = digest_cache.get(digest)
                if cached:
                    preview_id, cached_ext = cached
                    out_ext = cached_ext
                else:
                    preview_id = uuid.uuid4().hex
                    out_path = images_dir / f"{preview_id}{out_ext}"
                    try:
                        out_path.write_bytes(image_bytes)
                    except Exception:
                        continue
                    digest_cache[digest] = (preview_id, out_ext)

                if preview_id not in seen_saved_ids:
                    seen_saved_ids.add(preview_id)
                    saved_images.append(
                        {
                            "id": preview_id,
                            "filename": f"{preview_id}{out_ext}",
                            "path": str(images_dir / f"{preview_id}{out_ext}"),
                            "url": f"/api/v1/documents/image/{preview_id}",
                        }
                    )

                url = f"/api/v1/documents/image/{preview_id}"
                replacements[ref] = url

            if not replacements:
                continue

            doc.page_content = _rewrite_preview_image_refs(content, md_pat, html_pat, replacements)

        return saved_images

    def parse_for_preview(
        self,
        file_path: Path,
        tenant_id: UUID,
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
            pdf_quality=pdf_quality,
            allow_fallback=not explicit_pdf_backend,
        )
        local_images = self._materialize_local_images_for_preview(documents, tenant_id)
        markdown_text = self._merge_documents(documents)

        images = self._extract_and_save_inline_images(markdown_text, tenant_id)
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

    def _extract_and_save_inline_images(self, markdown_text: str, tenant_id: UUID) -> list[dict]:
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
            except Exception:
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
