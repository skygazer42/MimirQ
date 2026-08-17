import re
import time
import warnings
from pathlib import Path
from threading import Lock
from typing import Any

from langchain_core.documents import Document
from PIL import Image as PILImage

from app.core.config import settings
from app.deepdoc.parser import PdfParser as DeepDocPdfParser
from app.parsing.enrich.caption_linker import find_nearest_caption
from app.parsing.enrich.cross_page_table_linker import link_cross_page_table_documents
from app.parsing.enrich.document_region_algorithms import (
    detect_chart_regions,
    detect_formula_regions,
    profile_document_image_with_models,
)
from app.parsing.enrich.header_footer_remover import remove_repeated_header_footer_elements
from app.parsing.enrich.reading_order_fixer import fix_reading_order_elements
from app.parsing.enrich.section_tree import add_section_paths, build_section_tree
from app.parsing.enrich.table_canonical import extract_markdown_table, profile_markdown_table
from app.parsing.enrich.table_image_algorithms import (
    bind_ocr_lines_to_table_cells,
    classify_table_grid_type,
    extract_ocr_lines_from_image,
    select_table_rotation,
    table_cells_with_uniform_bboxes,
)
from app.parsing.enrich.table_renderers import render_table_csv, render_table_html, render_table_markdown
from app.parsing.enrich.table_structure_adapter import (
    TableStructureDetection,
    table_extraction_from_structure_detections,
)
from app.parsing.enrich.watermark_detector import remove_document_watermark_elements
from app.parsing.models.runtime import SmallModelRuntime
from app.parsing.models.table_transformer_onnx import predict_table_structure_detections
from app.parsing.utils.block_schema import POSITION_TAG_RE, build_block_element, parse_position_tags

_HEADING_LEVEL_RE = re.compile(r"(\d+)")


def _elapsed_ms_since(start: float) -> int:
    return max(0, int(round((time.perf_counter() - start) * 1000.0)))


def _raw_item_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if value is None:
        return 0
    if isinstance(value, str):
        return 1 if value.strip() else 0
    return 1


def _looks_like_heading_style(style_name: str) -> bool:
    s = (style_name or "").strip()
    if not s:
        return False
    s_lower = s.lower()
    return s_lower.startswith("heading") or "标题" in s


def _heading_level(style_name: str) -> int:
    m = _HEADING_LEVEL_RE.search((style_name or "").strip())
    if not m:
        return 2
    try:
        lvl = int(m.group(1))
    except Exception:
        return 2
    return max(1, min(6, lvl))


def _looks_like_list_style(style_name: str) -> bool:
    s = (style_name or "").strip().lower()
    return "list" in s or "bullet" in s or "列表" in s


def _list_marker(style_name: str) -> str:
    s = (style_name or "").strip().lower()
    if "number" in s or "编号" in s or "序号" in s:
        return "1."
    return "-"


