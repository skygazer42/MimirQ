"""
ETL4LLM parser (layout/table/image-aware, via an etl4llm predict API).

This backend calls an etl4llm-compatible service and returns Markdown-ish text
plus optional local image refs under an artifact directory so MimirQ can:
- rewrite images for preview (/api/v1/documents/image/{uuid})
- upload local images to MinIO during ingestion (/api/v1/documents/image-url/{img_id})

Example endpoint:
  http://localhost:10001/v1/etl4llm/predict
"""

import base64
import hashlib
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import requests
from langchain_core.documents import Document
from PIL import Image as PILImage

from app.core.config import settings
from app.core.constants import NON_CRITICAL_EXCEPTION_LOG_MESSAGE
from app.rag.core.logging import get_logger

logger = get_logger("parsing.etl4llm")
_ETL4LLM_PARSER_FALLBACK_LOG_MESSAGE = "Ignoring non-critical ETL4LLM parser fallback failure: %s"


_HEADER_FOOTER_TYPES = {
    "header",
    "footer",
    "pageheader",
    "pagefooter",
    "page_header",
    "page_footer",
}


class Etl4LlmParser:
    """
    ETL4LLM parser via an etl4llm predict API.

    Config via env/.env:
    - ETL4LLM_ENABLED=true
    - ETL4LLM_API_URL=http://localhost:10001/v1/etl4llm/predict
    """

    def __init__(self) -> None:
        self._enabled = bool(getattr(settings, "ETL4LLM_ENABLED", False))
        self._api_url = (getattr(settings, "ETL4LLM_API_URL", "") or "").strip()
        self._timeout_sec = float(getattr(settings, "ETL4LLM_TIMEOUT_SEC", 120) or 120)
        self._mode = (getattr(settings, "ETL4LLM_MODE", "") or "partition").strip().lower()
        self._force_ocr = bool(getattr(settings, "ETL4LLM_FORCE_OCR", False))
        self._enable_formula = bool(getattr(settings, "ETL4LLM_ENABLE_FORMULA", True))
        self._extract_images = bool(getattr(settings, "ETL4LLM_EXTRACT_IMAGES", True))
        self._filter_header_footer = bool(getattr(settings, "ETL4LLM_FILTER_PAGE_HEADER_FOOTER", False))

        if not self._enabled:
            raise RuntimeError("ETL4LLM is disabled (ETL4LLM_ENABLED=false).")
        if not self._api_url:
            raise RuntimeError("ETL4LLM requires ETL4LLM_API_URL.")

        self._session = requests.Session()

    def _build_artifact_root(self, file_path: Path, document_id: str | None) -> Path:
        run_id = (document_id or file_path.stem or "etl4llm").strip()
        run_id = re.sub(r"[^a-zA-Z0-9._-]+", "_", run_id)[:120] or "etl4llm"
        return (file_path.parent / ".etl4llm" / run_id).absolute()

    def _resolve_force_ocr(self, pdf_quality: Any) -> bool:
        if bool(self._force_ocr):
            return True
        if isinstance(pdf_quality, dict):
            return bool(pdf_quality.get("is_scanned", False))
        return False

    def _call_api(self, *, file_path: Path, force_ocr: bool) -> dict[str, Any]:
        file_bytes = file_path.read_bytes()
        b64_data = base64.b64encode(file_bytes).decode("utf-8")

        mode = self._mode or "partition"
        if mode not in {"partition", "text"}:
            mode = "partition"

        payload: dict[str, Any] = {
            "filename": file_path.name,
            "b64_data": [b64_data],
            "mode": mode,
        }
        # Optional knobs (service-dependent).
        payload["force_ocr"] = bool(force_ocr)
        payload["enable_formula"] = bool(self._enable_formula)
        payload["parameters"] = {"start": 0, "n": None}

        resp = self._session.post(self._api_url, json=payload, timeout=self._timeout_sec)
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            raise RuntimeError(f"ETL4LLM API error {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        if int(data.get("status_code", 0) or 0) != 200:
            raise RuntimeError(f"ETL4LLM returned status_code={data.get('status_code')}: {str(data)[:500]}")
        return data

    @staticmethod
    def _image_partition_item(part: dict[str, Any]) -> tuple[int, str, list[int]] | None:
        try:
            if str(part.get("type") or "").strip().lower() != "image":
                return None
            element_id = str(part.get("element_id") or "").strip()
            extra = (part.get("metadata") or {}).get("extra_data") or {}
            bboxes = extra.get("bboxes") or []
            pages = extra.get("pages") or []
            if not element_id:
                element_id = hashlib.sha256(
                    (str(pages[:1]) + str(bboxes[:1])).encode("utf-8", errors="ignore")
                ).hexdigest()[:32]
            if not bboxes or not pages:
                return None
            bbox = bboxes[0]
            if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
                return None
            return int(pages[0]), element_id, [int(x) for x in bbox]
        except Exception:
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
            return None

    def _collect_partition_image_items(
        self,
        partitions: list[dict[str, Any]],
    ) -> list[tuple[int, str, list[int]]]:
        items: list[tuple[int, str, list[int]]] = []
        for part in partitions:
            item = self._image_partition_item(part)
            if item is not None:
                items.append(item)
        return items

    @staticmethod
    def _load_pdf_page_image(pdf: Any, page_cache: dict[int, Any], page_idx: int) -> Any:
        page_img = page_cache.get(page_idx)
        if page_img is not None:
            return page_img
        pix = pdf[page_idx].get_pixmap()
        page_img = PILImage.open(BytesIO(pix.tobytes("png"))).convert("RGB")
        page_cache[page_idx] = page_img
        return page_img

    @staticmethod
    def _clamp_crop_box(page_img: Any, bbox: list[int]) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = bbox
        w, h = page_img.size
        x1c = max(0, min(int(x1), w - 1))
        y1c = max(0, min(int(y1), h - 1))
        x2c = max(x1c + 1, min(int(x2), w))
        y2c = max(y1c + 1, min(int(y2), h))
        return x1c, y1c, x2c, y2c

    def _write_partition_image(
        self,
        *,
        pdf: Any,
        page_cache: dict[int, Any],
        images_dir: Path,
        page_idx: int,
        element_id: str,
        bbox: list[int],
    ) -> str | None:
        if page_idx < 0 or page_idx >= len(pdf):
            return None
        page_img = self._load_pdf_page_image(pdf, page_cache, page_idx)
        crop_box = self._clamp_crop_box(page_img, bbox)
        out_path = images_dir / f"{element_id}.png"
        try:
            cropped = page_img.crop(crop_box)
            cropped.save(out_path, format="PNG", optimize=True)
            cropped.close()
        except Exception:
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
            return None
        return f"images/{out_path.name}"

    @staticmethod
    def _close_page_cache(page_cache: dict[int, Any]) -> None:
        for img in page_cache.values():
            try:
                img.close()
            except Exception as exc:
                logger.debug(_ETL4LLM_PARSER_FALLBACK_LOG_MESSAGE, exc)

    @staticmethod
    def _partition_text(label_l: str, text: str, element_id: str, image_map: dict[str, str]) -> str:
        if label_l != "image":
            return text
        ref = image_map.get(element_id)
        if ref:
            return f"![]({ref})"
        return text

    @staticmethod
    def _append_partition_text(
        parts: list[str],
        *,
        text: str,
        label_l: str,
        last_label: str,
        is_first: bool,
    ) -> None:
        if is_first:
            parts.append(text + "\n" if label_l == "title" else text)
            return
        if last_label.lower() == "title" and label_l == "title":
            parts.append("\n" + text)
            return
        if label_l in {"title", "table"}:
            parts.append("\n\n" + text)
            return
        separator = "\n\n" if last_label.lower() == "table" else "\n"
        parts.append(separator + text)

    @staticmethod
    def _partition_extra(part: dict[str, Any]) -> dict[str, Any]:
        if isinstance(part.get("metadata"), dict):
            return (part.get("metadata") or {}).get("extra_data") or {}
        return {}

    def _extend_merged_meta(
        self,
        *,
        meta: dict[str, Any],
        extra: dict[str, Any],
        prev_length: int,
    ) -> None:
        bboxes = extra.get("bboxes") or []
        pages = extra.get("pages") or []
        types = extra.get("types") or []
        indexes = extra.get("indexes") or []

        try:
            meta["bboxes"].extend([list(map(int, b)) for b in bboxes if isinstance(b, (list, tuple)) and len(b) == 4])
        except Exception as exc:
            logger.debug(_ETL4LLM_PARSER_FALLBACK_LOG_MESSAGE, exc)
        if isinstance(pages, list):
            meta["pages"].extend(pages)
        if isinstance(types, list):
            meta["types"].extend(types)

        try:
            shifted = []
            for item in indexes:
                if not (isinstance(item, (list, tuple)) and len(item) == 2):
                    continue
                s, e = int(item[0]), int(item[1])
                shifted.append([s + prev_length, e + prev_length])
            meta["indexes"].extend(shifted)
        except Exception as exc:
            logger.debug(_ETL4LLM_PARSER_FALLBACK_LOG_MESSAGE, exc)

    @staticmethod
    def _base_merged_meta() -> dict[str, Any]:
        return {"bboxes": [], "pages": [], "indexes": [], "types": []}

    def _parse_service_payload(
        self,
        *,
        file_path: Path,
        force_ocr: bool,
        artifact_root: Path,
        images_dir: Path,
    ) -> tuple[str, dict[str, Any], int]:
        data = self._call_api(file_path=file_path, force_ocr=force_ocr)
        partitions = data.get("partitions") or []
        text = str(data.get("text") or "")

        extracted_images = 0
        image_map: dict[str, str] = {}
        merged_meta = self._base_merged_meta()
        merged_text = ""
        if isinstance(partitions, list) and partitions:
            try:
                extracted_images, image_map = self._extract_partition_images(
                    pdf_path=file_path,
                    partitions=partitions,
                    images_dir=images_dir,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[etl4llm] image extraction failed: %s", str(exc)[:200])
            merged_text, merged_meta = self._merge_partitions(partitions=partitions, image_map=image_map)
        elif text.strip():
            merged_text = text.strip()

        self._maybe_add_page_image_fallback(
            file_path=file_path,
            merged_text=merged_text,
            extracted_images=extracted_images,
            images_dir=images_dir,
            metadata=merged_meta,
        )
        merged_text = str(merged_meta.pop("_merged_text", merged_text))
        merged_meta["asset_base_dir"] = str(artifact_root)
        merged_meta["artifact_dir"] = str(artifact_root)
        merged_meta["etl4llm_partitions"] = int(len(partitions) if isinstance(partitions, list) else 0)
        merged_meta["etl4llm_extracted_images"] = int(extracted_images)
        return merged_text, merged_meta, extracted_images

    def _maybe_add_page_image_fallback(
        self,
        *,
        file_path: Path,
        merged_text: str,
        extracted_images: int,
        images_dir: Path,
        metadata: dict[str, Any],
    ) -> None:
        try:
            fallback_enabled = bool(getattr(settings, "ETL4LLM_INCLUDE_PAGE_IMAGES_IF_EMPTY", True))
            has_any_images = int(extracted_images or 0) > 0
            lowered = (merged_text or "").lower()
            has_refs = ("![" in lowered) or ("<img" in lowered)
            if not (
                fallback_enabled
                and self._extract_images
                and file_path.suffix.lower() == ".pdf"
                and (not has_any_images)
                and (not has_refs)
            ):
                return

            dpi = int(getattr(settings, "ETL4LLM_PAGE_IMAGE_DPI", 150) or 150)
            max_pages = max(0, int(settings.ETL4LLM_PAGE_IMAGE_MAX_PAGES))
            page_refs = self._render_page_image_refs(
                file_path=file_path, images_dir=images_dir, dpi=dpi, max_pages=max_pages
            )
            if not page_refs:
                return

            gallery = "\n\n".join(page_refs).strip()
            metadata["_merged_text"] = f"{gallery}\n\n{merged_text}".strip() if (merged_text or "").strip() else gallery
            metadata["etl4llm_page_images"] = len(page_refs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[etl4llm] page image fallback failed: %s", str(exc)[:200])

    def _render_page_image_refs(
        self,
        *,
        file_path: Path,
        images_dir: Path,
        dpi: int,
        max_pages: int,
    ) -> list[str]:
        page_refs: list[str] = []
        pdf = fitz.open(str(file_path))
        try:
            images_dir.mkdir(parents=True, exist_ok=True)
            for page_idx, page in enumerate(pdf, start=1):
                if max_pages and page_idx > max_pages:
                    break
                pix = page.get_pixmap(dpi=dpi)
                jpg_bytes = pix.tobytes("jpg")
                out_path = images_dir / f"page_{page_idx:04d}.jpg"
                if not out_path.exists():
                    try:
                        out_path.write_bytes(jpg_bytes)
                    except Exception:
                        get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
                        continue
                page_refs.append(f"![page {page_idx}](images/{out_path.name})")
        finally:
            try:
                pdf.close()
            except Exception as exc:
                logger.debug(_ETL4LLM_PARSER_FALLBACK_LOG_MESSAGE, exc)
        return page_refs

    def _build_document_metadata(
        self,
        *,
        file_path: Path,
        artifact_root: Path,
        force_ocr: bool,
        merged_meta: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = {
            "source": file_path.name,
            "file_type": "pdf",
            "parser_backend": "etl4llm",
            "etl4llm_mode": str(self._mode or ""),
            "etl4llm_force_ocr": bool(force_ocr),
            "asset_base_dir": str(artifact_root),
            "artifact_dir": str(artifact_root),
        }
        if isinstance(merged_meta, dict):
            metadata.update(merged_meta)
        return metadata

    def _extract_partition_images(
        self,
        *,
        pdf_path: Path,
        partitions: list[dict[str, Any]],
        images_dir: Path,
    ) -> tuple[int, dict[str, str]]:
        """
        Crop image partitions from the source PDF into `images_dir`.

        Returns (count, element_id->relative_path mapping).
        """
        if not self._extract_images:
            return 0, {}

        images_dir.mkdir(parents=True, exist_ok=True)
        items = self._collect_partition_image_items(partitions)

        if not items:
            return 0, {}

        pdf = fitz.open(str(pdf_path))
        page_cache: dict[int, Any] = {}
        mapping: dict[str, str] = {}
        written = 0
        try:
            for page_idx, element_id, bbox in items:
                ref = self._write_partition_image(
                    pdf=pdf,
                    page_cache=page_cache,
                    images_dir=images_dir,
                    page_idx=page_idx,
                    element_id=element_id,
                    bbox=bbox,
                )
                if ref is None:
                    continue
                mapping[element_id] = ref
                written += 1

        finally:
            self._close_page_cache(page_cache)
            pdf.close()

        return written, mapping

    def _merge_partitions(
        self,
        *,
        partitions: list[dict[str, Any]],
        image_map: dict[str, str],
    ) -> tuple[str, dict[str, Any]]:
        """
        Merge partitions into a single markdown-ish string, preserving extra_data indices.
        """
        parts: list[str] = []
        is_first = True
        last_label = ""
        prev_length = 0
        meta = self._base_merged_meta()

        for part in partitions:
            label = str(part.get("type") or "").strip()
            label_l = label.lower()
            if self._filter_header_footer and label_l in _HEADER_FOOTER_TYPES:
                continue

            text = self._partition_text(
                label_l,
                str(part.get("text") or ""),
                str(part.get("element_id") or "").strip(),
                image_map,
            )
            self._append_partition_text(
                parts,
                text=text,
                label_l=label_l,
                last_label=last_label,
                is_first=is_first,
            )
            self._extend_merged_meta(
                meta=meta,
                extra=self._partition_extra(part),
                prev_length=prev_length,
            )

            prev_length += len(parts[-1])
            last_label = label
            is_first = False

        return "".join(parts), meta

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
            raise ValueError("ETL4LLM currently supports PDF only")

        start = time.time()
        force_ocr = self._resolve_force_ocr(_kwargs.get("pdf_quality"))
        logger.info("[etl4llm] start %s (force_ocr=%s)", file_path.name, bool(force_ocr))

        artifact_root = self._build_artifact_root(file_path, document_id)
        images_dir = artifact_root / "images"
        artifact_root.mkdir(parents=True, exist_ok=True)

        merged_text, merged_meta, _ = self._parse_service_payload(
            file_path=file_path,
            force_ocr=force_ocr,
            artifact_root=artifact_root,
            images_dir=images_dir,
        )
        metadata = self._build_document_metadata(
            file_path=file_path,
            artifact_root=artifact_root,
            force_ocr=force_ocr,
            merged_meta=merged_meta,
        )

        logger.info("[etl4llm] done %s in %.2fs", file_path.name, time.time() - start)
        return [Document(page_content=merged_text, metadata=metadata)]
