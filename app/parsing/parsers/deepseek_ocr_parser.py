"""
DeepSeek OCR parser (SiliconFlow API).

This backend converts PDF pages into images and uses DeepSeek-OCR to return
Markdown. Intended for scanned PDFs or image-heavy documents.
"""

import base64
import hashlib
import re
import shutil
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote

import fitz  # PyMuPDF
import requests
from langchain_core.documents import Document
from PIL import Image

from app.core.config import settings
from app.core.constants import NON_CRITICAL_EXCEPTION_LOG_MESSAGE
from app.rag.core.logging import get_logger

logger = get_logger("parsing.deepseek_ocr")

_DEEPSEEK_OCR_FALLBACK_LOG_MESSAGE = "Ignoring non-critical DeepSeek OCR fallback failure: %s"

_TAG_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"<\|ref\|>.*?<\|/ref\|>", re.DOTALL),
    re.compile(r"<\|det\|>.*?<\|/det\|>", re.DOTALL),
)

_MARKDOWN_IMAGE_REF_RE = re.compile(
    r"!\[[^\]]*\]\(\s*(?:<)?([^)\s>]+)(?:>)?(?:\s+['\"][^'\"]*['\"])?\s*\)",
    flags=re.IGNORECASE,
)
_HTML_IMAGE_REF_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", flags=re.IGNORECASE)


