from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document

RETRIEVAL_TEXT_METADATA_KEY = "_retrieval_text"
RETRIEVAL_DISPLAY_CONTENT_METADATA_KEY = "_retrieval_display_content"
INDEXED_METADATA_KEY = "_indexed_metadata"
DISPLAY_METADATA_KEY = "_display_metadata"
EVALUABLE_METADATA_KEY = "_evaluable_metadata"
RECORD_IDENTITY_METADATA_KEY = "_record_identity"
METADATA_SCHEMA_VIEW_KEYS = (
    INDEXED_METADATA_KEY,
    DISPLAY_METADATA_KEY,
    EVALUABLE_METADATA_KEY,
    RECORD_IDENTITY_METADATA_KEY,
)

_FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,119}$")
_SUPPORTED_TYPES = {"string", "integer", "number", "boolean", "array", "object"}
_SUPPORTED_METADATA_STAGES = {"governance", "chunk", "kg"}
_SUPPORTED_RETRIEVAL_TEXT_STAGES = {"governance", "chunk"}
_SUPPORTED_KG_METADATA_FIELD_PREFIXES = ("metadata.", "references.", "extra_data.")
_SUPPORTED_METADATA_FIELD_KEYS = {
    "name",
    "type",
    "required",
    "stages",
    "filterable",
    "display",
    "evaluable",
    "max_length",
    "enum",
}
_SUPPORTED_RETRIEVAL_STAGE_KEYS = {"fields"}
_SUPPORTED_RETRIEVAL_FIELD_KEYS = {"metadata", "content", "label"}
_SUPPORTED_RETRIEVAL_POLICY_BOOST_KEYS = {"metadata", "weight", "match"}
_SUPPORTED_RETRIEVAL_POLICY_QUERY_VALUE_KEYS = {"metadata", "value", "values", "terms"}
_SUPPORTED_RETRIEVAL_POLICY_ANCHOR_KEYS = {"metadata", "weight", "aliases"}
_SUPPORTED_RETRIEVAL_POLICY_FALLBACK_KEYS = {"enabled", "expand_top_k_multiplier"}
_SUPPORTED_RETRIEVAL_POLICY_RESPONSE_COMPACTION_KEYS = {
    "enabled",
    "min_top_score",
    "relative_score_floor",
    "min_records",
}
_SUPPORTED_RETRIEVAL_POLICY_RESPONSE_HINT_KEYS = {
    "answer_prefix",
    "source_prefix",
    "structured_labels",
    "answer_labels",
    "answer_keywords",
    "answer_highlight_metadata",
    "existing_hint_prefixes",
    "anchor_only_chunk_kinds",
    "anchor_only_markers",
    "groups",
    "enumeration",
}
_SUPPORTED_RETRIEVAL_POLICY_RESPONSE_HINT_GROUP_KEYS = {
    "name",
    "required_any_labels",
    "hint_labels",
    "question_from_query_label",
    "answer_label",
    "query_gate",
}
_SUPPORTED_RETRIEVAL_POLICY_RESPONSE_HINT_QUERY_GATE_KEYS = {
    "content_labels",
    "metadata",
    "min_chars",
    "min_common_chars",
}
_SUPPORTED_RETRIEVAL_POLICY_RESPONSE_HINT_ENUMERATION_KEYS = {
    "enabled",
    "intro_terms",
    "query_terms",
    "max_terms",
    "named_markers",
    "prefix",
    "message_template",
    "term_separator",
}
_SUPPORTED_RETRIEVAL_POLICY_MATCHES = {"exact", "contains", "overlap", "fuzzy_overlap"}
_RESERVED_METADATA_PREFIX = "_"
_PLATFORM_OWNED_METADATA_FIELD_ROOTS = {
    "source",
    "file_path",
    "file_name",
    "file_sha256",
    "document_id",
    "chunk_id",
    "dataset_id",
    "tenant_id",
    "parser_backend",
    "resolved_chunk_strategy",
    "content_hash",
    "simhash64",
    "chunk_quality",
}
RESERVED_PLATFORM_METADATA_VIEW_KEYS = (
    *METADATA_SCHEMA_VIEW_KEYS,
    RETRIEVAL_TEXT_METADATA_KEY,
    RETRIEVAL_DISPLAY_CONTENT_METADATA_KEY,
)
_RESERVED_PLATFORM_METADATA_VIEW_KEYS = RESERVED_PLATFORM_METADATA_VIEW_KEYS


class PipelinePluginContractError(ValueError):
    """Raised when plugin contract declarations or outputs are invalid."""


@dataclass(frozen=True)
class MetadataField:
    name: str
    type: str
    required: bool
    stages: tuple[str, ...]
    filterable: bool
    display: bool
    evaluable: bool
    max_length: int | None = None
    enum: tuple[Any, ...] | None = None


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_string_list(value: Any, *, field_label: str | None = None) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if field_label is not None and not isinstance(item, str):
            raise PipelinePluginContractError(f"{field_label}[{index}] must be a string")
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return tuple(out)


def _unknown_keys(value: dict[str, Any], supported: set[str]) -> list[str]:
    return sorted(str(key or "").strip() or "<empty>" for key in value if str(key or "").strip() not in supported)


def _uses_reserved_metadata_namespace(name: str) -> bool:
    return any(part.startswith(_RESERVED_METADATA_PREFIX) for part in str(name or "").split(".") if part)


def _uses_platform_owned_metadata_field_name(name: str) -> bool:
    text = str(name or "").strip()
    if text.startswith("metadata."):
        text = text.split(".", 1)[1]
    root = text.split(".", 1)[0]
    return root in _PLATFORM_OWNED_METADATA_FIELD_ROOTS


def _validate_contract_stage_list(
    value: Any,
    *,
    field_label: str,
    allow_missing: bool = True,
) -> tuple[str, ...]:
    if value is None and allow_missing:
        return ()
    if not isinstance(value, list):
        raise PipelinePluginContractError(f"{field_label} stages must be a list")
    stages = _as_string_list(value, field_label=f"{field_label} stages")
    unsupported = [stage for stage in stages if stage not in _SUPPORTED_METADATA_STAGES]
    if unsupported:
        missing_text = ", ".join(unsupported[:20])
        raise PipelinePluginContractError(f"{field_label} has unsupported stages: {missing_text}")
    return stages


