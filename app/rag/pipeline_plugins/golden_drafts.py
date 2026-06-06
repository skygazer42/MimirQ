from __future__ import annotations

from typing import Any
from uuid import UUID

from app.rag.pipeline_plugins.contracts import EVALUABLE_METADATA_KEY
from app.services.regression_case_bundle import REGRESSION_CASE_BUNDLE_SCHEMA_V1


def _meta(chunk: Any) -> dict[str, Any]:
    value = getattr(chunk, "doc_metadata", None)
    return dict(value) if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _metadata_value(meta: dict[str, Any], key: str) -> Any:
    if key in meta:
        return meta.get(key)
    if "." not in key:
        return meta.get(key)
    cur: Any = meta
    for part in key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _format_question(template: str, meta: dict[str, Any]) -> str | None:
    values: dict[str, str] = {}
    cursor = 0
    while True:
        start = template.find("{", cursor)
        if start < 0:
            break
        end = template.find("}", start + 1)
        if end < 0:
            return None
        key = template[start + 1 : end].strip()
        if not key:
            return None
        raw = _metadata_value(meta, key)
        if isinstance(raw, (list, tuple, set)):
            value = "、".join(_text(v) for v in raw if _text(v))
        else:
            value = _text(raw)
        if not value:
            return None
        values[key] = value
        cursor = end + 1
    try:
        question = template.format(**values).strip()
    except Exception:
        return None
    return question or None


def _rule_fields(golden_rules: dict[str, Any], key: str) -> list[str]:
    raw_fields = golden_rules.get(key)
    if not isinstance(raw_fields, list):
        return []
    out: list[str] = []
    for field in raw_fields:
        value = _text(field)
        if value and value not in out:
            out.append(value)
    return out


def _templates_for_chunk(meta: dict[str, Any], golden_rules: dict[str, Any]) -> list[str]:
    query_templates = golden_rules.get("query_templates")
    if not isinstance(query_templates, dict):
        return []
    candidates = [_text(_metadata_value(meta, key)) for key in _rule_fields(golden_rules, "template_selector_fields")]
    candidates.append("default")
    out: list[str] = []
    for key in candidates:
        raw = query_templates.get(key)
        if not isinstance(raw, list):
            continue
        for item in raw:
            template = _text(item)
            if template:
                out.append(template)
        if out:
            break
    return out


def _expected_metadata(meta: dict[str, Any], golden_rules: dict[str, Any]) -> dict[str, Any] | None:
    raw_fields = golden_rules.get("expected_metadata")
    if not isinstance(raw_fields, list):
        raw_fields = []
    evaluable_meta = meta.get(EVALUABLE_METADATA_KEY)
    if not isinstance(evaluable_meta, dict):
        return None
    out: dict[str, Any] = {}
    for field in raw_fields:
        key = _text(field)
        if not key:
            continue
        value = _metadata_value(evaluable_meta, key)
        if value is None or value == "" or value == []:
            return None
        out[key] = value
    return out


def _reference_source(chunk: Any, meta: dict[str, Any]) -> dict[str, Any]:
    document_id = getattr(chunk, "document_id", None) or meta.get("document_id")
    chunk_id = getattr(chunk, "id", None) or meta.get("chunk_id")
    payload: dict[str, Any] = {
        "document_id": str(document_id),
        "chunk_id": str(chunk_id),
    }
    chunk_index = getattr(chunk, "chunk_index", None)
    if chunk_index is not None:
        payload["chunk_index"] = int(chunk_index)
    page_number = getattr(chunk, "page_number", None) or meta.get("page_number") or meta.get("page")
    if page_number:
        payload["page_number"] = int(page_number)
    start_char = getattr(chunk, "start_char", None)
    end_char = getattr(chunk, "end_char", None)
    if start_char is not None:
        payload["start_char"] = int(start_char)
    if end_char is not None:
        payload["end_char"] = int(end_char)
    for key in ("doc_pipeline_key", "pipeline_hash", "family_collapse_key", "hierarchy_family_key"):
        value = _text(meta.get(key))
        if value:
            payload[key] = value
    record_identity = meta.get("_record_identity")
    if isinstance(record_identity, dict) and _text(record_identity.get("key")):
        payload["record_identity"] = {
            "schema": _text(record_identity.get("schema")) or "mimirq.record_identity.v1",
            "key": _text(record_identity.get("key")),
            "fields": record_identity.get("fields") if isinstance(record_identity.get("fields"), dict) else {},
        }
    content = _text(getattr(chunk, "content", None))
    if content:
        payload["quote"] = content[:2000]
    return payload


def _tags(plugin_id: str, meta: dict[str, Any], golden_rules: dict[str, Any]) -> list[str]:
    out = [f"plugin:{plugin_id}", "golden_draft"]
    for key in _rule_fields(golden_rules, "tag_fields"):
        value = _text(_metadata_value(meta, key))
        if value and value not in out:
            out.append(value)
    return out


def build_golden_draft_bundle_from_chunks(
    *,
    dataset_id: UUID,
    chunks: list[Any],
    golden_rules: dict[str, Any],
    plugin_id: str,
    plugin_version: str | None = None,
    plugin_ref: str | None = None,
    plugin_package_hash: str | None = None,
    max_items: int = 500,
) -> dict[str, Any]:
    """
    Build a human-reviewable regression case bundle from indexed chunks.

    This does not write to DB. The returned payload matches
    `mimirq.regression_cases.v1` and can be imported through the existing
    regression case import API after human review.
    """
    if not isinstance(golden_rules, dict) or golden_rules.get("schema") != "mimirq.golden_rules.v1":
        return {"schema": REGRESSION_CASE_BUNDLE_SCHEMA_V1, "dataset_id": str(dataset_id), "items": []}

    cap = max(1, min(2000, int(max_items or 500)))
    seen_questions: set[str] = set()
    items: list[dict[str, Any]] = []
    plugin_extra = {"plugin_id": plugin_id}
    if _text(plugin_version):
        plugin_extra["plugin_version"] = _text(plugin_version)
    if _text(plugin_ref):
        plugin_extra["plugin_ref"] = _text(plugin_ref)
    if _text(plugin_package_hash):
        plugin_extra["plugin_package_hash"] = _text(plugin_package_hash)
    for chunk in chunks or []:
        meta = _meta(chunk)
        expected = _expected_metadata(meta, golden_rules)
        if expected is None:
            continue
        for template in _templates_for_chunk(meta, golden_rules):
            question = _format_question(template, meta)
            if not question or question in seen_questions:
                continue
            seen_questions.add(question)
            items.append(
                {
                    "question": question,
                    "expected_answer": _text(getattr(chunk, "content", None)) or None,
                    "reference_sources": [_reference_source(chunk, meta)],
                    "tags": _tags(plugin_id, meta, golden_rules),
                    "extra": {
                        "source": "plugin_golden_draft",
                        **plugin_extra,
                        "expected_metadata": expected,
                    },
                }
            )
            if len(items) >= cap:
                return {"schema": REGRESSION_CASE_BUNDLE_SCHEMA_V1, "dataset_id": str(dataset_id), "items": items}

    return {"schema": REGRESSION_CASE_BUNDLE_SCHEMA_V1, "dataset_id": str(dataset_id), "items": items}


__all__ = ["build_golden_draft_bundle_from_chunks"]
