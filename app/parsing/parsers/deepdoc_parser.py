from __future__ import annotations

import re
import time
import warnings
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any, TypedDict

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
from app.parsing.enrich.header_footer_remover import HeaderFooterRemovalResult, remove_repeated_header_footer_elements
from app.parsing.enrich.reading_order_fixer import ReadingOrderFixResult, fix_reading_order_elements
from app.parsing.enrich.section_tree import add_section_paths, build_section_tree
from app.parsing.enrich.table_canonical import MarkdownTableProfile, extract_markdown_table, profile_markdown_table
from app.parsing.enrich.table_cell_schema import TableExtraction
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
from app.parsing.enrich.watermark_detector import WatermarkRemovalResult, remove_document_watermark_elements
from app.parsing.models.runtime import SmallModelRuntime
from app.parsing.models.table_transformer_onnx import predict_table_structure_detections
from app.parsing.utils.block_schema import build_block_element, parse_position_tags

if TYPE_CHECKING:
    from app.deepdoc.parser import DocxParser as DeepDocDocxParser

_HEADING_LEVEL_RE = re.compile(r"(\d+)")


class _SectionRecord(TypedDict):
    text: str
    element: dict[str, Any]


class _TableModelMetadata(TypedDict):
    model: dict[str, Any]
    detections: list[dict[str, Any]]
    detection_count: int


class _MediaAnalysis(TypedDict):
    positions: list[dict[str, Any]]
    table_profile: MarkdownTableProfile | None
    table_extraction: TableExtraction | None
    table_detection_model: _TableModelMetadata | None
    structure_model: _TableModelMetadata | None
    is_table: bool


def _elapsed_ms_since(start: float) -> int:
    return max(0, int(round((time.perf_counter() - start) * 1000.0)))


def _looks_like_heading_style(style_name: str) -> bool:
    style = style_name.strip()
    if not style:
        return False
    return style.lower().startswith("heading") or "标题" in style


def _heading_level(style_name: str) -> int:
    match = _HEADING_LEVEL_RE.search(style_name.strip())
    if not match:
        return 2
    try:
        level = int(match.group(1))
    except Exception:
        return 2
    return max(1, min(6, level))


def _looks_like_list_style(style_name: str) -> bool:
    style = style_name.strip().lower()
    return "list" in style or "bullet" in style or "列表" in style


def _list_marker(style_name: str) -> str:
    style = style_name.strip().lower()
    if "number" in style or "编号" in style or "序号" in style:
        return "1."
    return "-"


def _small_model_summary(runtime_metadata: dict[str, Any]) -> dict[str, Any]:
    unavailable_tasks = [task for task, item in runtime_metadata.items() if not item["available"]]
    return {
        "task_count": len(runtime_metadata),
        "available_count": len(runtime_metadata) - len(unavailable_tasks),
        "unavailable_count": len(unavailable_tasks),
        "unavailable_tasks": unavailable_tasks,
    }


def _build_deepdoc_profile(
    *,
    file_type: str,
    stages_ms: dict[str, int],
    runtime_metadata: dict[str, Any],
    document_count: int,
    section_count: int,
    media_count: int,
    total_pages: int | None = None,
    ocr_recognition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "schema": "mimirq.deepdoc_profile.v1",
        "engine": "deepdoc",
        "file_type": file_type,
        "stages_ms": dict(stages_ms),
        "document_count": document_count,
        "section_count": section_count,
        "media_count": media_count,
        "small_model_summary": _small_model_summary(runtime_metadata),
    }
    if total_pages is not None and total_pages > 0:
        profile["total_pages"] = total_pages
    if ocr_recognition:
        profile["ocr_recognition"] = dict(ocr_recognition)
    return profile


def _attach_deepdoc_profile(documents: list[Document], profile: dict[str, Any]) -> list[Document]:
    for doc in documents:
        meta = dict(doc.metadata)
        meta["deepdoc_profile"] = dict(profile)
        doc.metadata = meta
    return documents


