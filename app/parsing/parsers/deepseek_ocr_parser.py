"""
DeepSeek OCR parser (SiliconFlow API).

This backend converts PDF pages into images and uses DeepSeek-OCR to return
Markdown. Intended for scanned PDFs or image-heavy documents.
"""

from __future__ import annotations

import base64
import hashlib
import re
import shutil
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from urllib.parse import unquote

import fitz  # PyMuPDF
import requests
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("parsing.deepseek_ocr")


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

        # Best-effort: Pillow may be unavailable in minimal installs.
        from io import BytesIO

        try:
            from PIL import Image as pil_image  # type: ignore
        except ImportError:
            pil_image = None  # type: ignore[assignment]
            pillow_ok = False
        else:
            pillow_ok = True

        def normalize_ext(ext: str) -> str:
            e = (ext or "").strip().lower()
            if e == "jpeg":
                return "jpg"
            return e

        written = 0
        seen_xrefs: set[int] = set()

        for page in doc:
            try:
                imgs = page.get_images(full=True) or []
            except Exception:
                imgs = []

            for img in imgs:
                if not img:
                    continue
                xref = img[0]
                if not isinstance(xref, int):
                    continue
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)

                try:
                    extracted = doc.extract_image(xref) or {}
                except Exception:
                    continue
                raw = extracted.get("image")
                if not raw:
                    continue

                ext = normalize_ext(str(extracted.get("ext") or "")) or "bin"
                digest_raw = hashlib.sha256(raw).hexdigest()

                # Write raw bytes with the original extension.
                raw_path = images_dir / f"{digest_raw}.{ext}"
                if not raw_path.exists():
                    try:
                        raw_path.write_bytes(raw)
                    except Exception:
                        continue

                # Alias for jpg/jpeg to cover both reference styles.
                if ext == "jpg":
                    alias = images_dir / f"{digest_raw}.jpeg"
                    if not alias.exists():
                        try:
                            alias.write_bytes(raw)
                        except Exception as exc:
                            logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)

                # Best-effort: also create a JPEG variant for non-JPEG formats.
                if pillow_ok and ext not in {"jpg", "jpeg"}:
                    try:
                        img_obj = pil_image.open(BytesIO(raw))  # type: ignore[arg-type]
                        try:
                            if getattr(img_obj, "mode", None) != "RGB":
                                img_obj = img_obj.convert("RGB")
                            out = BytesIO()  # type: ignore[call-arg]
                            img_obj.save(out, format="JPEG", quality=85, optimize=True)
                            jpg_bytes = out.getvalue()
                        finally:
                            try:
                                img_obj.close()
                            except Exception as exc:
                                logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)

                        # 1) Keep the original digest but `.jpg` extension (max compatibility with callers
                        #    that hash pre-conversion but still reference `.jpg`).
                        compat_path = images_dir / f"{digest_raw}.jpg"
                        if not compat_path.exists():
                            try:
                                compat_path.write_bytes(jpg_bytes)
                            except Exception as exc:
                                logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)

                        # 2) Also save under the digest of the JPEG bytes.
                        digest_jpg = hashlib.sha256(jpg_bytes).hexdigest()
                        jpg_path = images_dir / f"{digest_jpg}.jpg"
                        if not jpg_path.exists():
                            try:
                                jpg_path.write_bytes(jpg_bytes)
                            except Exception as exc:
                                logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)
                        jpg_alias = images_dir / f"{digest_jpg}.jpeg"
                        if not jpg_alias.exists():
                            try:
                                jpg_alias.write_bytes(jpg_bytes)
                            except Exception as exc:
                                logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)
                    except Exception as exc:
                        logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)

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

        try:
            digest_png = hashlib.sha256(png_bytes).hexdigest()
        except Exception:
            return

        # 1) Exact PNG bytes (input to the model).
        png_path = images_dir / f"{digest_png}.png"
        if not png_path.exists():
            try:
                png_path.write_bytes(png_bytes)
            except Exception as exc:
                logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)

        # 2) A JPEG variant saved under both (a) the PNG digest (compat) and (b) the JPEG digest.
        try:
            jpg_bytes = pix.tobytes("jpg")
        except Exception:
            return

        jpg_path_compat = images_dir / f"{digest_png}.jpg"
        if not jpg_path_compat.exists():
            try:
                jpg_path_compat.write_bytes(jpg_bytes)
            except Exception as exc:
                logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)
        jpeg_path_compat = images_dir / f"{digest_png}.jpeg"
        if not jpeg_path_compat.exists():
            try:
                jpeg_path_compat.write_bytes(jpg_bytes)
            except Exception as exc:
                logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)

        try:
            digest_jpg = hashlib.sha256(jpg_bytes).hexdigest()
        except Exception:
            return

        jpg_path = images_dir / f"{digest_jpg}.jpg"
        if not jpg_path.exists():
            try:
                jpg_path.write_bytes(jpg_bytes)
            except Exception as exc:
                logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)
        jpeg_path = images_dir / f"{digest_jpg}.jpeg"
        if not jpeg_path.exists():
            try:
                jpeg_path.write_bytes(jpg_bytes)
            except Exception as exc:
                logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)

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
                logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)

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
                        logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)
            except Exception as exc:
                logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)

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

        max_images = max(0, int(getattr(settings, "MAX_INLINE_IMAGES", 0) or 0))
        supported_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

        found: list[str] = []
        seen: set[str] = set()
        for pat in (_MARKDOWN_IMAGE_REF_RE, _HTML_IMAGE_REF_RE):
            for m in pat.finditer(markdown_text):
                ref = (m.group(1) or "").strip()
                if not ref or ref in seen:
                    continue
                seen.add(ref)
                found.append(ref)

        if not found:
            return
        if max_images and len(found) > max_images:
            found = found[:max_images]

        def _copy_or_write_placeholder(dest: Path, *, prefer: str) -> None:
            """
            Best-effort placeholder writer.
            - prefer="png": copy page_png_path or write page_png_bytes
            - prefer="jpg": copy page_jpg_path or write page_jpg_bytes
            """
            if prefer == "jpg":
                if page_jpg_path and page_jpg_path.exists():
                    try:
                        shutil.copyfile(page_jpg_path, dest)
                        return
                    except Exception as exc:
                        logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)
                if page_jpg_bytes:
                    try:
                        dest.write_bytes(page_jpg_bytes)
                    except Exception as exc:
                        logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)
                return

            if page_png_path and page_png_path.exists():
                try:
                    shutil.copyfile(page_png_path, dest)
                    return
                except Exception as exc:
                    logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)
            if page_png_bytes:
                try:
                    dest.write_bytes(page_png_bytes)
                except Exception as exc:
                    logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)

        for ref in found:
            ref_stripped = ref.strip()
            if not ref_stripped:
                continue

            ref_lower = ref_stripped.lower()
            ref_scheme = ref_stripped.split(":", 1)[0].lower()
            if ref_scheme in {"http", "https", "data", "blob"} or ref_lower.startswith("/api/"):
                continue

            ref_path = ref_stripped.split("?", 1)[0].split("#", 1)[0].strip()
            if not ref_path:
                continue
            try:
                ref_path = unquote(ref_path)
            except Exception as exc:
                logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)

            rel = ref_path.lstrip("/")
            if not rel.lower().startswith("images/"):
                continue

            leaf = rel[7:]  # strip "images/"
            if not leaf or leaf.startswith(("/", "\\")):
                continue

            ext = Path(leaf).suffix.lower()
            if ext and ext not in supported_exts:
                continue

            dest_path = (images_dir / leaf).resolve(strict=False)
            try:
                dest_path.relative_to(images_dir_resolved)
            except Exception:
                continue
            if dest_path.exists():
                continue

            try:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                continue

            prefer = "jpg" if ext in {".jpg", ".jpeg"} else "png"
            _copy_or_write_placeholder(dest_path, prefer=prefer)

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
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        if file_path.suffix.lower() != ".pdf":
            raise ValueError("DeepSeek OCR currently supports PDF only")

        start = time.time()
        logger.info("[deepseek_ocr] start %s", file_path.name)

        artifact_root = self._build_artifact_root(file_path, document_id)
        images_dir = artifact_root / "images"
        artifact_root.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(file_path))
        try:
            total_pages = int(len(doc))
            include_page_images = bool(getattr(settings, "DEEPSEEK_OCR_INCLUDE_PAGE_IMAGES", True))
            max_page_images = int(getattr(settings, "DEEPSEEK_OCR_PAGE_IMAGE_MAX_PAGES", 0) or 0)
            page_image_format = (getattr(settings, "DEEPSEEK_OCR_PAGE_IMAGE_FORMAT", "jpg") or "jpg").strip().lower()
            if page_image_format not in {"png", "jpg", "jpeg"}:
                page_image_format = "jpg"

            extracted_images = 0
            try:
                extracted_images = self._extract_pdf_images(doc, images_dir=images_dir)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[deepseek_ocr] failed extracting PDF images: %s", str(exc)[:200])

            concurrency = int(getattr(settings, "DEEPSEEK_OCR_CONCURRENCY", 1) or 1)
            concurrency = max(1, min(concurrency, max(1, total_pages)))

            # Run per-page OCR (optionally in parallel).
            results: dict[int, str] = {}
            page_named_images: dict[int, tuple[Path, Path]] = {}
            errors: list[str] = []

            def submit_page(executor: ThreadPoolExecutor, idx: int, page_obj: fitz.Page) -> None:
                pix = page_obj.get_pixmap(dpi=self._pdf_dpi)
                img_bytes = pix.tobytes("png")
                self._persist_page_image_variants(pix=pix, png_bytes=img_bytes, images_dir=images_dir)
                try:
                    page_named_images[idx] = self._persist_named_page_images(
                        page_idx=idx,
                        pix=pix,
                        png_bytes=img_bytes,
                        images_dir=images_dir,
                    )
                except Exception as exc:
                    logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)
                logger.info("[deepseek_ocr] page %s/%s (%s)", idx, total_pages, file_path.name)
                fut = executor.submit(self._call_api, img_bytes, mime_type="image/png")
                inflight[fut] = idx

            if concurrency <= 1:
                for idx, page in enumerate(doc, start=1):
                    pix = page.get_pixmap(dpi=self._pdf_dpi)
                    img_bytes = pix.tobytes("png")
                    self._persist_page_image_variants(pix=pix, png_bytes=img_bytes, images_dir=images_dir)
                    png_path, jpg_path = self._persist_named_page_images(
                        page_idx=idx,
                        pix=pix,
                        png_bytes=img_bytes,
                        images_dir=images_dir,
                    )
                    page_named_images[idx] = (png_path, jpg_path)
                    logger.info("[deepseek_ocr] page %s/%s (%s)", idx, total_pages, file_path.name)
                    text = self._call_api(img_bytes, mime_type="image/png")
                    page_jpg_bytes: bytes | None = None
                    try:
                        page_jpg_bytes = pix.tobytes("jpg")
                    except Exception:
                        page_jpg_bytes = None
                    try:
                        self._ensure_referenced_images_exist(
                            markdown_text=text or "",
                            images_dir=images_dir,
                            page_png_path=png_path,
                            page_jpg_path=jpg_path,
                            page_png_bytes=img_bytes,
                            page_jpg_bytes=page_jpg_bytes,
                        )
                    except Exception as exc:
                        logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)
                    results[idx] = text or ""
            else:
                inflight: dict = {}
                with ThreadPoolExecutor(max_workers=concurrency) as executor:
                    for idx, page in enumerate(doc, start=1):
                        submit_page(executor, idx, page)
                        if len(inflight) < concurrency:
                            continue
                        done, _pending = wait(inflight.keys(), return_when=FIRST_COMPLETED)
                        for f in done:
                            page_idx = inflight.pop(f)
                            try:
                                text = f.result() or ""
                                results[page_idx] = text
                                try:
                                    png_path, jpg_path = page_named_images.get(page_idx, (None, None))
                                    self._ensure_referenced_images_exist(
                                        markdown_text=text or "",
                                        images_dir=images_dir,
                                        page_png_path=png_path,
                                        page_jpg_path=jpg_path,
                                    )
                                except Exception as exc:
                                    logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)
                            except Exception as exc:  # noqa: BLE001
                                errors.append(f"page {page_idx}: {str(exc)[:200]}")

                    # Drain remaining futures.
                    if inflight:
                        done_all, _ = wait(inflight.keys())
                        for f in done_all:
                            page_idx = inflight.pop(f, None)
                            if page_idx is None:
                                continue
                            try:
                                text = f.result() or ""
                                results[page_idx] = text
                                try:
                                    png_path, jpg_path = page_named_images.get(page_idx, (None, None))
                                    self._ensure_referenced_images_exist(
                                        markdown_text=text or "",
                                        images_dir=images_dir,
                                        page_png_path=png_path,
                                        page_jpg_path=jpg_path,
                                    )
                                except Exception as exc:
                                    logger.debug("Ignoring non-critical DeepSeek OCR fallback failure: %s", exc)
                            except Exception as exc:  # noqa: BLE001
                                errors.append(f"page {page_idx}: {str(exc)[:200]}")

            if errors:
                raise RuntimeError(f"DeepSeek OCR failed: {errors[0]}")

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
                    # Used by downstream stages to resolve relative image paths like "images/<sha>.jpg".
                    "asset_base_dir": str(artifact_root),
                    # Used for best-effort cleanup after ingestion/preview.
                    "artifact_dir": str(artifact_root),
                    "deepseek_ocr_extracted_images": int(extracted_images),
                    "deepseek_ocr_concurrency": int(concurrency),
                }
                docs.append(Document(page_content=page_content, metadata=meta))
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