def _optional_bool(value: Any, *, field_label: str, key: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise PipelinePluginContractError(f"{field_label} {key} must be a boolean")
    return value


def _optional_int(value: Any, *, field_label: str, key: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise PipelinePluginContractError(f"{field_label} {key} must be an integer")
    return value


def parse_metadata_schema(schema: dict[str, Any] | None) -> list[MetadataField]:
    if not schema:
        return []
    if schema.get("schema") != "mimirq.metadata_schema.v1":
        raise PipelinePluginContractError("metadata_schema.schema must be mimirq.metadata_schema.v1")
    raw_fields = schema.get("fields")
    if not isinstance(raw_fields, list):
        raise PipelinePluginContractError("metadata_schema.fields must be a list")

    fields: list[MetadataField] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_fields):
        if not isinstance(raw, dict):
            raise PipelinePluginContractError(f"metadata field at index {index} must be an object")
        item = raw
        raw_name = item.get("name")
        if not isinstance(raw_name, str):
            raise PipelinePluginContractError(f"metadata field at index {index} name must be a string")
        name = raw_name.strip()
        if not name or not _FIELD_NAME_RE.fullmatch(name):
            raise PipelinePluginContractError(f"metadata field at index {index} has invalid name")
        if _uses_reserved_metadata_namespace(name):
            raise PipelinePluginContractError(f"metadata field '{name}' uses reserved platform metadata namespace")
        if _uses_platform_owned_metadata_field_name(name):
            raise PipelinePluginContractError(f"metadata field '{name}' uses platform-owned metadata field name")
        unknown = _unknown_keys(item, _SUPPORTED_METADATA_FIELD_KEYS)
        if unknown:
            raise PipelinePluginContractError(f"metadata field '{name}' contains unknown fields: {', '.join(unknown[:20])}")
        if name in seen:
            raise PipelinePluginContractError(f"metadata field '{name}' is duplicated")
        seen.add(name)
        field_type = str(item.get("type") or "string").strip().lower()
        if field_type not in _SUPPORTED_TYPES:
            raise PipelinePluginContractError(f"metadata field '{name}' has unsupported type '{field_type}'")
        max_length = _optional_int(item.get("max_length"), field_label=f"metadata field '{name}'", key="max_length")
        if max_length is not None:
            if max_length < 1 or max_length > 100_000:
                raise PipelinePluginContractError(f"metadata field '{name}' max_length is out of range")
        stages = _validate_contract_stage_list(
            item.get("stages"),
            field_label=f"metadata field '{name}'",
        )
        if "kg" in stages and not name.startswith(_SUPPORTED_KG_METADATA_FIELD_PREFIXES):
            raise PipelinePluginContractError(
                f"metadata field '{name}' used by kg must start with metadata., references., or extra_data."
            )
        enum_raw = item.get("enum")
        if enum_raw is not None and not isinstance(enum_raw, list):
            raise PipelinePluginContractError(f"metadata field '{name}' enum must be a list")
        enum_values = tuple(enum_raw) if enum_raw else None
        fields.append(
            MetadataField(
                name=name,
                type=field_type,
                required=_optional_bool(item.get("required"), field_label=f"metadata field '{name}'", key="required"),
                stages=stages,
                filterable=_optional_bool(
                    item.get("filterable"),
                    field_label=f"metadata field '{name}'",
                    key="filterable",
                ),
                display=_optional_bool(item.get("display"), field_label=f"metadata field '{name}'", key="display"),
                evaluable=_optional_bool(
                    item.get("evaluable"),
                    field_label=f"metadata field '{name}'",
                    key="evaluable",
                ),
                max_length=max_length,
                enum=enum_values,
            )
        )
    raw_identity_fields = schema.get("record_identity")
    if raw_identity_fields is not None and not isinstance(raw_identity_fields, list):
        raise PipelinePluginContractError("metadata_schema.record_identity must be a list")
    identity_fields = _as_string_list(raw_identity_fields, field_label="metadata_schema.record_identity")
    missing_identity_fields = [field_name for field_name in identity_fields if field_name not in seen]
    if missing_identity_fields:
        missing_text = ", ".join(missing_identity_fields[:20])
        raise PipelinePluginContractError(
            f"metadata_schema.record_identity references undeclared metadata fields: {missing_text}"
        )
    return fields


def _stage_applies(field: MetadataField, stage: str) -> bool:
    if not field.stages:
        return True
    normalized = "chunk" if stage == "chunking" else stage
    return normalized in field.stages


def _type_ok(value: Any, field_type: str) -> bool:
    if field_type == "string":
        return isinstance(value, str)
    if field_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if field_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if field_type == "boolean":
        return isinstance(value, bool)
    if field_type == "array":
        return isinstance(value, list)
    if field_type == "object":
        return isinstance(value, dict)
    return False


def validate_documents_metadata(
    documents: Iterable[Document],
    *,
    metadata_schema: dict[str, Any] | None,
    stage: str,
) -> dict[str, Any]:
    fields = parse_metadata_schema(metadata_schema)
    docs = list(documents or [])
    errors: list[dict[str, Any]] = []
    if not fields:
        return {"ok": True, "checked": len(docs), "errors": []}

    for doc_index, doc in enumerate(docs):
        meta = dict(doc.metadata or {})
        for field in fields:
            if not _stage_applies(field, stage):
                continue
            value = meta.get(field.name)
            missing = value is None or value == "" or value == []
            if field.required and missing:
                errors.append({"index": doc_index, "field": field.name, "reason": "required"})
                continue
            if missing:
                continue
            if not _type_ok(value, field.type):
                errors.append({"index": doc_index, "field": field.name, "reason": f"expected_{field.type}"})
                continue
            if field.max_length is not None and isinstance(value, str) and len(value) > field.max_length:
                errors.append({"index": doc_index, "field": field.name, "reason": "max_length"})
                continue
            if field.enum is not None and value not in field.enum:
                errors.append({"index": doc_index, "field": field.name, "reason": "enum"})

    return {"ok": not errors, "checked": len(docs), "errors": errors}


def _kg_event_contract_metadata(event: Any) -> dict[str, Any]:
    return {
        "metadata": _as_dict(getattr(event, "metadata", None)),
        "references": _as_dict(getattr(event, "references", None)),
        "extra_data": _as_dict(getattr(event, "extra_data", None)),
        "title": getattr(event, "title", None),
        "summary": getattr(event, "summary", None),
        "content": getattr(event, "content", None),
    }


def validate_kg_events_metadata(
    events: Iterable[Any],
    *,
    metadata_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    fields = [field for field in parse_metadata_schema(metadata_schema) if "kg" in field.stages]
    items = list(events or [])
    errors: list[dict[str, Any]] = []
    if not fields:
        return {"ok": True, "checked": len(items), "errors": []}

    for event_index, event in enumerate(items):
        meta = _kg_event_contract_metadata(event)
        for field in fields:
            value = _value_from_metadata(meta, field.name)
            missing = value is None or value == "" or value == []
            if field.required and missing:
                errors.append({"index": event_index, "field": field.name, "reason": "required"})
                continue
            if missing:
                continue
            if not _type_ok(value, field.type):
                errors.append({"index": event_index, "field": field.name, "reason": f"expected_{field.type}"})
                continue
            if field.max_length is not None and isinstance(value, str) and len(value) > field.max_length:
                errors.append({"index": event_index, "field": field.name, "reason": "max_length"})
                continue
            if field.enum is not None and value not in field.enum:
                errors.append({"index": event_index, "field": field.name, "reason": "enum"})

    return {"ok": not errors, "checked": len(items), "errors": errors}


def validate_no_reserved_platform_metadata_views(
    metadata: dict[str, Any] | None,
    *,
    field_label: str = "metadata",
) -> None:
    meta = _as_dict(metadata)
    for key in _RESERVED_PLATFORM_METADATA_VIEW_KEYS:
        if key in meta:
            raise PipelinePluginContractError(f"{field_label} must not contain reserved platform metadata field '{key}'")


def strip_reserved_platform_metadata_views(documents: Iterable[Document]) -> list[Document]:
    out: list[Document] = []
    for doc in documents or []:
        meta = dict(doc.metadata or {})
        for key in _RESERVED_PLATFORM_METADATA_VIEW_KEYS:
            meta.pop(key, None)
        out.append(Document(page_content=doc.page_content or "", metadata=meta, id=getattr(doc, "id", None)))
    return out


def summarize_contracts(
    *,
    metadata_schema: dict[str, Any] | None = None,
    retrieval_text_schema: dict[str, Any] | None = None,
    golden_rules: dict[str, Any] | None = None,
    retrieval_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fields = parse_metadata_schema(metadata_schema)
    retrieval_stages = []
    if isinstance(retrieval_text_schema, dict):
        stages = retrieval_text_schema.get("stages")
        if isinstance(stages, dict):
            retrieval_stages = sorted(str(k) for k in stages.keys())
    return {
        "metadata": {
            "schema": (metadata_schema or {}).get("schema") if isinstance(metadata_schema, dict) else None,
            "fields": [field.name for field in fields],
            "required_fields": [field.name for field in fields if field.required],
            "filterable_fields": [field.name for field in fields if field.filterable],
            "display_fields": [field.name for field in fields if field.display],
            "evaluable_fields": [field.name for field in fields if field.evaluable],
            "record_identity_fields": list(
                _as_string_list(metadata_schema.get("record_identity") if isinstance(metadata_schema, dict) else None)
            ),
        },
        "retrieval_text": {
            "schema": (retrieval_text_schema or {}).get("schema") if isinstance(retrieval_text_schema, dict) else None,
            "stages": retrieval_stages,
        },
        "golden": {
            "schema": (golden_rules or {}).get("schema") if isinstance(golden_rules, dict) else None,
            "enabled": bool(golden_rules),
        },
        "retrieval_policy": _summarize_retrieval_policy(retrieval_policy),
    }


def _summarize_retrieval_policy(retrieval_policy: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(retrieval_policy, dict):
        return {
            "schema": None,
            "query_expansion_fields": [],
            "query_expansion_value_fields": [],
            "filter_fields": [],
            "boost_fields": [],
            "rerank_features": [],
            "fallback_enabled": False,
            "response_compaction_enabled": False,
        }
    raw_boosts = retrieval_policy.get("boost_fields")
    boost_fields: list[str] = []
    if isinstance(raw_boosts, list):
        for raw in raw_boosts:
            if isinstance(raw, dict):
                field_name = str(raw.get("metadata") or "").strip()
                if field_name and field_name not in boost_fields:
                    boost_fields.append(field_name)
    raw_anchors = retrieval_policy.get("anchor_fields")
    anchor_fields: list[str] = []
    if isinstance(raw_anchors, list):
        for raw in raw_anchors:
            if isinstance(raw, dict):
                field_name = str(raw.get("metadata") or "").strip()
                if field_name and field_name not in anchor_fields:
                    anchor_fields.append(field_name)
    raw_value_mappings = retrieval_policy.get("query_expansion_values")
    value_fields: list[str] = []
    if isinstance(raw_value_mappings, list):
        for raw in raw_value_mappings:
            if isinstance(raw, dict):
                field_name = str(raw.get("metadata") or "").strip()
                if field_name and field_name not in value_fields:
                    value_fields.append(field_name)
    fallback = retrieval_policy.get("fallback")
    response_compaction = retrieval_policy.get("response_compaction")
    return {
        "schema": retrieval_policy.get("schema"),
        "query_expansion_fields": list(_as_string_list(retrieval_policy.get("query_expansion_fields"))),
        "query_expansion_value_fields": value_fields,
        "question_intent_terms": list(_as_string_list(retrieval_policy.get("question_intent_terms"))),
        "filter_fields": list(_as_string_list(retrieval_policy.get("filter_fields"))),
        "boost_fields": boost_fields,
        "anchor_fields": anchor_fields,
        "rerank_features": list(_as_string_list(retrieval_policy.get("rerank_features"))),
        "fallback_enabled": isinstance(fallback, dict) and fallback.get("enabled") is True,
        "response_compaction_enabled": (
            isinstance(response_compaction, dict) and response_compaction.get("enabled") is True
        ),
        "response_hints_enabled": isinstance(retrieval_policy.get("response_hints"), dict),
    }


def validate_golden_rules_metadata_fields(
    *,
    golden_rules: dict[str, Any] | None,
    metadata_schema: dict[str, Any] | None,
) -> None:
    if not isinstance(golden_rules, dict) or golden_rules.get("schema") != "mimirq.golden_rules.v1":
        return
    metadata_fields = parse_metadata_schema(metadata_schema)
    declared_fields = {field.name for field in metadata_fields}
    evaluable_fields = {field.name for field in metadata_fields if field.evaluable}
    for rule_key in ("expected_metadata", "answer_key_point_fields", "template_selector_fields", "tag_fields"):
        raw_rule_fields = golden_rules.get(rule_key)
        if raw_rule_fields is not None and not isinstance(raw_rule_fields, list):
            raise PipelinePluginContractError(f"golden_rules.{rule_key} must be a list")
        rule_fields = _as_string_list(raw_rule_fields, field_label=f"golden_rules.{rule_key}")
        missing = [field_name for field_name in rule_fields if field_name not in declared_fields]
        if missing:
            missing_text = ", ".join(missing[:20])
            raise PipelinePluginContractError(
                f"golden_rules.{rule_key} references undeclared metadata fields: {missing_text}"
            )
        if rule_key == "expected_metadata":
            if not rule_fields:
                raise PipelinePluginContractError("golden_rules.expected_metadata must declare at least one field")
            non_evaluable = [field_name for field_name in rule_fields if field_name not in evaluable_fields]
            if non_evaluable:
                non_evaluable_text = ", ".join(non_evaluable[:20])
                raise PipelinePluginContractError(
                    f"golden_rules.expected_metadata references non-evaluable metadata fields: {non_evaluable_text}"
                )
        if rule_key == "answer_key_point_fields":
            non_evaluable = [field_name for field_name in rule_fields if field_name not in evaluable_fields]
            if non_evaluable:
                non_evaluable_text = ", ".join(non_evaluable[:20])
                raise PipelinePluginContractError(
                    f"golden_rules.answer_key_point_fields references non-evaluable metadata fields: {non_evaluable_text}"
                )
    raw_templates = golden_rules.get("query_templates")
    if raw_templates is not None:
        if not isinstance(raw_templates, dict):
            raise PipelinePluginContractError("golden_rules.query_templates must be an object")
        for bucket, templates in raw_templates.items():
            bucket_name = str(bucket or "").strip() or "<empty>"
            if not isinstance(templates, list):
                raise PipelinePluginContractError(f"golden_rules.query_templates.{bucket_name} must be a list")
            for index, template in enumerate(templates):
                if not isinstance(template, str):
                    raise PipelinePluginContractError(
                        f"golden_rules.query_templates.{bucket_name}[{index}] must be a string"
                    )


def validate_retrieval_text_schema_metadata_fields(
    *,
    retrieval_text_schema: dict[str, Any] | None,
    metadata_schema: dict[str, Any] | None,
) -> None:
    if not isinstance(retrieval_text_schema, dict) or retrieval_text_schema.get("schema") != "mimirq.retrieval_text_schema.v1":
        return
    declared_fields = {field.name for field in parse_metadata_schema(metadata_schema)}
    stages = retrieval_text_schema.get("stages")
    if not isinstance(stages, dict):
        raise PipelinePluginContractError("retrieval_text_schema.stages must be an object")
    unsupported_stages = [
        str(stage_name or "").strip() or "<empty>"
        for stage_name in stages
        if str(stage_name or "").strip() not in _SUPPORTED_RETRIEVAL_TEXT_STAGES
    ]
    if unsupported_stages:
        missing_text = ", ".join(unsupported_stages[:20])
        raise PipelinePluginContractError(f"retrieval_text_schema.stages contains unsupported stages: {missing_text}")
    for stage_name, raw_stage in stages.items():
        stage_text = str(stage_name or "").strip() or "<unknown>"
        if not isinstance(raw_stage, dict):
            raise PipelinePluginContractError(f"retrieval_text_schema.stages.{stage_text} must be an object")
        stage = raw_stage
        unknown_stage_keys = _unknown_keys(stage, _SUPPORTED_RETRIEVAL_STAGE_KEYS)
        if unknown_stage_keys:
            raise PipelinePluginContractError(
                f"retrieval_text_schema.stages.{stage_text} contains unknown fields: {', '.join(unknown_stage_keys[:20])}"
            )
        raw_fields = stage.get("fields")
        if not isinstance(raw_fields, list):
            raise PipelinePluginContractError(f"retrieval_text_schema.stages.{stage_text}.fields must be a list")
        referenced: list[str] = []
        for field_index, raw_field in enumerate(raw_fields):
            if not isinstance(raw_field, dict):
                raise PipelinePluginContractError(
                    f"retrieval_text_schema.stages.{stage_text}.fields[{field_index}] must be an object"
                )
            item = raw_field
            unknown_field_keys = _unknown_keys(item, _SUPPORTED_RETRIEVAL_FIELD_KEYS)
            if unknown_field_keys:
                raise PipelinePluginContractError(
                    f"retrieval_text_schema.stages.{stage_text}.fields[{field_index}] contains unknown fields: {', '.join(unknown_field_keys[:20])}"
                )
            raw_content = item.get("content")
            if "content" in item and not isinstance(raw_content, bool):
                raise PipelinePluginContractError(
                    f"retrieval_text_schema.stages.{stage_text}.fields[{field_index}].content must be a boolean"
                )
            raw_field_name = item.get("metadata")
            if raw_field_name is not None and not isinstance(raw_field_name, str):
                raise PipelinePluginContractError(
                    f"retrieval_text_schema.stages.{stage_text}.fields[{field_index}].metadata must be a string"
                )
            field_name = str(raw_field_name or "").strip()
            if not field_name and raw_content is not True:
                raise PipelinePluginContractError(
                    f"retrieval_text_schema.stages.{stage_text}.fields[{field_index}] must set metadata or content=true"
                )
            if field_name and field_name not in referenced:
                referenced.append(field_name)
        missing = [field_name for field_name in referenced if field_name not in declared_fields]
        if missing:
            missing_text = ", ".join(missing[:20])
            raise PipelinePluginContractError(
                f"retrieval_text_schema.stages.{stage_text}.fields references undeclared metadata fields: {missing_text}"
            )


def _declared_metadata_fields(metadata_schema: dict[str, Any] | None) -> dict[str, MetadataField]:
    return {field.name: field for field in parse_metadata_schema(metadata_schema)}


def _policy_string_list(raw: Any, *, key: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise PipelinePluginContractError(f"retrieval_policy.{key} must be a list")
    return _as_string_list(raw, field_label=f"retrieval_policy.{key}")


def _validate_declared_policy_fields(
    field_names: tuple[str, ...],
    *,
    declared_fields: dict[str, MetadataField],
    key: str,
) -> None:
    missing = [field_name for field_name in field_names if field_name not in declared_fields]
    if missing:
        missing_text = ", ".join(missing[:20])
        raise PipelinePluginContractError(
            f"retrieval_policy.{key} references undeclared metadata fields: {missing_text}"
        )


def _validate_policy_chunk_stage_fields(
    field_names: tuple[str, ...],
    *,
    declared_fields: dict[str, MetadataField],
    key: str,
) -> None:
    unavailable = [
        field_name
        for field_name in field_names
        if field_name in declared_fields and not _stage_applies(declared_fields[field_name], "chunk")
    ]
    if unavailable:
        unavailable_text = ", ".join(unavailable[:20])
        raise PipelinePluginContractError(
            f"retrieval_policy.{key} references metadata fields not available at chunk stage: {unavailable_text}"
        )


def _validate_retrieval_policy_query_expansion_values(
    raw_mappings: Any,
    *,
    declared_fields: dict[str, MetadataField],
) -> None:
    if raw_mappings is None:
        return
    if not isinstance(raw_mappings, list):
        raise PipelinePluginContractError("retrieval_policy.query_expansion_values must be a list")
    field_names: list[str] = []
    for index, raw in enumerate(raw_mappings):
        if not isinstance(raw, dict):
            raise PipelinePluginContractError(f"retrieval_policy.query_expansion_values[{index}] must be an object")
        unknown = _unknown_keys(raw, _SUPPORTED_RETRIEVAL_POLICY_QUERY_VALUE_KEYS)
        if unknown:
            raise PipelinePluginContractError(
                f"retrieval_policy.query_expansion_values[{index}] contains unknown fields: {', '.join(unknown[:20])}"
            )
        field_name = str(raw.get("metadata") or "").strip()
        if not field_name:
            raise PipelinePluginContractError(
                f"retrieval_policy.query_expansion_values[{index}].metadata must be non-empty"
            )
        if "value" not in raw and "values" not in raw:
            raise PipelinePluginContractError(
                f"retrieval_policy.query_expansion_values[{index}] must declare value or values"
            )
        if "value" in raw and "values" in raw:
            raise PipelinePluginContractError(
                f"retrieval_policy.query_expansion_values[{index}] must not declare both value and values"
            )
        if "values" in raw:
            _as_string_list(raw.get("values"), field_label=f"retrieval_policy.query_expansion_values[{index}].values")
        elif not isinstance(raw.get("value"), str):
            raise PipelinePluginContractError(
                f"retrieval_policy.query_expansion_values[{index}].value must be a string"
            )
        terms = _as_string_list(raw.get("terms"), field_label=f"retrieval_policy.query_expansion_values[{index}].terms")
        if not terms:
            raise PipelinePluginContractError(
                f"retrieval_policy.query_expansion_values[{index}].terms must declare at least one term"
            )
        field_names.append(field_name)
    _validate_declared_policy_fields(
        tuple(field_names),
        declared_fields=declared_fields,
        key="query_expansion_values",
    )
    _validate_policy_chunk_stage_fields(
        tuple(field_names),
        declared_fields=declared_fields,
        key="query_expansion_values",
    )


def _validate_optional_string(value: Any, *, key: str) -> None:
    if value is not None and not isinstance(value, str):
        raise PipelinePluginContractError(f"retrieval_policy.{key} must be a string")


def _validate_optional_string_list(value: Any, *, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise PipelinePluginContractError(f"retrieval_policy.{key} must be a list")
    return _as_string_list(value, field_label=f"retrieval_policy.{key}")


def _validate_retrieval_policy_response_hints(
    raw_hints: Any,
    *,
    declared_fields: dict[str, MetadataField],
) -> None:
    if raw_hints is None:
        return
    if not isinstance(raw_hints, dict):
        raise PipelinePluginContractError("retrieval_policy.response_hints must be an object")
    unknown = _unknown_keys(raw_hints, _SUPPORTED_RETRIEVAL_POLICY_RESPONSE_HINT_KEYS)
    if unknown:
        raise PipelinePluginContractError(
            f"retrieval_policy.response_hints contains unknown fields: {', '.join(unknown[:20])}"
        )

    for key in ("answer_prefix", "source_prefix"):
        _validate_optional_string(raw_hints.get(key), key=f"response_hints.{key}")
    for key in (
        "structured_labels",
        "answer_labels",
        "answer_keywords",
        "answer_highlight_metadata",
        "existing_hint_prefixes",
        "anchor_only_chunk_kinds",
        "anchor_only_markers",
    ):
        _validate_optional_string_list(raw_hints.get(key), key=f"response_hints.{key}")

    raw_groups = raw_hints.get("groups")
    if raw_groups is not None and not isinstance(raw_groups, list):
        raise PipelinePluginContractError("retrieval_policy.response_hints.groups must be a list")
    for index, raw_group in enumerate(raw_groups or []):
        if not isinstance(raw_group, dict):
            raise PipelinePluginContractError(f"retrieval_policy.response_hints.groups[{index}] must be an object")
        unknown_group = _unknown_keys(raw_group, _SUPPORTED_RETRIEVAL_POLICY_RESPONSE_HINT_GROUP_KEYS)
        if unknown_group:
            raise PipelinePluginContractError(
                "retrieval_policy.response_hints.groups"
                f"[{index}] contains unknown fields: {', '.join(unknown_group[:20])}"
            )
        _validate_optional_string(raw_group.get("name"), key=f"response_hints.groups[{index}].name")
        required = _validate_optional_string_list(
            raw_group.get("required_any_labels"),
            key=f"response_hints.groups[{index}].required_any_labels",
        )
        if not required:
            raise PipelinePluginContractError(
                f"retrieval_policy.response_hints.groups[{index}].required_any_labels must declare at least one label"
            )
        hints = _validate_optional_string_list(
            raw_group.get("hint_labels"),
            key=f"response_hints.groups[{index}].hint_labels",
        )
        if not hints:
            raise PipelinePluginContractError(
                f"retrieval_policy.response_hints.groups[{index}].hint_labels must declare at least one label"
            )
        _validate_optional_string(
            raw_group.get("question_from_query_label"),
            key=f"response_hints.groups[{index}].question_from_query_label",
        )
        _validate_optional_string(raw_group.get("answer_label"), key=f"response_hints.groups[{index}].answer_label")
        query_gate = raw_group.get("query_gate")
        if query_gate is None:
            continue
        if not isinstance(query_gate, dict):
            raise PipelinePluginContractError(
                f"retrieval_policy.response_hints.groups[{index}].query_gate must be an object"
            )
        unknown_gate = _unknown_keys(query_gate, _SUPPORTED_RETRIEVAL_POLICY_RESPONSE_HINT_QUERY_GATE_KEYS)
        if unknown_gate:
            raise PipelinePluginContractError(
                "retrieval_policy.response_hints.groups"
                f"[{index}].query_gate contains unknown fields: {', '.join(unknown_gate[:20])}"
            )
        _validate_optional_string_list(
            query_gate.get("content_labels"),
            key=f"response_hints.groups[{index}].query_gate.content_labels",
        )
        metadata_fields = _validate_optional_string_list(
            query_gate.get("metadata"),
            key=f"response_hints.groups[{index}].query_gate.metadata",
        )
        _validate_declared_policy_fields(metadata_fields, declared_fields=declared_fields, key="response_hints.query_gate")
        _validate_policy_chunk_stage_fields(metadata_fields, declared_fields=declared_fields, key="response_hints.query_gate")
        min_chars = query_gate.get("min_chars")
        if min_chars is not None and (
            not isinstance(min_chars, int) or isinstance(min_chars, bool) or min_chars < 1 or min_chars > 64
        ):
            raise PipelinePluginContractError(
                f"retrieval_policy.response_hints.groups[{index}].query_gate.min_chars is out of range"
            )
        min_common_chars = query_gate.get("min_common_chars")
        if min_common_chars is not None and (
            not isinstance(min_common_chars, int)
            or isinstance(min_common_chars, bool)
            or min_common_chars < 1
            or min_common_chars > 64
        ):
            raise PipelinePluginContractError(
                f"retrieval_policy.response_hints.groups[{index}].query_gate.min_common_chars is out of range"
            )

    enumeration = raw_hints.get("enumeration")
    if enumeration is None:
        return
    if not isinstance(enumeration, dict):
        raise PipelinePluginContractError("retrieval_policy.response_hints.enumeration must be an object")
    unknown_enum = _unknown_keys(enumeration, _SUPPORTED_RETRIEVAL_POLICY_RESPONSE_HINT_ENUMERATION_KEYS)
    if unknown_enum:
        raise PipelinePluginContractError(
            f"retrieval_policy.response_hints.enumeration contains unknown fields: {', '.join(unknown_enum[:20])}"
        )
    enabled = enumeration.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise PipelinePluginContractError("retrieval_policy.response_hints.enumeration.enabled must be a boolean")
    for key in ("intro_terms", "query_terms"):
        _validate_optional_string_list(enumeration.get(key), key=f"response_hints.enumeration.{key}")
    for key in ("prefix", "message_template", "term_separator"):
        _validate_optional_string(enumeration.get(key), key=f"response_hints.enumeration.{key}")
    named_markers = enumeration.get("named_markers")
    if named_markers is not None:
        if not isinstance(named_markers, dict):
            raise PipelinePluginContractError("retrieval_policy.response_hints.enumeration.named_markers must be an object")
        for raw_key, raw_value in named_markers.items():
            key = str(raw_key or "").strip()
            if not key:
                raise PipelinePluginContractError(
                    "retrieval_policy.response_hints.enumeration.named_markers contains an empty key"
                )
            if not isinstance(raw_value, str):
                raise PipelinePluginContractError(
                    f"retrieval_policy.response_hints.enumeration.named_markers.{key} must be a string"
                )
    max_terms = enumeration.get("max_terms")
    if max_terms is not None and (
        not isinstance(max_terms, int) or isinstance(max_terms, bool) or max_terms < 1 or max_terms > 20
    ):
        raise PipelinePluginContractError("retrieval_policy.response_hints.enumeration.max_terms is out of range")


def validate_retrieval_policy_metadata_fields(
    *,
    retrieval_policy: dict[str, Any] | None,
    metadata_schema: dict[str, Any] | None,
) -> None:
    if not isinstance(retrieval_policy, dict) or retrieval_policy.get("schema") != "mimirq.retrieval_policy.v1":
        return
    declared_fields = _declared_metadata_fields(metadata_schema)

    for key in ("query_expansion_fields", "filter_fields", "rerank_features"):
        field_names = _policy_string_list(retrieval_policy.get(key), key=key)
        _validate_declared_policy_fields(field_names, declared_fields=declared_fields, key=key)
        _validate_policy_chunk_stage_fields(field_names, declared_fields=declared_fields, key=key)
        if key == "filter_fields":
            non_filterable = [field_name for field_name in field_names if not declared_fields[field_name].filterable]
            if non_filterable:
                non_filterable_text = ", ".join(non_filterable[:20])
                raise PipelinePluginContractError(
                    f"retrieval_policy.filter_fields references non-filterable metadata fields: {non_filterable_text}"
                )
    _validate_retrieval_policy_query_expansion_values(
        retrieval_policy.get("query_expansion_values"),
        declared_fields=declared_fields,
    )
    _validate_optional_string_list(retrieval_policy.get("question_intent_terms"), key="question_intent_terms")
    question_anchor_bonus = retrieval_policy.get("question_anchor_bonus")
    if question_anchor_bonus is not None and (
        not isinstance(question_anchor_bonus, int | float)
        or isinstance(question_anchor_bonus, bool)
        or question_anchor_bonus < 0
        or question_anchor_bonus > 2
    ):
        raise PipelinePluginContractError("retrieval_policy.question_anchor_bonus is out of range")
    _validate_retrieval_policy_response_hints(
        retrieval_policy.get("response_hints"),
        declared_fields=declared_fields,
    )

    raw_boosts = retrieval_policy.get("boost_fields")
    if raw_boosts is not None and not isinstance(raw_boosts, list):
        raise PipelinePluginContractError("retrieval_policy.boost_fields must be a list")
    for index, raw in enumerate(raw_boosts or []):
        if not isinstance(raw, dict):
            raise PipelinePluginContractError(f"retrieval_policy.boost_fields[{index}] must be an object")
        unknown = _unknown_keys(raw, _SUPPORTED_RETRIEVAL_POLICY_BOOST_KEYS)
        if unknown:
            raise PipelinePluginContractError(
                f"retrieval_policy.boost_fields[{index}] contains unknown fields: {', '.join(unknown[:20])}"
            )
        field_name = str(raw.get("metadata") or "").strip()
        if not field_name:
            raise PipelinePluginContractError(f"retrieval_policy.boost_fields[{index}].metadata must be non-empty")
        _validate_declared_policy_fields((field_name,), declared_fields=declared_fields, key="boost_fields")
        _validate_policy_chunk_stage_fields((field_name,), declared_fields=declared_fields, key="boost_fields")
        weight = raw.get("weight", 1.0)
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0 or weight > 10:
            raise PipelinePluginContractError(f"retrieval_policy.boost_fields[{index}].weight is out of range")
        match_mode = str(raw.get("match") or "contains").strip()
        if match_mode not in _SUPPORTED_RETRIEVAL_POLICY_MATCHES:
            raise PipelinePluginContractError(f"retrieval_policy.boost_fields[{index}].match is unsupported")

    raw_anchors = retrieval_policy.get("anchor_fields")
    if raw_anchors is not None and not isinstance(raw_anchors, list):
        raise PipelinePluginContractError("retrieval_policy.anchor_fields must be a list")
    anchor_field_names: list[str] = []
    for index, raw in enumerate(raw_anchors or []):
        if not isinstance(raw, dict):
            raise PipelinePluginContractError(f"retrieval_policy.anchor_fields[{index}] must be an object")
        unknown = _unknown_keys(raw, _SUPPORTED_RETRIEVAL_POLICY_ANCHOR_KEYS)
        if unknown:
            raise PipelinePluginContractError(
                f"retrieval_policy.anchor_fields[{index}] contains unknown fields: {', '.join(unknown[:20])}"
            )
        field_name = str(raw.get("metadata") or "").strip()
        if not field_name:
            raise PipelinePluginContractError(f"retrieval_policy.anchor_fields[{index}].metadata must be non-empty")
        anchor_field_names.append(field_name)
        weight = raw.get("weight", 1.0)
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0 or weight > 10:
            raise PipelinePluginContractError(f"retrieval_policy.anchor_fields[{index}].weight is out of range")
        aliases = raw.get("aliases")
        if aliases is not None:
            if not isinstance(aliases, dict):
                raise PipelinePluginContractError(f"retrieval_policy.anchor_fields[{index}].aliases must be an object")
            for raw_key, raw_values in aliases.items():
                key = str(raw_key or "").strip()
                if not key:
                    raise PipelinePluginContractError(
                        f"retrieval_policy.anchor_fields[{index}].aliases contains an empty key"
                    )
                if isinstance(raw_values, str):
                    continue
                if not isinstance(raw_values, list):
                    raise PipelinePluginContractError(
                        f"retrieval_policy.anchor_fields[{index}].aliases.{key} must be a string or list"
                    )
                _as_string_list(raw_values, field_label=f"retrieval_policy.anchor_fields[{index}].aliases.{key}")
    _validate_declared_policy_fields(
        tuple(anchor_field_names),
        declared_fields=declared_fields,
        key="anchor_fields",
    )
    _validate_policy_chunk_stage_fields(
        tuple(anchor_field_names),
        declared_fields=declared_fields,
        key="anchor_fields",
    )

    fallback = retrieval_policy.get("fallback")
    if fallback is not None:
        if not isinstance(fallback, dict):
            raise PipelinePluginContractError("retrieval_policy.fallback must be an object")
        unknown_fallback = _unknown_keys(fallback, _SUPPORTED_RETRIEVAL_POLICY_FALLBACK_KEYS)
        if unknown_fallback:
            raise PipelinePluginContractError(
                f"retrieval_policy.fallback contains unknown fields: {', '.join(unknown_fallback[:20])}"
            )
        enabled = fallback.get("enabled")
        if enabled is not None and not isinstance(enabled, bool):
            raise PipelinePluginContractError("retrieval_policy.fallback.enabled must be a boolean")
        multiplier = fallback.get("expand_top_k_multiplier")
        if multiplier is not None and (
            not isinstance(multiplier, int) or isinstance(multiplier, bool) or multiplier < 1 or multiplier > 10
        ):
            raise PipelinePluginContractError("retrieval_policy.fallback.expand_top_k_multiplier is out of range")

    response_compaction = retrieval_policy.get("response_compaction")
    if response_compaction is None:
        return
    if not isinstance(response_compaction, dict):
        raise PipelinePluginContractError("retrieval_policy.response_compaction must be an object")
    unknown_compaction = _unknown_keys(response_compaction, _SUPPORTED_RETRIEVAL_POLICY_RESPONSE_COMPACTION_KEYS)
    if unknown_compaction:
        raise PipelinePluginContractError(
            "retrieval_policy.response_compaction contains unknown fields: "
            f"{', '.join(unknown_compaction[:20])}"
        )
    enabled = response_compaction.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise PipelinePluginContractError("retrieval_policy.response_compaction.enabled must be a boolean")
    min_top_score = response_compaction.get("min_top_score")
    if min_top_score is not None and (
        not isinstance(min_top_score, (int, float))
        or isinstance(min_top_score, bool)
        or min_top_score < 0
        or min_top_score > 2
    ):
        raise PipelinePluginContractError("retrieval_policy.response_compaction.min_top_score is out of range")
    relative_score_floor = response_compaction.get("relative_score_floor")
    if relative_score_floor is not None and (
        not isinstance(relative_score_floor, (int, float))
        or isinstance(relative_score_floor, bool)
        or relative_score_floor < 0
        or relative_score_floor > 1
    ):
        raise PipelinePluginContractError("retrieval_policy.response_compaction.relative_score_floor is out of range")
    min_records = response_compaction.get("min_records")
    if min_records is not None and (
        not isinstance(min_records, int) or isinstance(min_records, bool) or min_records < 1 or min_records > 20
    ):
        raise PipelinePluginContractError("retrieval_policy.response_compaction.min_records is out of range")


def _value_from_metadata(meta: dict[str, Any], key: str) -> Any:
    if "." not in key:
        return meta.get(key)
    cur: Any = meta
    for part in key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _is_present(value: Any) -> bool:
    return value is not None and value != "" and value != []


def _stable_identity_value(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def _record_identity_payload(meta: dict[str, Any], schema: dict[str, Any] | None) -> dict[str, Any] | None:
    identity_fields = _as_string_list((schema or {}).get("record_identity") if isinstance(schema, dict) else None)
    if not identity_fields:
        return None
    values: dict[str, Any] = {}
    for field_name in identity_fields:
        value = _value_from_metadata(meta, field_name)
        if _is_present(value):
            values[field_name] = value
    if not values:
        return None
    key = "|".join(f"{name}={_stable_identity_value(values[name])}" for name in values)
    return {
        "schema": "mimirq.record_identity.v1",
        "key": key[:1000],
        "fields": values,
    }


def build_metadata_schema_views(
    document: Document,
    *,
    metadata_schema: dict[str, Any] | None,
    stage: str,
) -> dict[str, Any]:
    """
    Build generic platform views from a plugin metadata schema.

    The platform only interprets contract flags (`filterable`, `display`,
    `evaluable`, `record_identity`). It does not know any business-specific
    field names; those remain plugin-owned.
    """
    fields = parse_metadata_schema(metadata_schema)
    if not fields:
        return {}

    meta = dict(document.metadata or {})
    indexed: dict[str, Any] = {}
    display: dict[str, Any] = {}
    evaluable: dict[str, Any] = {}
    for field in fields:
        if not _stage_applies(field, stage):
            continue
        value = _value_from_metadata(meta, field.name)
        if not _is_present(value):
            continue
        if field.filterable:
            indexed[field.name] = value
        if field.display:
            display[field.name] = value
        if field.evaluable:
            evaluable[field.name] = value

    views: dict[str, Any] = {}
    if indexed:
        views[INDEXED_METADATA_KEY] = indexed
    if display:
        views[DISPLAY_METADATA_KEY] = display
    if evaluable:
        views[EVALUABLE_METADATA_KEY] = evaluable
    record_identity = _record_identity_payload(meta, metadata_schema)
    if record_identity:
        views[RECORD_IDENTITY_METADATA_KEY] = record_identity
    return views


def apply_metadata_schema_views(
    documents: Iterable[Document],
    *,
    metadata_schema: dict[str, Any] | None,
    stage: str,
) -> list[Document]:
    out: list[Document] = []
    for doc in documents or []:
        meta = dict(doc.metadata or {})
        for key in METADATA_SCHEMA_VIEW_KEYS:
            meta.pop(key, None)
        meta.update(build_metadata_schema_views(doc, metadata_schema=metadata_schema, stage=stage))
        out.append(Document(page_content=doc.page_content or "", metadata=meta, id=getattr(doc, "id", None)))
    return out


def _retrieval_stage_spec(schema: dict[str, Any] | None, stage: str) -> dict[str, Any]:
    if not schema:
        return {}
    if schema.get("schema") != "mimirq.retrieval_text_schema.v1":
        raise PipelinePluginContractError("retrieval_text_schema.schema must be mimirq.retrieval_text_schema.v1")
    stages = schema.get("stages")
    if not isinstance(stages, dict):
        return {}
    normalized = "chunk" if stage == "chunking" else stage
    return _as_dict(stages.get(normalized))


def build_retrieval_text_for_document(
    document: Document,
    *,
    retrieval_text_schema: dict[str, Any] | None,
    stage: str,
) -> str | None:
    spec = _retrieval_stage_spec(retrieval_text_schema, stage)
    raw_fields = spec.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        return None

    meta = dict(document.metadata or {})
    lines: list[str] = []
    for raw in raw_fields:
        item = _as_dict(raw)
        label = str(item.get("label") or "").strip()
        raw_content = item.get("content")
        if "content" in item and not isinstance(raw_content, bool):
            raise PipelinePluginContractError("retrieval_text_schema field content must be a boolean")
        if raw_content is True:
            value = str(document.page_content or "").strip()
        else:
            raw_key = item.get("metadata")
            if raw_key is not None and not isinstance(raw_key, str):
                raise PipelinePluginContractError("retrieval_text_schema field metadata must be a string")
            key = str(raw_key or "").strip()
            if not key:
                raise PipelinePluginContractError("retrieval_text_schema field must set metadata or content=true")
            value_raw = _value_from_metadata(meta, key)
            if isinstance(value_raw, (list, tuple, set)):
                value = "、".join(str(v).strip() for v in value_raw if str(v).strip())
            elif value_raw is None:
                value = ""
            else:
                value = str(value_raw).strip()
        if not value:
            continue
        lines.append(f"{label}：{value}" if label else value)
    return "\n".join(lines).strip() or None


def apply_retrieval_text_schema(
    documents: Iterable[Document],
    *,
    retrieval_text_schema: dict[str, Any] | None,
    stage: str,
) -> list[Document]:
    out: list[Document] = []
    for doc in documents or []:
        meta = dict(doc.metadata or {})
        retrieval_text = build_retrieval_text_for_document(
            doc,
            retrieval_text_schema=retrieval_text_schema,
            stage=stage,
        )
        if retrieval_text:
            meta[RETRIEVAL_DISPLAY_CONTENT_METADATA_KEY] = str(doc.page_content or "")
            meta[RETRIEVAL_TEXT_METADATA_KEY] = retrieval_text
            meta["retrieval_text_schema_applied"] = True
        out.append(Document(page_content=doc.page_content or "", metadata=meta, id=getattr(doc, "id", None)))
    return out


__all__ = [
    "DISPLAY_METADATA_KEY",
    "EVALUABLE_METADATA_KEY",
    "INDEXED_METADATA_KEY",
    "METADATA_SCHEMA_VIEW_KEYS",
    "PipelinePluginContractError",
    "RECORD_IDENTITY_METADATA_KEY",
    "RESERVED_PLATFORM_METADATA_VIEW_KEYS",
    "RETRIEVAL_DISPLAY_CONTENT_METADATA_KEY",
    "RETRIEVAL_TEXT_METADATA_KEY",
    "apply_metadata_schema_views",
    "apply_retrieval_text_schema",
    "build_metadata_schema_views",
    "build_retrieval_text_for_document",
    "parse_metadata_schema",
    "summarize_contracts",
    "strip_reserved_platform_metadata_views",
    "validate_documents_metadata",
    "validate_golden_rules_metadata_fields",
    "validate_kg_events_metadata",
    "validate_no_reserved_platform_metadata_views",
    "validate_retrieval_policy_metadata_fields",
    "validate_retrieval_text_schema_metadata_fields",
]