def _ocr_recognition_profile_from_parser(parser: DeepDocPdfParser) -> dict[str, Any] | None:
    profile = parser.ocr.last_recognition_profile
    return dict(profile) if profile else None


def _table_structure_detections_from_metadata(
    structure_model: _TableModelMetadata | None,
) -> list[TableStructureDetection]:
    if structure_model is None:
        return []
    return [
        TableStructureDetection(
            label=item["label"],
            score=item["score"],
            bbox=item["bbox"],
        )
        for item in structure_model["detections"]
    ]


def _docx_section_parts(sections: list[tuple[str, str | None]]) -> list[str]:
    parts: list[str] = []
    for raw_text, style_name in sections:
        text = raw_text.strip()
        if not text:
            continue
        if style_name and _looks_like_heading_style(style_name):
            parts.append(f"{'#' * _heading_level(style_name)} {text}")
        elif style_name and _looks_like_list_style(style_name):
            parts.append(f"{_list_marker(style_name)} {text}")
        else:
            parts.append(text)
    return parts


def _docx_table_parts(tables: list[list[str]]) -> list[str]:
    parts: list[str] = []
    for table in tables:
        joined = "\n".join(value.strip() for value in table if value.strip()).strip()
        if joined:
            parts.append(joined)
    return parts


def _pdf_base_meta(file_path: Path, *, runtime_metadata: dict[str, Any], total_pages: int | None) -> dict[str, Any]:
    base_meta = {
        "source": file_path.name,
        "file_type": "pdf",
        "parser_backend": "deepdoc",
        "small_model_runtime": runtime_metadata,
    }
    if total_pages:
        base_meta["total_pages"] = total_pages
    return base_meta


def _section_records(sections: str) -> list[_SectionRecord]:
    text = sections.strip()
    if not text:
        return []
    return [
        {
            "text": text,
            "element": build_block_element(
                text=text,
                kind="text",
                source_backend="deepdoc",
                source_element_id="section:0",
                element_id="deepdoc:section:0",
                attributes={"block_index": 0},
            ),
        }
    ]


def _filter_records_by_elements(
    records: list[_SectionRecord],
    elements: list[dict[str, Any]],
    *,
    changed: bool,
) -> list[_SectionRecord]:
    if not changed:
        return records
    kept_ids = {element["id"] for element in elements}
    return [record for record in records if record["element"]["id"] in kept_ids]


def _prepare_section_content(
    section_records: list[_SectionRecord],
) -> tuple[
    list[_SectionRecord],
    list[str],
    list[dict[str, Any]],
    list[dict[str, Any]],
    WatermarkRemovalResult,
    HeaderFooterRemovalResult,
    ReadingOrderFixResult,
]:
    watermark_removal = remove_document_watermark_elements([record["element"] for record in section_records])
    section_records = _filter_records_by_elements(
        section_records,
        watermark_removal.elements,
        changed=watermark_removal.changed,
    )

    header_footer_removal = remove_repeated_header_footer_elements([record["element"] for record in section_records])
    section_records = _filter_records_by_elements(
        section_records,
        header_footer_removal.elements,
        changed=header_footer_removal.changed,
    )

    reading_order_fix = fix_reading_order_elements([record["element"] for record in section_records])
    records_by_id = {record["element"]["id"]: record for record in section_records}
    section_records = [records_by_id[element["id"]] for element in reading_order_fix.elements]

    text_parts = [record["text"] for record in section_records]
    derived_elements = [dict(record["element"]) for record in section_records]
    section_tree = build_section_tree(derived_elements)
    if section_tree:
        derived_elements = add_section_paths(derived_elements, section_tree)
    return (
        section_records,
        text_parts,
        derived_elements,
        section_tree,
        watermark_removal,
        header_footer_removal,
        reading_order_fix,
    )