class DeepSeekOCRParser:
    """
    DeepSeek OCR parser via SiliconFlow (OpenAI-compatible chat completions).

    Config via env/.env:
    - DEEPSEEK_OCR_ENABLED=true
    - SILICONFLOW_API_KEY=...
    - SILICONFLOW_API_BASE=https://api.siliconflow.cn/v1
    - DEEPSEEK_OCR_MODEL=deepseek-ai/DeepSeek-OCR
    """

    def __init__(self) -> None:
        self._api_key = (getattr(settings, "SILICONFLOW_API_KEY", "") or "").strip()
        self._api_base = (getattr(settings, "SILICONFLOW_API_BASE", "") or "https://api.siliconflow.cn/v1").strip()
        self._model = (getattr(settings, "DEEPSEEK_OCR_MODEL", "") or "deepseek-ai/DeepSeek-OCR").strip()

        self._timeout_sec = float(getattr(settings, "DEEPSEEK_OCR_TIMEOUT_SEC", 120) or 120)
        self._max_tokens = int(getattr(settings, "DEEPSEEK_OCR_MAX_TOKENS", 4096) or 4096)
        self._temperature = float(getattr(settings, "DEEPSEEK_OCR_TEMPERATURE", 0.1) or 0.1)
        self._pdf_dpi = int(getattr(settings, "DEEPSEEK_OCR_PDF_DPI", 200) or 200)

        base = self._api_base.rstrip("/")
        # Allow users to pass either ".../v1" or the full ".../v1/chat/completions".
        self._api_url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"

        if not self._api_key:
            raise RuntimeError(
                "DeepSeek OCR requires SILICONFLOW_API_KEY. "
                "Set DEEPSEEK_OCR_ENABLED=true and configure SILICONFLOW_API_KEY."
            )

        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        # Thread-local sessions allow safe connection reuse when page OCR runs in parallel.
        self._session_local = threading.local()

    def _get_session(self) -> requests.Session:
        session = getattr(self._session_local, "session", None)
        if isinstance(session, requests.Session):
            return session
        session = requests.Session()
        self._session_local.session = session
        return session

    def _build_artifact_root(self, file_path: Path, document_id: str | None) -> Path:
        run_id = (document_id or file_path.stem or "deepseek_ocr").strip()
        run_id = re.sub(r"[^a-zA-Z0-9._-]+", "_", run_id)[:120] or "deepseek_ocr"
        return (file_path.parent / ".deepseek_ocr" / run_id).absolute()

    @staticmethod
    def _normalize_image_ext(ext: str) -> str:
        normalized = (ext or "").strip().lower()
        return "jpg" if normalized == "jpeg" else normalized

    @staticmethod
    def _write_if_missing(path: Path, data: bytes) -> bool:
        if path.exists():
            return True
        try:
            path.write_bytes(data)
        except Exception:
            return False
        return True

    @staticmethod
    def _unique_xrefs(doc: fitz.Document) -> list[int]:
        seen_xrefs: set[int] = set()
        xrefs: list[int] = []
        for page in doc:
            try:
                imgs = page.get_images(full=True) or []
            except Exception:
                imgs = []
            for img in imgs:
                if not img:
                    continue
                xref = img[0]
                if not isinstance(xref, int) or xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                xrefs.append(xref)
        return xrefs

    def _extract_pdf_image_payload(self, doc: fitz.Document, *, xref: int) -> tuple[bytes | None, str]:
        try:
            extracted = doc.extract_image(xref) or {}
        except Exception:
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
            return None, ""
        raw = extracted.get("image")
        if not raw:
            return None, ""
        return raw, self._normalize_image_ext(str(extracted.get("ext") or "")) or "bin"

    def _persist_jpeg_aliases(self, *, images_dir: Path, digest: str, jpg_bytes: bytes) -> None:
        for suffix in ("jpg", "jpeg"):
            path = images_dir / f"{digest}.{suffix}"
            if not self._write_if_missing(path, jpg_bytes):
                logger.debug(_DEEPSEEK_OCR_FALLBACK_LOG_MESSAGE, RuntimeError(f"write_failed:{path.name}"))

    def _persist_converted_jpeg_variants(self, *, images_dir: Path, raw: bytes, ext: str, digest_raw: str) -> None:
        if ext in {"jpg", "jpeg"}:
            return
        try:
            img_obj = Image.open(BytesIO(raw))
            try:
                if getattr(img_obj, "mode", None) != "RGB":
                    img_obj = img_obj.convert("RGB")
                out = BytesIO()
                img_obj.save(out, format="JPEG", quality=85, optimize=True)
                jpg_bytes = out.getvalue()
            finally:
                try:
                    img_obj.close()
                except Exception as exc:
                    logger.debug(_DEEPSEEK_OCR_FALLBACK_LOG_MESSAGE, exc)
        except Exception as exc:
            logger.debug(_DEEPSEEK_OCR_FALLBACK_LOG_MESSAGE, exc)
            return

        self._persist_jpeg_aliases(images_dir=images_dir, digest=digest_raw, jpg_bytes=jpg_bytes)
        digest_jpg = hashlib.sha256(jpg_bytes).hexdigest()
        self._persist_jpeg_aliases(images_dir=images_dir, digest=digest_jpg, jpg_bytes=jpg_bytes)

    @staticmethod
    def _digest_bytes(data: bytes) -> str | None:
        try:
            return hashlib.sha256(data).hexdigest()
        except Exception:
            return None

    @staticmethod
    def _page_image_config(total_pages: int) -> tuple[bool, int, str, int]:
        include_page_images = bool(getattr(settings, "DEEPSEEK_OCR_INCLUDE_PAGE_IMAGES", True))
        max_page_images = int(getattr(settings, "DEEPSEEK_OCR_PAGE_IMAGE_MAX_PAGES", 0) or 0)
        page_image_format = (getattr(settings, "DEEPSEEK_OCR_PAGE_IMAGE_FORMAT", "jpg") or "jpg").strip().lower()
        if page_image_format not in {"png", "jpg", "jpeg"}:
            page_image_format = "jpg"
        concurrency = int(getattr(settings, "DEEPSEEK_OCR_CONCURRENCY", 1) or 1)
        concurrency = max(1, min(concurrency, max(1, total_pages)))
        return include_page_images, max_page_images, page_image_format, concurrency

    @staticmethod
    def _validated_pdf_path(file_path: Path) -> Path:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if path.suffix.lower() != ".pdf":
            raise ValueError("DeepSeek OCR currently supports PDF only")
        return path

    def _extract_pdf_images(self, doc: fitz.Document, *, images_dir: Path) -> int:
        """
        Extract embedded PDF images into `images_dir`.

        Why:
        DeepSeek OCR may emit markdown refs like `![](images/<sha256>.jpg)` similar to
        MinerU/MagicPDF. Without an `images/` folder, these refs become dead links.

        Strategy:
        - Save raw extracted bytes (for maximum hash compatibility)
        - Additionally, best-effort save a JPEG-converted variant for non-JPEG formats
          (covers models that normalize images to JPEG before hashing/output)
        """
        images_dir.mkdir(parents=True, exist_ok=True)

        max_images = int(getattr(settings, "ZIP_MAX_IMAGES", 0) or 0)
        max_images = max(0, max_images)

        written = 0
        for xref in self._unique_xrefs(doc):
            raw, ext = self._extract_pdf_image_payload(doc, xref=xref)
            if not raw:
                continue
            digest_raw = hashlib.sha256(raw).hexdigest()
            raw_path = images_dir / f"{digest_raw}.{ext}"
            if not self._write_if_missing(raw_path, raw):
                get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
                continue
            if ext == "jpg":
                self._persist_jpeg_aliases(images_dir=images_dir, digest=digest_raw, jpg_bytes=raw)
            self._persist_converted_jpeg_variants(images_dir=images_dir, raw=raw, ext=ext, digest_raw=digest_raw)
            written += 1
            if max_images and written >= max_images:
                return written

        return written

    def _persist_page_image_variants(self, *, pix: fitz.Pixmap, png_bytes: bytes, images_dir: Path) -> None:
        """
        Persist page-render images into `images_dir` using sha256-based filenames.

        Why:
        Some OCR models emit markdown refs like `images/<sha256>.jpg` based on the input
        page image bytes (or a normalized JPEG variant). By materializing these files,
        downstream preview/ingestion can resolve those refs without a custom `/images` route.
        """
        try:
            images_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return

        digest_png = self._digest_bytes(png_bytes)
        if digest_png is None:
            return

        try:
            jpg_bytes = pix.tobytes("jpg")
        except Exception:
            jpg_bytes = None

        self._write_if_missing(images_dir / f"{digest_png}.png", png_bytes)
        if jpg_bytes is None:
            return

        self._persist_jpeg_aliases(images_dir=images_dir, digest=digest_png, jpg_bytes=jpg_bytes)
        digest_jpg = self._digest_bytes(jpg_bytes)
        if digest_jpg is not None:
            self._persist_jpeg_aliases(images_dir=images_dir, digest=digest_jpg, jpg_bytes=jpg_bytes)

    def _persist_named_page_images(
        self,
        *,
        page_idx: int,
        pix: fitz.Pixmap,
        png_bytes: bytes,
        images_dir: Path,
    ) -> tuple[Path, Path]:
        """
        Persist stable filenames for page images so we can reference them in Markdown:
        - images/page_0001.png
        - images/page_0001.jpg
        """
        try:
            images_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return images_dir / f"page_{page_idx:04d}.png", images_dir / f"page_{page_idx:04d}.jpg"

        png_path = images_dir / f"page_{page_idx:04d}.png"
        if not png_path.exists():
            try:
                png_path.write_bytes(png_bytes)
            except Exception as exc:
                logger.debug(_DEEPSEEK_OCR_FALLBACK_LOG_MESSAGE, exc)

        jpg_path = images_dir / f"page_{page_idx:04d}.jpg"
        if not jpg_path.exists():
            try:
                jpg_bytes = pix.tobytes("jpg")
                jpg_path.write_bytes(jpg_bytes)
                jpeg_alias = images_dir / f"page_{page_idx:04d}.jpeg"
                if not jpeg_alias.exists():
                    try:
                        jpeg_alias.write_bytes(jpg_bytes)
                    except Exception as exc:
                        logger.debug(_DEEPSEEK_OCR_FALLBACK_LOG_MESSAGE, exc)
            except Exception as exc:
                logger.debug(_DEEPSEEK_OCR_FALLBACK_LOG_MESSAGE, exc)

        return png_path, jpg_path

    def _ensure_referenced_images_exist(
        self,
        *,
        markdown_text: str,
        images_dir: Path,
        page_png_path: Path | None = None,
        page_jpg_path: Path | None = None,
        page_png_bytes: bytes | None = None,
        page_jpg_bytes: bytes | None = None,
    ) -> None:
        """
        Best-effort: some OCR outputs reference `images/<hash>.jpg` but do not actually
        provide those files. To avoid dead links in preview/ingestion, materialize
        missing referenced files under the current artifact `images_dir`.

        Strategy:
        - Find Markdown `![]()` and HTML `<img src>` refs.
        - For local refs like `images/<name>.(jpg|png|...)`, ensure the file exists.
        - If missing, write the current page render as a placeholder image.
        """
        if not isinstance(markdown_text, str) or not markdown_text:
            return

        try:
            images_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return

        images_dir_resolved = images_dir.resolve(strict=False)
        refs = self._referenced_image_refs(markdown_text)
        max_images = max(0, int(getattr(settings, "MAX_INLINE_IMAGES", 0) or 0))
        if max_images:
            refs = refs[:max_images]
        for ref in refs:
            resolved = self._resolve_referenced_dest(
                ref=ref,
                images_dir=images_dir,
                images_dir_resolved=images_dir_resolved,
            )
            if resolved is None:
                continue
            dest_path, prefer = resolved
            self._copy_or_write_placeholder(
                dest_path,
                prefer=prefer,
                page_png_path=page_png_path,
                page_jpg_path=page_jpg_path,
                page_png_bytes=page_png_bytes,
                page_jpg_bytes=page_jpg_bytes,
            )

    def _referenced_image_refs(self, markdown_text: str) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()
        for pattern in (_MARKDOWN_IMAGE_REF_RE, _HTML_IMAGE_REF_RE):
            for match in pattern.finditer(markdown_text):
                ref = (match.group(1) or "").strip()
                if not ref or ref in seen:
                    continue
                seen.add(ref)
                found.append(ref)
        return found

    def _resolve_referenced_dest(
        self,
        *,
        ref: str,
        images_dir: Path,
        images_dir_resolved: Path,
    ) -> tuple[Path, str] | None:
        supported_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
        ref_lower = ref.lower()
        ref_scheme = ref.split(":", 1)[0].lower()
        if ref_scheme in {"http", "https", "data", "blob"} or ref_lower.startswith("/api/"):
            return None

        ref_path = ref.split("?", 1)[0].split("#", 1)[0].strip()
        if not ref_path:
            return None
        try:
            ref_path = unquote(ref_path)
        except Exception as exc:
            logger.debug(_DEEPSEEK_OCR_FALLBACK_LOG_MESSAGE, exc)

        rel = ref_path.lstrip("/")
        if not rel.lower().startswith("images/"):
            return None

        leaf = rel[7:]
        if not leaf or leaf.startswith(("/", "\\")):
            return None

        ext = Path(leaf).suffix.lower()
        if ext and ext not in supported_exts:
            return None

        dest_path = (images_dir / leaf).resolve(strict=False)
        try:
            dest_path.relative_to(images_dir_resolved)
        except Exception:
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
            return None
        if dest_path.exists():
            return None

        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
            return None
        return dest_path, ("jpg" if ext in {".jpg", ".jpeg"} else "png")

    def _copy_or_write_placeholder(
        self,
        dest: Path,
        *,
        prefer: str,
        page_png_path: Path | None,
        page_jpg_path: Path | None,
        page_png_bytes: bytes | None,
        page_jpg_bytes: bytes | None,
    ) -> None:
        if prefer == "jpg":
            if page_jpg_path and page_jpg_path.exists():
                try:
                    shutil.copyfile(page_jpg_path, dest)
                    return
                except Exception as exc:
                    logger.debug(_DEEPSEEK_OCR_FALLBACK_LOG_MESSAGE, exc)
            if page_jpg_bytes:
                try:
                    dest.write_bytes(page_jpg_bytes)
                except Exception as exc:
                    logger.debug(_DEEPSEEK_OCR_FALLBACK_LOG_MESSAGE, exc)
            return

        if page_png_path and page_png_path.exists():
            try:
                shutil.copyfile(page_png_path, dest)
                return
            except Exception as exc:
                logger.debug(_DEEPSEEK_OCR_FALLBACK_LOG_MESSAGE, exc)
        if page_png_bytes:
            try:
                dest.write_bytes(page_png_bytes)
            except Exception as exc:
                logger.debug(_DEEPSEEK_OCR_FALLBACK_LOG_MESSAGE, exc)

    @staticmethod
    def _page_jpg_bytes(pix: fitz.Pixmap) -> bytes | None:
        try:
            return pix.tobytes("jpg")
        except Exception:
            return None

    def _persist_page_assets(
        self, *, page_idx: int, pix: fitz.Pixmap, images_dir: Path
    ) -> tuple[bytes, Path, Path, bytes | None]:
        img_bytes = pix.tobytes("png")
        self._persist_page_image_variants(pix=pix, png_bytes=img_bytes, images_dir=images_dir)
        png_path, jpg_path = self._persist_named_page_images(
            page_idx=page_idx,
            pix=pix,
            png_bytes=img_bytes,
            images_dir=images_dir,
        )
        return img_bytes, png_path, jpg_path, self._page_jpg_bytes(pix)

    def _ensure_page_references(
        self,
        *,
        text: str,
        images_dir: Path,
        png_path: Path | None,
        jpg_path: Path | None,
        png_bytes: bytes | None = None,
        jpg_bytes: bytes | None = None,
    ) -> None:
        try:
            self._ensure_referenced_images_exist(
                markdown_text=text or "",
                images_dir=images_dir,
                page_png_path=png_path,
                page_jpg_path=jpg_path,
                page_png_bytes=png_bytes,
                page_jpg_bytes=jpg_bytes,
            )
        except Exception as exc:
            logger.debug(_DEEPSEEK_OCR_FALLBACK_LOG_MESSAGE, exc)

    def _process_pages_sequential(
        self,
        *,
        doc: fitz.Document,
        file_path: Path,
        total_pages: int,
        images_dir: Path,
    ) -> tuple[dict[int, str], list[str]]:
        results: dict[int, str] = {}
        for idx, page in enumerate(doc, start=1):
            pix = page.get_pixmap(dpi=self._pdf_dpi)
            img_bytes, png_path, jpg_path, page_jpg_bytes = self._persist_page_assets(
                page_idx=idx,
                pix=pix,
                images_dir=images_dir,
            )
            logger.info("[deepseek_ocr] page %s/%s (%s)", idx, total_pages, file_path.name)
            text = self._call_api(img_bytes, mime_type="image/png")
            self._ensure_page_references(
                text=text,
                images_dir=images_dir,
                png_path=png_path,
                jpg_path=jpg_path,
                png_bytes=img_bytes,
                jpg_bytes=page_jpg_bytes,
            )
            results[idx] = text or ""
        return results, []

    def _submit_page(
        self,
        *,
        executor: ThreadPoolExecutor,
        idx: int,
        page_obj: fitz.Page,
        total_pages: int,
        file_path: Path,
        images_dir: Path,
        inflight: dict,
        page_named_images: dict[int, tuple[Path, Path]],
    ) -> None:
        pix = page_obj.get_pixmap(dpi=self._pdf_dpi)
        img_bytes, png_path, jpg_path, _page_jpg_bytes = self._persist_page_assets(
            page_idx=idx,
            pix=pix,
            images_dir=images_dir,
        )
        page_named_images[idx] = (png_path, jpg_path)
        logger.info("[deepseek_ocr] page %s/%s (%s)", idx, total_pages, file_path.name)
        inflight[executor.submit(self._call_api, img_bytes, mime_type="image/png")] = idx

    def _collect_parallel_results(
        self,
        *,
        done,
        inflight: dict,
        results: dict[int, str],
        errors: list[str],
        page_named_images: dict[int, tuple[Path, Path]],
        images_dir: Path,
    ) -> None:
        for future in done:
            page_idx = inflight.pop(future, None)
            if page_idx is None:
                continue
            try:
                text = future.result() or ""
                results[page_idx] = text
                png_path, jpg_path = page_named_images.get(page_idx, (None, None))
                self._ensure_page_references(
                    text=text,
                    images_dir=images_dir,
                    png_path=png_path,
                    jpg_path=jpg_path,
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"page {page_idx}: {str(exc)[:200]}")

    def _process_pages_parallel(
        self,
        *,
        doc: fitz.Document,
        file_path: Path,
        total_pages: int,
        images_dir: Path,
        concurrency: int,
    ) -> tuple[dict[int, str], list[str]]:
        inflight: dict = {}
        results: dict[int, str] = {}
        errors: list[str] = []
        page_named_images: dict[int, tuple[Path, Path]] = {}
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            for idx, page in enumerate(doc, start=1):
                self._submit_page(
                    executor=executor,
                    idx=idx,
                    page_obj=page,
                    total_pages=total_pages,
                    file_path=file_path,
                    images_dir=images_dir,
                    inflight=inflight,
                    page_named_images=page_named_images,
                )
                if len(inflight) >= concurrency:
                    done, _pending = wait(inflight.keys(), return_when=FIRST_COMPLETED)
                    self._collect_parallel_results(
                        done=done,
                        inflight=inflight,
                        results=results,
                        errors=errors,
                        page_named_images=page_named_images,
                        images_dir=images_dir,
                    )
            if inflight:
                done_all, _ = wait(inflight.keys())
                self._collect_parallel_results(
                    done=done_all,
                    inflight=inflight,
                    results=results,
                    errors=errors,
                    page_named_images=page_named_images,
                    images_dir=images_dir,
                )
        return results, errors

    def _build_documents(
        self,
        *,
        file_path: Path,
        artifact_root: Path,
        total_pages: int,
        include_page_images: bool,
        max_page_images: int,
        page_image_format: str,
        extracted_images: int,
        concurrency: int,
        results: dict[int, str],
    ) -> list[Document]:
        docs: list[Document] = []
        ext = "png" if page_image_format == "png" else "jpg"
        for idx in range(1, total_pages + 1):
            text = (results.get(idx) or "").strip()
            page_parts: list[str] = []
            if include_page_images and (max_page_images <= 0 or idx <= max_page_images):
                page_parts.append(f"![page {idx}](images/page_{idx:04d}.{ext})")
            if text:
                page_parts.append(text)
            page_content = "\n\n".join(page_parts).strip()
            if not page_content:
                continue
            meta = {
                "source": file_path.name,
                "file_type": "pdf",
                "page": idx,
                "total_pages": total_pages,
                "parser_backend": "deepseek_ocr",
                "asset_base_dir": str(artifact_root),
                "artifact_dir": str(artifact_root),
                "deepseek_ocr_extracted_images": int(extracted_images),
                "deepseek_ocr_concurrency": int(concurrency),
            }
            docs.append(Document(page_content=page_content, metadata=meta))
        return docs

    def parse(
        self,
        file_path: Path,
        *,
        dataset_id: str | None = None,  # kept for interface parity
        document_id: str | None = None,
        tenant_id: str | None = None,  # kept for interface parity
        **_kwargs,
    ) -> list[Document]:
        _ = (dataset_id, tenant_id)
        file_path = self._validated_pdf_path(file_path)

        start = time.time()
        logger.info("[deepseek_ocr] start %s", file_path.name)

        artifact_root = self._build_artifact_root(file_path, document_id)
        images_dir = artifact_root / "images"
        artifact_root.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(file_path))
        try:
            total_pages = int(len(doc))
            include_page_images, max_page_images, page_image_format, concurrency = self._page_image_config(total_pages)

            extracted_images = 0
            try:
                extracted_images = self._extract_pdf_images(doc, images_dir=images_dir)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[deepseek_ocr] failed extracting PDF images: %s", str(exc)[:200])

            if concurrency <= 1:
                results, errors = self._process_pages_sequential(
                    doc=doc,
                    file_path=file_path,
                    total_pages=total_pages,
                    images_dir=images_dir,
                )
            else:
                results, errors = self._process_pages_parallel(
                    doc=doc,
                    file_path=file_path,
                    total_pages=total_pages,
                    images_dir=images_dir,
                    concurrency=concurrency,
                )

            if errors:
                raise RuntimeError(f"DeepSeek OCR failed: {errors[0]}")

            docs = self._build_documents(
                file_path=file_path,
                artifact_root=artifact_root,
                total_pages=total_pages,
                include_page_images=include_page_images,
                max_page_images=max_page_images,
                page_image_format=page_image_format,
                extracted_images=extracted_images,
                concurrency=concurrency,
                results=results,
            )
            logger.info("[deepseek_ocr] done %s in %.2fs", file_path.name, time.time() - start)
            return docs
        finally:
            doc.close()

    def _call_api(self, data_bytes: bytes, *, mime_type: str) -> str:
        encoded = base64.b64encode(data_bytes).decode("utf-8")
        data_url = f"data:{mime_type};base64,{encoded}"

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {
                        "type": "text",
                        "text": "<image>\n<|grounding|>Convert the document to markdown.",
                    },
                ],
            }
        ]

        payload = {
            "model": self._model,
            "messages": messages,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }

        resp = self._get_session().post(self._api_url, headers=self._headers, json=payload, timeout=self._timeout_sec)
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            raise RuntimeError(f"DeepSeek OCR API error {resp.status_code}: {resp.text[:500]}")

        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
        text = str(content).strip()
        for pattern in _TAG_PATTERNS:
            text = pattern.sub("", text)
        return text.strip()