class DeepDocParser:
    """Bridge DeepDoc's parser so we can reuse it inside our pipeline."""

    def __init__(self):
        self._pdf_parser_cls = DeepDocPdfParser
        self._pdf_parser = None
        self._docx_parser = None
        self._small_model_runtime = SmallModelRuntime()
        self._lock = Lock()

    def _ensure_pdf_parser(self):
        if self._pdf_parser is None:
            self._pdf_parser = self._pdf_parser_cls()
        return self._pdf_parser

    def _ensure_docx_parser(self):
        if self._docx_parser is None:
            from app.deepdoc.parser import DocxParser as DeepDocDocxParser

            self._docx_parser = DeepDocDocxParser()
        return self._docx_parser

    @staticmethod
    def _small_model_summary(runtime_metadata: dict[str, Any]) -> dict[str, Any]:
        available_tasks: list[str] = []
        unavailable_tasks: list[str] = []
        for task, item in runtime_metadata.items():
            if isinstance(item, dict) and bool(item.get("available")):
                available_tasks.append(str(task))
            else:
                unavailable_tasks.append(str(task))
        return {
            "task_count": len(runtime_metadata),
            "available_count": len(available_tasks),
            "unavailable_count": len(unavailable_tasks),
            "unavailable_tasks": unavailable_tasks,
        }

    @classmethod
    def _build_deepdoc_profile(
        cls,
        *,
        file_type: str,
        stages_ms: dict[str, int],
        runtime_metadata: dict[str, Any],
        document_count: int,
        section_count: int,
        media_count: int,
        total_pages: Any = None,
        ocr_recognition: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        profile: dict[str, Any] = {
            "schema": "mimirq.deepdoc_profile.v1",
            "engine": "deepdoc",
            "file_type": file_type,
            "stages_ms": dict(stages_ms),
            "document_count": int(max(0, document_count)),
            "section_count": int(max(0, section_count)),
            "media_count": int(max(0, media_count)),
            "small_model_summary": cls._small_model_summary(runtime_metadata),
        }
        try:
            pages = int(total_pages)
        except (TypeError, ValueError):
            pages = 0
        if pages > 0:
            profile["total_pages"] = pages
        if isinstance(ocr_recognition, dict) and ocr_recognition:
            profile["ocr_recognition"] = dict(ocr_recognition)
        return profile

    @staticmethod
    def _attach_deepdoc_profile(documents: list[Document], profile: dict[str, Any]) -> list[Document]:
        for doc in documents:
            meta = dict(doc.metadata or {})
            meta["deepdoc_profile"] = dict(profile)
            doc.metadata = meta
        return documents

    @staticmethod
    def _ocr_recognition_profile_from_parser(parser: Any) -> dict[str, Any] | None:
        ocr = getattr(parser, "ocr", None)
        profile = getattr(ocr, "last_recognition_profile", None)
        return dict(profile) if isinstance(profile, dict) and profile else None

    def _small_model_runtime_metadata(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for task in (
            "layout",
            "table_detection",
            "table_structure",
            "ocr_detection",
            "ocr_recognition",
            "document_orientation",
            "document_rectification",
            "textline_orientation",
        ):
            try:
                out[task] = self._small_model_runtime.resolve(task, allow_download=False).to_metadata()
            except Exception as exc:  # pragma: no cover - defensive metadata should not block parsing
                out[task] = {
                    "task": task,
                    "available": False,
                    "reason": f"small_model_resolve_failed:{str(exc)[:160]}",
                }
        return out

    def _table_structure_model_metadata(self, image_obj: Any) -> dict[str, Any] | None:
        if not isinstance(image_obj, PILImage.Image):
            return None
        try:
            status = self._small_model_runtime.resolve(
                "table_structure",
                model_id="tatr_v1_1_all_onnx",
                allow_download=False,
            )
            if not status.available:
                return {
                    "model": status.to_metadata(),
                    "detections": [],
                    "detection_count": 0,
                }
            detections = predict_table_structure_detections(
                image_obj,
                runtime=self._small_model_runtime,
                model_id="tatr_v1_1_all_onnx",
                threshold=0.8,
                max_detections=80,
            )
            return {
                "model": status.to_metadata(),
                "detections": [item.to_metadata() for item in detections],
                "detection_count": len(detections),
            }
        except Exception as exc:  # pragma: no cover - optional model should never block parsing
            return {
                "model": {
                    "task": "table_structure",
                    "model_id": "tatr_v1_1_all_onnx",
                    "available": False,
                    "reason": f"table_structure_prediction_failed:{str(exc)[:160]}",
                },
                "detections": [],
                "detection_count": 0,
            }

    def _table_detection_model_metadata(self, image_obj: Any) -> dict[str, Any] | None:
        if not isinstance(image_obj, PILImage.Image):
            return None
        try:
            status = self._small_model_runtime.resolve(
                "table_detection",
                model_id="tatr_detection_onnx",
                allow_download=False,
            )
            if not status.available:
                return None
            detections = predict_table_structure_detections(
                image_obj,
                runtime=self._small_model_runtime,
                task="table_detection",
                model_id="tatr_detection_onnx",
                threshold=0.8,
                max_detections=16,
            )
            return {
                "model": status.to_metadata(),
                "detections": [item.to_metadata() for item in detections],
                "detection_count": len(detections),
            }
        except Exception as exc:  # pragma: no cover - optional model should never block parsing
            return {
                "model": {
                    "task": "table_detection",
                    "model_id": "tatr_detection_onnx",
                    "available": False,
                    "reason": f"table_detection_prediction_failed:{str(exc)[:160]}",
                },
                "detections": [],
                "detection_count": 0,
            }

    @staticmethod
    def _table_structure_detections_from_metadata(
        structure_model: dict[str, Any] | None,
    ) -> list[TableStructureDetection]:
        if not isinstance(structure_model, dict):
            return []
        detections = structure_model.get("detections")
        if not isinstance(detections, list):
            return []
        out: list[TableStructureDetection] = []
        for item in detections:
            if not isinstance(item, dict):
                continue
            out.append(
                TableStructureDetection(
                    label=str(item.get("label") or ""),
                    score=float(item.get("score") or 0.0),
                    bbox=item.get("bbox") if isinstance(item.get("bbox"), dict) else None,
                )
            )
        return out

    def _docx_section_parts(self, sections: Any) -> list[str]:
        parts: list[str] = []
        if isinstance(sections, list):
            for item in sections:
                if isinstance(item, tuple):
                    text = str((item[0] if item else "") or "").strip()
                    style_name = str((item[1] if len(item) > 1 else "") or "")
                else:
                    text = str(item or "").strip()
                    style_name = ""
                if not text:
                    continue
                if style_name and _looks_like_heading_style(style_name):
                    parts.append(f"{'#' * _heading_level(style_name)} {text}")
                elif style_name and _looks_like_list_style(style_name):
                    parts.append(f"{_list_marker(style_name)} {text}")
                else:
                    parts.append(text)
        else:
            text = str(sections or "").strip()
            if text:
                parts.append(text)
        return parts

    @staticmethod
    def _docx_table_parts(tables: Any) -> list[str]:
        parts: list[str] = []
        if isinstance(tables, list):
            for table in tables:
                if isinstance(table, list):
                    joined = "\n".join(str(value).strip() for value in table if str(value).strip()).strip()
                    if joined:
                        parts.append(joined)
                else:
                    text = str(table or "").strip()
                    if text:
                        parts.append(text)
        return parts

    def _docx_parts(self, sections: Any, tables: Any) -> list[str]:
        return self._docx_section_parts(sections) + self._docx_table_parts(tables)

    def _parse_docx(self, file_path: Path) -> list[Document]:
        stages_ms: dict[str, int] = {}
        with self._lock:
            stage_t0 = time.perf_counter()
            parser = self._ensure_docx_parser()
            stages_ms["ensure_parser"] = _elapsed_ms_since(stage_t0)
            try:
                stage_t0 = time.perf_counter()
                sections, tables = parser(str(file_path))
                stages_ms["parse_core"] = _elapsed_ms_since(stage_t0)
            except Exception as exc:  # pragma: no cover - passthrough
                raise RuntimeError(f"DeepDoc failed to parse {file_path}") from exc

        postprocess_t0 = time.perf_counter()
        merged_text = "\n\n".join(self._docx_parts(sections, tables)).strip()
        stages_ms["postprocess"] = _elapsed_ms_since(postprocess_t0)
        runtime_metadata = self._small_model_runtime_metadata()
        docs = [
            Document(
                page_content=merged_text,
                metadata={
                    "source": file_path.name,
                    "file_type": "docx",
                    "parser_backend": "deepdoc",
                    "small_model_runtime": runtime_metadata,
                },
            )
        ]
        profile = self._build_deepdoc_profile(
            file_type="docx",
            stages_ms=stages_ms,
            runtime_metadata=runtime_metadata,
            document_count=len(docs),
            section_count=_raw_item_count(sections),
            media_count=_raw_item_count(tables),
        )
        return self._attach_deepdoc_profile(docs, profile)

    def _parse_pdf_core(self, file_path: Path) -> tuple[Any, Any, Any, Any, dict[str, int]]:
        stages_ms: dict[str, int] = {}
        with self._lock:
            stage_t0 = time.perf_counter()
            parser = self._ensure_pdf_parser()
            stages_ms["ensure_parser"] = _elapsed_ms_since(stage_t0)
            try:
                stage_t0 = time.perf_counter()
                sections, media = parser(
                    str(file_path),
                    need_image=True,
                    zoomin=3,
                    return_html=True,
                )
                stages_ms["parse_core"] = _elapsed_ms_since(stage_t0)
            except Exception as exc:  # pragma: no cover - passthrough
                raise RuntimeError(f"DeepDoc failed to parse {file_path}") from exc
            total_pages = getattr(parser, "total_page", None)
        return parser, sections, media, total_pages, stages_ms

    @staticmethod
    def _pdf_base_meta(file_path: Path, *, runtime_metadata: dict[str, Any], total_pages: Any) -> dict[str, Any]:
        base_meta = {
            "source": file_path.name,
            "file_type": "pdf",
            "parser_backend": "deepdoc",
            "small_model_runtime": runtime_metadata,
        }
        if total_pages:
            base_meta["total_pages"] = total_pages
        return base_meta

    @staticmethod
    def _normalize_pdf_section(section: Any) -> tuple[str, str, dict[str, Any] | None]:
        if isinstance(section, tuple):
            head = section[0] if section else ""
            text = str(head or "").strip()
            if not text:
                return "", "text", None

            tag = ""
            native_kind = "text"
            extra_attrs: dict[str, Any] = {}
            for item in reversed(section[1:]):
                if isinstance(item, dict):
                    extra_attrs.update(item)
                    continue
                if not isinstance(item, str):
                    continue
                candidate = item.strip()
                if "@@" in candidate and "##" in candidate and POSITION_TAG_RE.search(candidate):
                    tag = candidate
                    continue
                normalized = candidate.lower()
                if normalized in {"text", "paragraph", "heading", "title", "list", "table", "image", "figure", "equation", "formula"}:
                    native_kind = normalized
            if tag and tag not in text:
                text = f"{text}{tag}"
            return text, native_kind, (extra_attrs or None)

        if isinstance(section, str):
            return section.strip(), "text", None
        return str(section or "").strip(), "text", None

    @staticmethod
    def _section_record(*, text: str, native_kind: str, attrs: dict[str, Any] | None, index: int) -> dict[str, Any]:
        return {
            "text": text,
            "element": build_block_element(
                text=text,
                kind=native_kind,
                source_backend="deepdoc",
                source_element_id=f"section:{index}",
                element_id=f"deepdoc:section:{index}",
                attributes={"block_index": index, **(attrs or {})},
            ),
        }

    def _section_records(self, sections: Any) -> list[dict[str, Any]]:
        section_items = sections if isinstance(sections, list) else [sections]
        records: list[dict[str, Any]] = []
        for index, item in enumerate(section_items):
            normalized, native_kind, attrs = self._normalize_pdf_section(item)
            if normalized:
                records.append(self._section_record(text=normalized, native_kind=native_kind, attrs=attrs, index=index))
        return records

    @staticmethod
    def _filter_records_by_elements(
        records: list[dict[str, Any]],
        elements: list[dict[str, Any]],
        *,
        changed: bool,
    ) -> list[dict[str, Any]]:
        if not changed:
            return records
        kept_ids = {str(element.get("id") or "") for element in elements}
        return [record for record in records if str(record["element"].get("id") or "") in kept_ids]

    def _prepare_section_content(
        self,
        section_records: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], Any, Any, Any]:
        watermark_removal = remove_document_watermark_elements([record["element"] for record in section_records])
        section_records = self._filter_records_by_elements(
            section_records,
            watermark_removal.elements,
            changed=watermark_removal.changed,
        )

        header_footer_removal = remove_repeated_header_footer_elements([record["element"] for record in section_records])
        section_records = self._filter_records_by_elements(
            section_records,
            header_footer_removal.elements,
            changed=header_footer_removal.changed,
        )

        reading_order_fix = fix_reading_order_elements([record["element"] for record in section_records])
        if reading_order_fix.elements:
            records_by_id = {str(record["element"].get("id") or ""): record for record in section_records}
            fixed_records = [records_by_id.get(str(element.get("id") or "")) for element in reading_order_fix.elements]
            if all(record is not None for record in fixed_records) and len(fixed_records) == len(section_records):
                section_records = [record for record in fixed_records if record is not None]

        text_parts = [str(record["text"]) for record in section_records]
        derived_elements = [dict(record["element"]) for record in section_records]
        section_tree = build_section_tree(derived_elements)
        if section_tree:
            derived_elements = add_section_paths(derived_elements, section_tree)
        return section_records, text_parts, derived_elements, section_tree, watermark_removal, header_footer_removal, reading_order_fix

    def _text_document_from_sections(
        self,
        *,
        merged_text: str,
        base_meta: dict[str, Any],
        derived_elements: list[dict[str, Any]],
        section_tree: list[dict[str, Any]],
        watermark_removal: Any,
        header_footer_removal: Any,
        reading_order_fix: Any,
    ) -> Document | None:
        if not merged_text:
            return None
        text_meta = dict(base_meta)
        text_meta["element_kind"] = "paragraph"
        text_meta["element_text"] = merged_text
        text_meta["element_attributes"] = {
            "source_content_type": "text",
            "source_doc_type": "text",
        }
        if derived_elements:
            text_meta["derived_elements"] = derived_elements
            if section_tree:
                text_meta["section_tree"] = section_tree
            text_meta["watermark_removal"] = watermark_removal.to_metadata()
            text_meta["header_footer_removal"] = header_footer_removal.to_metadata()
            text_meta["reading_order_fix"] = reading_order_fix.to_metadata()
            formula_regions = detect_formula_regions(derived_elements)
            chart_regions = detect_chart_regions(derived_elements)
            if formula_regions["count"]:
                text_meta["formula_regions"] = formula_regions
            if chart_regions["count"]:
                text_meta["chart_regions"] = chart_regions
        return Document(page_content=merged_text, metadata=text_meta)

    @staticmethod
    def _media_content(payload: Any) -> str:
        if isinstance(payload, str):
            content = payload.strip()
        elif isinstance(payload, list):
            content = "\n".join(str(item).strip() for item in payload if str(item).strip()).strip()
        else:
            content = str(payload).strip() if payload is not None else ""
        if not content:
            return "image"
        if len(content) > 900:
            return content[:900].rstrip() + "..."
        return content

    def _media_analysis(self, *, media_index: int, image_obj: Any, content: str) -> dict[str, Any]:
        positions = parse_position_tags(content)
        first_position = positions[0] if positions else {}
        table_profile = profile_markdown_table(content)
        table_extraction = extract_markdown_table(
            content,
            page=first_position.get("page"),
            bbox=first_position.get("bbox"),
            source_element_id=f"media:{media_index}",
        )
        table_detection_model = self._table_detection_model_metadata(image_obj)
        structure_model = self._table_structure_model_metadata(image_obj)
        structure_detections = self._table_structure_detections_from_metadata(structure_model)
        if table_extraction is None and isinstance(image_obj, PILImage.Image) and structure_detections:
            table_extraction = table_extraction_from_structure_detections(
                structure_detections,
                image_size=image_obj.size,
                page=first_position.get("page"),
                bbox=first_position.get("bbox"),
                source_element_id=f"media:{media_index}",
            )
        return {
            "positions": positions,
            "first_position": first_position,
            "table_profile": table_profile,
            "table_extraction": table_extraction,
            "table_detection_model": table_detection_model,
            "structure_model": structure_model,
            "is_table": table_profile is not None or table_extraction is not None,
        }

    @staticmethod
    def _apply_table_profile_metadata(meta: dict[str, Any], *, table_profile: Any, table_extraction: Any) -> None:
        if table_profile is not None:
            meta.update(table_profile.to_metadata())
            return
        if table_extraction is not None:
            meta.update(
                {
                    "table_columns": list(table_extraction.columns),
                    "table_shape": {
                        "rows": int(table_extraction.row_count),
                        "columns": int(table_extraction.col_count),
                    },
                }
            )

    def _apply_media_position_metadata(
        self,
        *,
        meta: dict[str, Any],
        positions: list[dict[str, Any]],
        first_position: dict[str, Any],
        derived_elements: list[dict[str, Any]],
        is_table: bool,
    ) -> None:
        if not positions:
            return
        meta["element_page"] = first_position.get("page")
        meta["element_bbox"] = first_position.get("bbox")
        if first_position.get("pages"):
            meta["cross_page_merge_pages"] = first_position.get("pages")
        caption = find_nearest_caption(
            derived_elements,
            media_kind="table" if is_table else "image",
            page=meta.get("element_page"),
            bbox=meta.get("element_bbox"),
        )
        if caption is not None:
            meta["caption"] = caption

    def _apply_table_extraction_metadata(
        self,
        *,
        meta: dict[str, Any],
        image_obj: Any,
        table_extraction: Any,
        structure_model: dict[str, Any] | None,
        table_detection_model: dict[str, Any] | None,
    ) -> Any:
        if table_extraction is None:
            return None
        if isinstance(image_obj, PILImage.Image):
            rotation = select_table_rotation(image_obj)
            table_kind = classify_table_grid_type(image_obj)
            table_with_boxes = table_cells_with_uniform_bboxes(table_extraction, image_size=image_obj.size)
            ocr_lines = extract_ocr_lines_from_image(image_obj)
            binding = bind_ocr_lines_to_table_cells(table_with_boxes, ocr_lines)
            table_extraction = binding.table
            meta["table_image_algorithms"] = {
                "rotation": rotation.to_metadata(),
                "grid": table_kind.to_metadata(),
                "cell_ocr_binding": binding.metadata,
                "ocr_line_count": len(ocr_lines),
            }
        meta["table_extraction"] = table_extraction.to_metadata()
        meta["table_outputs"] = {
            "markdown": render_table_markdown(table_extraction),
            "html": render_table_html(table_extraction),
            "csv": render_table_csv(table_extraction),
        }
        if structure_model is not None:
            meta["table_structure_model"] = structure_model
        if table_detection_model is not None:
            meta["table_detection_model"] = table_detection_model
        return table_extraction

    @staticmethod
    def _media_element_attributes(
        *,
        is_table: bool,
        source_element_id: str,
        table_profile: Any,
        caption: Any,
        positions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        attributes = {
            "source_content_type": "table" if is_table else "image",
            "source_doc_type": "table" if is_table else "image",
            "source_backend": "deepdoc",
            "source_element_id": source_element_id,
        }
        if table_profile is not None:
            attributes.update(table_profile.to_metadata())
        if isinstance(caption, dict):
            attributes["caption_text"] = str(caption.get("text") or "")
            attributes["caption_source_element_id"] = caption.get("source_element_id")
        if positions:
            attributes["position_tag"] = positions[0]["tag"]
            attributes["position_tags"] = [item["tag"] for item in positions]
        return attributes

    def _media_document(
        self,
        *,
        media_index: int,
        image_obj: Any,
        content: str,
        base_meta: dict[str, Any],
        derived_elements: list[dict[str, Any]],
    ) -> Document:
        analysis = self._media_analysis(media_index=media_index, image_obj=image_obj, content=content)
        positions = analysis["positions"]
        first_position = analysis["first_position"]
        table_profile = analysis["table_profile"]
        table_extraction = analysis["table_extraction"]
        table_detection_model = analysis["table_detection_model"]
        structure_model = analysis["structure_model"]
        is_table = bool(analysis["is_table"])

        meta = dict(base_meta)
        meta["content_type"] = "table" if is_table else "image"
        meta["doc_type_kwd"] = "table" if is_table else "image"
        meta["element_id"] = f"deepdoc:media:{media_index}"
        meta["element_kind"] = "table" if is_table else "image"
        meta["element_text"] = content
        self._apply_table_profile_metadata(meta, table_profile=table_profile, table_extraction=table_extraction)
        self._apply_media_position_metadata(
            meta=meta,
            positions=positions,
            first_position=first_position,
            derived_elements=derived_elements,
            is_table=is_table,
        )
        table_extraction = self._apply_table_extraction_metadata(
            meta=meta,
            image_obj=image_obj,
            table_extraction=table_extraction,
            structure_model=structure_model,
            table_detection_model=table_detection_model,
        )

        source_element_id = f"media:{media_index}"
        meta["source_backend"] = "deepdoc"
        meta["source_element_id"] = source_element_id
        meta["element_attributes"] = self._media_element_attributes(
            is_table=is_table,
            source_element_id=source_element_id,
            table_profile=table_profile,
            caption=meta.get("caption"),
            positions=positions,
        )
        media_element = {
            "id": meta["element_id"],
            "kind": meta["element_kind"],
            "text": content,
            "page": meta.get("element_page"),
            "bbox": meta.get("element_bbox"),
            "attributes": meta.get("element_attributes") if isinstance(meta.get("element_attributes"), dict) else {},
        }
        chart_regions = detect_chart_regions([media_element])
        if chart_regions["count"]:
            meta["chart_regions"] = chart_regions
        if isinstance(image_obj, PILImage.Image):
            meta["document_image_profile"] = profile_document_image_with_models(
                image_obj,
                runtime=self._small_model_runtime,
            )
        meta["image"] = image_obj
        return Document(page_content=content, metadata=meta)

    def _media_documents(self, media: Any, *, base_meta: dict[str, Any], derived_elements: list[dict[str, Any]]) -> list[Document]:
        docs: list[Document] = []
        if not isinstance(media, list):
            return docs
        for media_index, item in enumerate(media):
            if not (isinstance(item, tuple) and len(item) == 2):
                continue
            image_obj, payload = item
            if image_obj is None:
                continue
            docs.append(
                self._media_document(
                    media_index=media_index,
                    image_obj=image_obj,
                    content=self._media_content(payload),
                    base_meta=base_meta,
                    derived_elements=derived_elements,
                )
            )
        return docs

    @staticmethod
    def _append_seal_documents(docs: list[Document], *, file_path: Path) -> list[Document]:
        if not bool(getattr(settings, "SEAL_RECOGNITION_ENABLED", False)):
            return docs
        try:
            from app.parsing.enrich import seal_recognition

            docs.extend(
                seal_recognition.extract_seal_documents_from_pdf(
                    file_path=file_path,
                    source=file_path.name,
                    parser_backend="deepdoc",
                )
            )
        except Exception as exc:  # pragma: no cover - defensive: never fail the main parse path
            warnings.warn(
                f"DeepDoc seal recognition skipped for {file_path.name}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
        return docs

    def _parse_pdf(self, file_path: Path) -> list[Document]:
        parser, sections, media, total_pages, stages_ms = self._parse_pdf_core(file_path)
        postprocess_t0 = time.perf_counter()
        runtime_metadata = self._small_model_runtime_metadata()
        base_meta = self._pdf_base_meta(file_path, runtime_metadata=runtime_metadata, total_pages=total_pages)

        section_records = self._section_records(sections)
        section_records, text_parts, derived_elements, section_tree, watermark_removal, header_footer_removal, reading_order_fix = self._prepare_section_content(section_records)
        docs: list[Document] = []
        text_doc = self._text_document_from_sections(
            merged_text="\n\n".join(text_parts).strip(),
            base_meta=base_meta,
            derived_elements=derived_elements,
            section_tree=section_tree,
            watermark_removal=watermark_removal,
            header_footer_removal=header_footer_removal,
            reading_order_fix=reading_order_fix,
        )
        if text_doc is not None:
            docs.append(text_doc)

        docs.extend(self._media_documents(media, base_meta=base_meta, derived_elements=derived_elements))
        docs = link_cross_page_table_documents(docs)
        docs = self._append_seal_documents(docs, file_path=file_path)
        if not docs:
            docs.append(Document(page_content="", metadata=dict(base_meta)))

        stages_ms["postprocess"] = _elapsed_ms_since(postprocess_t0)
        profile = self._build_deepdoc_profile(
            file_type="pdf",
            stages_ms=stages_ms,
            runtime_metadata=runtime_metadata,
            document_count=len(docs),
            section_count=len(section_records),
            media_count=_raw_item_count(media),
            total_pages=total_pages,
            ocr_recognition=self._ocr_recognition_profile_from_parser(parser),
        )
        return self._attach_deepdoc_profile(docs, profile)

    def parse(self, file_path: Path) -> list[Document]:
        ext = file_path.suffix.lower()
        if ext == ".docx":
            return self._parse_docx(file_path)
        if ext == ".pdf":
            return self._parse_pdf(file_path)
        raise ValueError(f"DeepDoc parser supports only .pdf/.docx, got: {ext or '(no ext)'}")