def _text_document_from_sections(
    *,
    merged_text: str,
    base_meta: dict[str, Any],
    derived_elements: list[dict[str, Any]],
    section_tree: list[dict[str, Any]],
    watermark_removal: WatermarkRemovalResult,
    header_footer_removal: HeaderFooterRemovalResult,
    reading_order_fix: ReadingOrderFixResult,
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


def _media_content(payload: str | list[str]) -> str:
    if isinstance(payload, str):
        content = payload.strip()
    else:
        content = "\n".join(item.strip() for item in payload if item.strip()).strip()
    if not content:
        return "image"
    if len(content) > 900:
        return content[:900].rstrip() + "..."
    return content


def _apply_table_profile_metadata(
    meta: dict[str, Any], *, table_profile: MarkdownTableProfile | None, table_extraction: TableExtraction | None
) -> None:
    if table_profile is not None:
        meta.update(table_profile.to_metadata())
        return
    if table_extraction is not None:
        meta.update(
            {
                "table_columns": list(table_extraction.columns),
                "table_shape": {
                    "rows": table_extraction.row_count,
                    "columns": table_extraction.col_count,
                },
            }
        )


def _apply_media_position_metadata(
    *,
    meta: dict[str, Any],
    positions: list[dict[str, Any]],
    derived_elements: list[dict[str, Any]],
    is_table: bool,
) -> None:
    if not positions:
        return
    first_position = positions[0]
    meta["element_page"] = first_position["page"]
    meta["element_bbox"] = first_position["bbox"]
    meta["cross_page_merge_pages"] = first_position["pages"]
    caption = find_nearest_caption(
        derived_elements,
        media_kind="table" if is_table else "image",
        page=first_position["page"],
        bbox=first_position["bbox"],
    )
    if caption is not None:
        meta["caption"] = caption


def _apply_table_extraction_metadata(
    *,
    meta: dict[str, Any],
    image_obj: Any,
    table_extraction: TableExtraction | None,
    structure_model: _TableModelMetadata | None,
    table_detection_model: _TableModelMetadata | None,
) -> None:
    if table_extraction is None:
        return
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


def _media_element_attributes(
    *,
    is_table: bool,
    source_element_id: str,
    table_profile: MarkdownTableProfile | None,
    caption: dict[str, Any] | None,
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
    if caption is not None:
        attributes["caption_text"] = caption["text"]
        attributes["caption_source_element_id"] = caption["source_element_id"]
    if positions:
        attributes["position_tag"] = positions[0]["tag"]
        attributes["position_tags"] = [item["tag"] for item in positions]
    return attributes


def _append_seal_documents(docs: list[Document], *, file_path: Path) -> list[Document]:
    if not bool(settings.SEAL_RECOGNITION_ENABLED):
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


class DeepDocParser:
    """Bridge DeepDoc's parser so we can reuse it inside our pipeline."""

    def __init__(self) -> None:
        self._pdf_parser: DeepDocPdfParser | None = None
        self._docx_parser: DeepDocDocxParser | None = None
        self._small_model_runtime = SmallModelRuntime()
        self._lock = Lock()

    def _ensure_pdf_parser(self) -> DeepDocPdfParser:
        if self._pdf_parser is None:
            self._pdf_parser = DeepDocPdfParser()
        return self._pdf_parser

    def _ensure_docx_parser(self) -> DeepDocDocxParser:
        if self._docx_parser is None:
            from app.deepdoc.parser import DocxParser as DeepDocDocxParser

            self._docx_parser = DeepDocDocxParser()
        return self._docx_parser

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

    def _table_structure_model_metadata(self, image_obj: Any) -> _TableModelMetadata | None:
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

    def _table_detection_model_metadata(self, image_obj: Any) -> _TableModelMetadata | None:
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
        merged_text = "\n\n".join(_docx_section_parts(sections) + _docx_table_parts(tables)).strip()
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
        profile = _build_deepdoc_profile(
            file_type="docx",
            stages_ms=stages_ms,
            runtime_metadata=runtime_metadata,
            document_count=len(docs),
            section_count=len(sections),
            media_count=len(tables),
        )
        return _attach_deepdoc_profile(docs, profile)

    def _parse_pdf_core(
        self, file_path: Path
    ) -> tuple[DeepDocPdfParser, str, list[tuple[Any, str | list[str]]], int | None, dict[str, int]]:
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

    def _media_analysis(self, *, media_index: int, image_obj: Any, content: str) -> _MediaAnalysis:
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
        structure_detections = _table_structure_detections_from_metadata(structure_model)
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
            "table_profile": table_profile,
            "table_extraction": table_extraction,
            "table_detection_model": table_detection_model,
            "structure_model": structure_model,
            "is_table": table_profile is not None or table_extraction is not None,
        }

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
        table_profile = analysis["table_profile"]
        table_extraction = analysis["table_extraction"]
        table_detection_model = analysis["table_detection_model"]
        structure_model = analysis["structure_model"]
        is_table = analysis["is_table"]

        meta = dict(base_meta)
        meta["content_type"] = "table" if is_table else "image"
        meta["doc_type_kwd"] = "table" if is_table else "image"
        meta["element_id"] = f"deepdoc:media:{media_index}"
        meta["element_kind"] = "table" if is_table else "image"
        meta["element_text"] = content
        _apply_table_profile_metadata(meta, table_profile=table_profile, table_extraction=table_extraction)
        _apply_media_position_metadata(
            meta=meta,
            positions=positions,
            derived_elements=derived_elements,
            is_table=is_table,
        )
        _apply_table_extraction_metadata(
            meta=meta,
            image_obj=image_obj,
            table_extraction=table_extraction,
            structure_model=structure_model,
            table_detection_model=table_detection_model,
        )

        source_element_id = f"media:{media_index}"
        meta["source_backend"] = "deepdoc"
        meta["source_element_id"] = source_element_id
        meta["element_attributes"] = _media_element_attributes(
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
            "attributes": meta["element_attributes"],
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

    def _media_documents(
        self,
        media: list[tuple[Any, str | list[str]]],
        *,
        base_meta: dict[str, Any],
        derived_elements: list[dict[str, Any]],
    ) -> list[Document]:
        docs: list[Document] = []
        for media_index, (image_obj, payload) in enumerate(media):
            if image_obj is None:
                continue
            docs.append(
                self._media_document(
                    media_index=media_index,
                    image_obj=image_obj,
                    content=_media_content(payload),
                    base_meta=base_meta,
                    derived_elements=derived_elements,
                )
            )
        return docs

    def _parse_pdf(self, file_path: Path) -> list[Document]:
        parser, sections, media, total_pages, stages_ms = self._parse_pdf_core(file_path)
        postprocess_t0 = time.perf_counter()
        runtime_metadata = self._small_model_runtime_metadata()
        base_meta = _pdf_base_meta(file_path, runtime_metadata=runtime_metadata, total_pages=total_pages)

        section_records = _section_records(sections)
        (
            section_records,
            text_parts,
            derived_elements,
            section_tree,
            watermark_removal,
            header_footer_removal,
            reading_order_fix,
        ) = _prepare_section_content(section_records)
        docs: list[Document] = []
        text_doc = _text_document_from_sections(
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
        docs = _append_seal_documents(docs, file_path=file_path)
        if not docs:
            docs.append(Document(page_content="", metadata=dict(base_meta)))

        stages_ms["postprocess"] = _elapsed_ms_since(postprocess_t0)
        profile = _build_deepdoc_profile(
            file_type="pdf",
            stages_ms=stages_ms,
            runtime_metadata=runtime_metadata,
            document_count=len(docs),
            section_count=len(section_records),
            media_count=len(media),
            total_pages=total_pages,
            ocr_recognition=_ocr_recognition_profile_from_parser(parser),
        )
        return _attach_deepdoc_profile(docs, profile)

    def parse(self, file_path: Path) -> list[Document]:
        ext = file_path.suffix.lower()
        if ext == ".docx":
            return self._parse_docx(file_path)
        if ext == ".pdf":
            return self._parse_pdf(file_path)
        raise ValueError(f"DeepDoc parser supports only .pdf/.docx, got: {ext or '(no ext)'}")
