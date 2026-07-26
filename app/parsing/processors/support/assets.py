"""Asset reference collection and inline-asset audit helpers."""
from typing import Any

from sqlalchemy.orm import Session

from app.models.document import Document as DBDocument
from app.parsing.processors.support.common import _PROCESSOR_CLEANUP_LOG_MESSAGE, logger
from app.parsing.processors.support.results import InlineAssetResult, ParseResult


def _asset_metadata(item: Any) -> dict[str, Any]:
    meta = getattr(item, "metadata", None)
    return meta if isinstance(meta, dict) else {}


def _collect_artifact_dir_from_meta(meta: dict[str, Any], artifact_dirs: set[str]) -> None:
    artifact_dir = meta.get("artifact_dir")
    if isinstance(artifact_dir, str) and artifact_dir.strip():
        artifact_dirs.add(artifact_dir.strip())


def _collect_image_ids_from_meta(meta: dict[str, Any], document_img_ids: set[str]) -> None:
    images = meta.get("images")
    if not isinstance(images, list):
        return
    for item in images:
        img_id = item.get("img_id") if isinstance(item, dict) else None
        if isinstance(img_id, str) and img_id.strip():
            document_img_ids.add(img_id)


def _collect_item_asset_refs(
    items: list[Any] | None,
    *,
    document_img_ids: set[str],
    artifact_dirs: set[str],
    collect_images: bool,
) -> None:
    for item in items or []:
        meta = _asset_metadata(item)
        _collect_artifact_dir_from_meta(meta, artifact_dirs)
        if collect_images:
            _collect_image_ids_from_meta(meta, document_img_ids)


def _collect_parser_asset_refs(
    parsed: ParseResult,
    *,
    document_img_ids: set[str],
    artifact_dirs: set[str],
) -> None:
    _collect_item_asset_refs(
        parsed.documents,
        document_img_ids=document_img_ids,
        artifact_dirs=artifact_dirs,
        collect_images=True,
    )
    _collect_item_asset_refs(
        parsed.chunks,
        document_img_ids=document_img_ids,
        artifact_dirs=artifact_dirs,
        collect_images=False,
    )


def _inline_asset_audit_needed(inline_result: InlineAssetResult) -> bool:
    return (
        int(getattr(inline_result, "image_codes_added", 0) or 0) > 0
        or isinstance(getattr(inline_result, "image_code_audit", None), dict)
        or int(getattr(inline_result, "captions_added", 0) or 0) > 0
        or isinstance(getattr(inline_result, "caption_audit", None), dict)
        or int(getattr(inline_result, "formulas_added", 0) or 0) > 0
        or isinstance(getattr(inline_result, "formula_audit", None), dict)
        or int(getattr(inline_result, "charts_added", 0) or 0) > 0
        or isinstance(getattr(inline_result, "chart_audit", None), dict)
    )


def _apply_inline_asset_audit_patch(
    db: Session,
    db_document: DBDocument,
    inline_result: InlineAssetResult,
) -> None:
    if not _inline_asset_audit_needed(inline_result):
        return

    try:
        meta_patch = dict(db_document.doc_metadata or {})
        field_specs = (
            ("image_codes_added", "image_codes_added", None, None, "image_code_audit", "image_code_audit"),
            ("image_captions_added", "captions_added", "image_caption_backend", "caption_backend", "image_caption_audit", "caption_audit"),
            ("formula_ocr_added", "formulas_added", "formula_ocr_backend", "formula_backend", "formula_ocr_audit", "formula_audit"),
            ("chart_data_added", "charts_added", "chart_data_backend", "chart_backend", "chart_data_audit", "chart_audit"),
        )
        for count_key, count_attr, backend_key, backend_attr, audit_key, audit_attr in field_specs:
            meta_patch[count_key] = int(getattr(inline_result, count_attr, 0) or 0)
            backend_value = getattr(inline_result, backend_attr, None) if backend_attr else None
            if backend_key and backend_value:
                meta_patch[backend_key] = str(backend_value or "")
            audit_value = getattr(inline_result, audit_attr, None)
            if isinstance(audit_value, dict):
                meta_patch[audit_key] = dict(audit_value or {})
        db_document.doc_metadata = meta_patch
        db.commit()
        db.refresh(db_document)
    except Exception as exc:
        logger.debug(_PROCESSOR_CLEANUP_LOG_MESSAGE, exc)


def _chunk_has_asset(meta: dict[str, Any]) -> bool:
    doc_type = str(meta.get("doc_type_kwd") or "").lower()
    if doc_type in {"image", "table"}:
        return True
    if meta.get("image") is not None:
        return True
    if isinstance(meta.get("image_path"), str) and meta.get("image_path").strip():
        return True
    return bool(meta.get("img_id") or meta.get("image_id") or meta.get("image_url"))
