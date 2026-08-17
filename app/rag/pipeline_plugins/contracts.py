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
_SUPPORTED_RETRIEVAL_POLICY_ANCHOR_KEYS = {"metadata", "weight", "aliases", "role"}
_SUPPORTED_RETRIEVAL_POLICY_ANCHOR_BINDING_KEYS = {
    "enabled",
    "anchor_fields",
    "anchor_match_bonus",
    "anchor_mismatch_penalty",
    "slot_fields",
    "slot_only_penalty",
    "anchor_slot_match_bonus",
}
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
    "answer_highlight_metadata_fields",
    "existing_hint_prefixes",
    "anchor_only_chunk_kinds",
    "anchor_only_markers",
    "groups",
    "enumeration",
}
_SUPPORTED_RETRIEVAL_POLICY_RESPONSE_HINT_METADATA_FIELD_KEYS = {
    "metadata",
    "key",
    "field",
    "fields",
    "label",
    "labels",
    "max_chars",
    "when_metadata",
    "metadata_when",
    "prioritize_query_fields",
    "requested_labels_prefix",
    "requested_labels_separator",
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
_SUPPORTED_RETRIEVAL_POLICY_FAST_RESPONSE_FIELD_RULE_KEYS = {"label", "markers"}
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


def _validate_known_fields(value: dict[str, Any], supported: set[str], *, field_label: str) -> None:
    unknown = _unknown_keys(value, supported)
    if unknown:
        raise PipelinePluginContractError(f"{field_label} contains unknown fields: {', '.join(unknown[:20])}")


def _validate_metadata_field_name(item: dict[str, Any], index: int) -> str:
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
    return name


def _validate_metadata_field_type(item: dict[str, Any], *, name: str) -> str:
    field_type = str(item.get("type") or "string").strip().lower()
    if field_type not in _SUPPORTED_TYPES:
        raise PipelinePluginContractError(f"metadata field '{name}' has unsupported type '{field_type}'")
    return field_type


def _validate_metadata_field_max_length(item: dict[str, Any], *, name: str) -> int | None:
    max_length = _optional_int(item.get("max_length"), field_label=f"metadata field '{name}'", key="max_length")
    if max_length is not None and (max_length < 1 or max_length > 100_000):
        raise PipelinePluginContractError(f"metadata field '{name}' max_length is out of range")
    return max_length


def _validate_metadata_field_stages(item: dict[str, Any], *, name: str) -> tuple[str, ...]:
    stages = _validate_contract_stage_list(item.get("stages"), field_label=f"metadata field '{name}'")
    if "kg" in stages and not name.startswith(_SUPPORTED_KG_METADATA_FIELD_PREFIXES):
        raise PipelinePluginContractError(
            f"metadata field '{name}' used by kg must start with metadata., references., or extra_data."
        )
    return stages


def _validate_metadata_field_enum(item: dict[str, Any], *, name: str) -> tuple[Any, ...] | None:
    enum_raw = item.get("enum")
    if enum_raw is not None and not isinstance(enum_raw, list):
        raise PipelinePluginContractError(f"metadata field '{name}' enum must be a list")
    return tuple(enum_raw) if enum_raw else None


def _build_metadata_field(
    item: dict[str, Any],
    *,
    name: str,
    field_type: str,
    stages: tuple[str, ...],
) -> MetadataField:
    field_label = f"metadata field '{name}'"
    return MetadataField(
        name=name,
        type=field_type,
        required=_optional_bool(item.get("required"), field_label=field_label, key="required"),
        stages=stages,
        filterable=_optional_bool(item.get("filterable"), field_label=field_label, key="filterable"),
        display=_optional_bool(item.get("display"), field_label=field_label, key="display"),
        evaluable=_optional_bool(item.get("evaluable"), field_label=field_label, key="evaluable"),
        max_length=_validate_metadata_field_max_length(item, name=name),
        enum=_validate_metadata_field_enum(item, name=name),
    )


def _parse_metadata_field(raw: Any, *, index: int, seen: set[str]) -> MetadataField:
    if not isinstance(raw, dict):
        raise PipelinePluginContractError(f"metadata field at index {index} must be an object")
    item = raw
    name = _validate_metadata_field_name(item, index)
    _validate_known_fields(item, _SUPPORTED_METADATA_FIELD_KEYS, field_label=f"metadata field '{name}'")
    if name in seen:
        raise PipelinePluginContractError(f"metadata field '{name}' is duplicated")
    seen.add(name)
    field_type = _validate_metadata_field_type(item, name=name)
    stages = _validate_metadata_field_stages(item, name=name)
    return _build_metadata_field(item, name=name, field_type=field_type, stages=stages)


def _validate_record_identity_fields(schema: dict[str, Any], *, declared_fields: set[str]) -> None:
    raw_identity_fields = schema.get("record_identity")
    if raw_identity_fields is not None and not isinstance(raw_identity_fields, list):
        raise PipelinePluginContractError("metadata_schema.record_identity must be a list")
    identity_fields = _as_string_list(raw_identity_fields, field_label="metadata_schema.record_identity")
    missing_identity_fields = [field_name for field_name in identity_fields if field_name not in declared_fields]
    if missing_identity_fields:
        missing_text = ", ".join(missing_identity_fields[:20])
        raise PipelinePluginContractError(
            f"metadata_schema.record_identity references undeclared metadata fields: {missing_text}"
        )


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
        fields.append(_parse_metadata_field(raw, index=index, seen=seen))
    _validate_record_identity_fields(schema, declared_fields=seen)
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
            raise PipelinePluginContractError(
                f"{field_label} must not contain reserved platform metadata field '{key}'"
            )


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


def _empty_retrieval_policy_summary() -> dict[str, Any]:
    return {
        "schema": None,
        "query_expansion_fields": [],
        "query_expansion_value_fields": [],
        "filter_fields": [],
        "boost_fields": [],
        "anchor_fields": [],
        "anchor_binding_fields": [],
        "anchor_binding_enabled": False,
        "rerank_features": [],
        "question_intent_terms": [],
        "mixed_intent_leading_noise_terms": [],
        "mixed_intent_subject_terms": [],
        "service_anchor_noise_terms": [],
        "service_anchor_priority_terms": [],
        "service_anchor_entity_terms": [],
        "service_anchor_leading_noise_terms": [],
        "service_anchor_cutoff_terms": [],
        "question_anchor_generic_subject_terms": [],
        "fast_response_always_labels": [],
        "fast_response_field_rules": 0,
        "service_anchor_query_rewrites": 0,
        "fallback_enabled": False,
        "response_compaction_enabled": False,
        "response_hints_enabled": False,
    }


def _list_length(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _policy_metadata_field_names(raw_values: Any) -> list[str]:
    field_names: list[str] = []
    for raw in raw_values if isinstance(raw_values, list) else ():
        if not isinstance(raw, dict):
            continue
        field_name = str(raw.get("metadata") or "").strip()
        if field_name and field_name not in field_names:
            field_names.append(field_name)
    return field_names


def _summarize_retrieval_policy(retrieval_policy: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(retrieval_policy, dict):
        return _empty_retrieval_policy_summary()
    anchor_binding = _as_dict(retrieval_policy.get("anchor_binding"))
    fallback = _as_dict(retrieval_policy.get("fallback"))
    response_compaction = _as_dict(retrieval_policy.get("response_compaction"))
    return {
        "schema": retrieval_policy.get("schema"),
        "query_expansion_fields": list(_as_string_list(retrieval_policy.get("query_expansion_fields"))),
        "query_expansion_value_fields": _policy_metadata_field_names(retrieval_policy.get("query_expansion_values")),
        "question_intent_terms": list(_as_string_list(retrieval_policy.get("question_intent_terms"))),
        "mixed_intent_leading_noise_terms": list(
            _as_string_list(retrieval_policy.get("mixed_intent_leading_noise_terms"))
        ),
        "mixed_intent_subject_terms": list(_as_string_list(retrieval_policy.get("mixed_intent_subject_terms"))),
        "service_anchor_noise_terms": list(_as_string_list(retrieval_policy.get("service_anchor_noise_terms"))),
        "service_anchor_priority_terms": list(_as_string_list(retrieval_policy.get("service_anchor_priority_terms"))),
        "service_anchor_entity_terms": list(_as_string_list(retrieval_policy.get("service_anchor_entity_terms"))),
        "service_anchor_leading_noise_terms": list(
            _as_string_list(retrieval_policy.get("service_anchor_leading_noise_terms"))
        ),
        "service_anchor_cutoff_terms": list(_as_string_list(retrieval_policy.get("service_anchor_cutoff_terms"))),
        "question_anchor_generic_subject_terms": list(
            _as_string_list(retrieval_policy.get("question_anchor_generic_subject_terms"))
        ),
        "fast_response_always_labels": list(_as_string_list(retrieval_policy.get("fast_response_always_labels"))),
        "fast_response_field_rules": _list_length(retrieval_policy.get("fast_response_field_rules")),
        "metadata_anchor_preflight_block_terms": list(
            _as_string_list(retrieval_policy.get("metadata_anchor_preflight_block_terms"))
        ),
        "service_anchor_query_rewrites": _list_length(retrieval_policy.get("service_anchor_query_rewrites")),
        "filter_fields": list(_as_string_list(retrieval_policy.get("filter_fields"))),
        "boost_fields": _policy_metadata_field_names(retrieval_policy.get("boost_fields")),
        "anchor_fields": _policy_metadata_field_names(retrieval_policy.get("anchor_fields")),
        "anchor_binding_fields": list(_as_string_list(anchor_binding.get("anchor_fields"))),
        "anchor_binding_enabled": anchor_binding.get("enabled") is True,
        "rerank_features": list(_as_string_list(retrieval_policy.get("rerank_features"))),
        "fallback_enabled": fallback.get("enabled") is True,
        "response_compaction_enabled": response_compaction.get("enabled") is True,
        "response_hints_enabled": isinstance(retrieval_policy.get("response_hints"), dict),
    }


def _validate_golden_rule_fields(
    raw_rule_fields: Any,
    *,
    rule_key: str,
    declared_fields: set[str],
    evaluable_fields: set[str],
) -> None:
    if raw_rule_fields is not None and not isinstance(raw_rule_fields, list):
        raise PipelinePluginContractError(f"golden_rules.{rule_key} must be a list")
    rule_fields = _as_string_list(raw_rule_fields, field_label=f"golden_rules.{rule_key}")
    missing = [field_name for field_name in rule_fields if field_name not in declared_fields]
    if missing:
        missing_text = ", ".join(missing[:20])
        raise PipelinePluginContractError(
            f"golden_rules.{rule_key} references undeclared metadata fields: {missing_text}"
        )
    if rule_key == "expected_metadata" and not rule_fields:
        raise PipelinePluginContractError("golden_rules.expected_metadata must declare at least one field")
    if rule_key not in {"expected_metadata", "answer_key_point_fields"}:
        return
    non_evaluable = [field_name for field_name in rule_fields if field_name not in evaluable_fields]
    if non_evaluable:
        non_evaluable_text = ", ".join(non_evaluable[:20])
        raise PipelinePluginContractError(
            f"golden_rules.{rule_key} references non-evaluable metadata fields: {non_evaluable_text}"
        )


def _validate_golden_rule_query_templates(raw_templates: Any) -> None:
    if raw_templates is None:
        return
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
        _validate_golden_rule_fields(
            golden_rules.get(rule_key),
            rule_key=rule_key,
            declared_fields=declared_fields,
            evaluable_fields=evaluable_fields,
        )
    _validate_golden_rule_query_templates(golden_rules.get("query_templates"))


def _validated_retrieval_text_stages(raw_stages: Any) -> dict[str, Any]:
    if not isinstance(raw_stages, dict):
        raise PipelinePluginContractError("retrieval_text_schema.stages must be an object")
    unsupported_stages = [
        str(stage_name or "").strip() or "<empty>"
        for stage_name in raw_stages
        if str(stage_name or "").strip() not in _SUPPORTED_RETRIEVAL_TEXT_STAGES
    ]
    if unsupported_stages:
        missing_text = ", ".join(unsupported_stages[:20])
        raise PipelinePluginContractError(f"retrieval_text_schema.stages contains unsupported stages: {missing_text}")
    return raw_stages


def _validate_retrieval_text_stage_field(raw_field: Any, *, stage_text: str, field_index: int) -> str:
    if not isinstance(raw_field, dict):
        raise PipelinePluginContractError(
            f"retrieval_text_schema.stages.{stage_text}.fields[{field_index}] must be an object"
        )
    item = raw_field
    _validate_known_fields(
        item,
        _SUPPORTED_RETRIEVAL_FIELD_KEYS,
        field_label=f"retrieval_text_schema.stages.{stage_text}.fields[{field_index}]",
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
    return field_name


def _validate_retrieval_text_stage(raw_stage: Any, *, stage_text: str, declared_fields: set[str]) -> None:
    if not isinstance(raw_stage, dict):
        raise PipelinePluginContractError(f"retrieval_text_schema.stages.{stage_text} must be an object")
    stage = raw_stage
    _validate_known_fields(
        stage,
        _SUPPORTED_RETRIEVAL_STAGE_KEYS,
        field_label=f"retrieval_text_schema.stages.{stage_text}",
    )
    raw_fields = stage.get("fields")
    if not isinstance(raw_fields, list):
        raise PipelinePluginContractError(f"retrieval_text_schema.stages.{stage_text}.fields must be a list")
    referenced: list[str] = []
    for field_index, raw_field in enumerate(raw_fields):
        field_name = _validate_retrieval_text_stage_field(raw_field, stage_text=stage_text, field_index=field_index)
        if field_name and field_name not in referenced:
            referenced.append(field_name)
    missing = [field_name for field_name in referenced if field_name not in declared_fields]
    if missing:
        missing_text = ", ".join(missing[:20])
        raise PipelinePluginContractError(
            f"retrieval_text_schema.stages.{stage_text}.fields references undeclared metadata fields: {missing_text}"
        )


def validate_retrieval_text_schema_metadata_fields(
    *,
    retrieval_text_schema: dict[str, Any] | None,
    metadata_schema: dict[str, Any] | None,
) -> None:
    if not isinstance(retrieval_text_schema, dict) or (
        retrieval_text_schema.get("schema") != "mimirq.retrieval_text_schema.v1"
    ):
        return
    declared_fields = {field.name for field in parse_metadata_schema(metadata_schema)}
    stages = _validated_retrieval_text_stages(retrieval_text_schema.get("stages"))
    for stage_name, raw_stage in stages.items():
        stage_text = str(stage_name or "").strip() or "<unknown>"
        _validate_retrieval_text_stage(raw_stage, stage_text=stage_text, declared_fields=declared_fields)


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
    field_names = [_validate_query_expansion_value_mapping(raw, index=index) for index, raw in enumerate(raw_mappings)]
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


def _validate_query_expansion_value_mapping(raw: Any, *, index: int) -> str:
    if not isinstance(raw, dict):
        raise PipelinePluginContractError(f"retrieval_policy.query_expansion_values[{index}] must be an object")
    _validate_known_fields(
        raw,
        _SUPPORTED_RETRIEVAL_POLICY_QUERY_VALUE_KEYS,
        field_label=f"retrieval_policy.query_expansion_values[{index}]",
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
        raise PipelinePluginContractError(f"retrieval_policy.query_expansion_values[{index}].value must be a string")
    terms = _as_string_list(raw.get("terms"), field_label=f"retrieval_policy.query_expansion_values[{index}].terms")
    if not terms:
        raise PipelinePluginContractError(
            f"retrieval_policy.query_expansion_values[{index}].terms must declare at least one term"
        )
    return field_name


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
    _validate_known_fields(
        raw_hints,
        _SUPPORTED_RETRIEVAL_POLICY_RESPONSE_HINT_KEYS,
        field_label="retrieval_policy.response_hints",
    )
    _validate_response_hint_scalar_fields(raw_hints)
    _validate_response_hint_highlight_fields(
        raw_hints.get("answer_highlight_metadata_fields"),
        declared_fields=declared_fields,
    )
    _validate_response_hint_groups(raw_hints.get("groups"), declared_fields=declared_fields)
    _validate_response_hint_enumeration(raw_hints.get("enumeration"))


def _validate_response_hint_scalar_fields(raw_hints: dict[str, Any]) -> None:
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


def _validate_response_hint_highlight_fields(
    raw_highlight_fields: Any,
    *,
    declared_fields: dict[str, MetadataField],
) -> None:
    if raw_highlight_fields is not None and not isinstance(raw_highlight_fields, list):
        raise PipelinePluginContractError(
            "retrieval_policy.response_hints.answer_highlight_metadata_fields must be a list"
        )
    for index, raw_field in enumerate(raw_highlight_fields or []):
        _validate_response_hint_highlight_field(raw_field, index=index, declared_fields=declared_fields)


def _validate_response_hint_highlight_field(
    raw_field: Any,
    *,
    index: int,
    declared_fields: dict[str, MetadataField],
) -> None:
    if not isinstance(raw_field, dict):
        raise PipelinePluginContractError(
            f"retrieval_policy.response_hints.answer_highlight_metadata_fields[{index}] must be an object"
        )
    _validate_known_fields(
        raw_field,
        _SUPPORTED_RETRIEVAL_POLICY_RESPONSE_HINT_METADATA_FIELD_KEYS,
        field_label=f"retrieval_policy.response_hints.answer_highlight_metadata_fields[{index}]",
    )
    metadata_field = str(raw_field.get("metadata") or raw_field.get("key") or "").strip()
    if not metadata_field:
        raise PipelinePluginContractError(
            f"retrieval_policy.response_hints.answer_highlight_metadata_fields[{index}].metadata must be non-empty"
        )
    _validate_declared_policy_fields(
        (metadata_field,),
        declared_fields=declared_fields,
        key="response_hints.answer_highlight_metadata_fields",
    )
    _validate_policy_chunk_stage_fields(
        (metadata_field,),
        declared_fields=declared_fields,
        key="response_hints.answer_highlight_metadata_fields",
    )
    _validate_response_hint_highlight_field_options(raw_field, index=index)
    _validate_response_hint_highlight_field_conditions(raw_field, index=index, declared_fields=declared_fields)


def _validate_response_hint_highlight_field_options(raw_field: dict[str, Any], *, index: int) -> None:
    for key in ("field", "label", "requested_labels_prefix", "requested_labels_separator"):
        _validate_optional_string(
            raw_field.get(key),
            key=f"response_hints.answer_highlight_metadata_fields[{index}].{key}",
        )
    prioritize_query_fields = raw_field.get("prioritize_query_fields")
    if prioritize_query_fields is not None and not isinstance(prioritize_query_fields, bool):
        raise PipelinePluginContractError(
            "retrieval_policy.response_hints.answer_highlight_metadata_fields"
            f"[{index}].prioritize_query_fields must be a boolean"
        )
    _validate_optional_string_list(
        raw_field.get("fields"),
        key=f"response_hints.answer_highlight_metadata_fields[{index}].fields",
    )
    _validate_response_hint_highlight_labels(raw_field.get("labels"), index=index)
    max_chars = raw_field.get("max_chars")
    if max_chars is not None and (
        not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < 1 or max_chars > 3000
    ):
        raise PipelinePluginContractError(
            f"retrieval_policy.response_hints.answer_highlight_metadata_fields[{index}].max_chars is out of range"
        )


def _validate_response_hint_highlight_labels(labels: Any, *, index: int) -> None:
    if labels is None:
        return
    if not isinstance(labels, dict):
        raise PipelinePluginContractError(
            f"retrieval_policy.response_hints.answer_highlight_metadata_fields[{index}].labels must be an object"
        )
    for label_key, label_value in labels.items():
        if not str(label_key or "").strip() or not isinstance(label_value, str) or not label_value.strip():
            raise PipelinePluginContractError(
                "retrieval_policy.response_hints.answer_highlight_metadata_fields"
                f"[{index}].labels must map non-empty field names to non-empty strings"
            )


def _validate_response_hint_highlight_field_conditions(
    raw_field: dict[str, Any],
    *,
    index: int,
    declared_fields: dict[str, MetadataField],
) -> None:
    for condition_key in ("when_metadata", "metadata_when"):
        raw_conditions = raw_field.get(condition_key)
        if raw_conditions is None:
            continue
        if not isinstance(raw_conditions, dict):
            raise PipelinePluginContractError(
                "retrieval_policy.response_hints.answer_highlight_metadata_fields"
                f"[{index}].{condition_key} must be an object"
            )
        condition_fields = tuple(str(field_name or "").strip() for field_name in raw_conditions)
        if not all(condition_fields):
            raise PipelinePluginContractError(
                "retrieval_policy.response_hints.answer_highlight_metadata_fields"
                f"[{index}].{condition_key} contains an empty metadata field"
            )
        _validate_declared_policy_fields(
            condition_fields,
            declared_fields=declared_fields,
            key=f"response_hints.answer_highlight_metadata_fields.{condition_key}",
        )
        _validate_policy_chunk_stage_fields(
            condition_fields,
            declared_fields=declared_fields,
            key=f"response_hints.answer_highlight_metadata_fields.{condition_key}",
        )


def _validate_response_hint_groups(
    raw_groups: Any,
    *,
    declared_fields: dict[str, MetadataField],
) -> None:
    if raw_groups is not None and not isinstance(raw_groups, list):
        raise PipelinePluginContractError("retrieval_policy.response_hints.groups must be a list")
    for index, raw_group in enumerate(raw_groups or []):
        _validate_response_hint_group(raw_group, index=index, declared_fields=declared_fields)


def _validate_response_hint_group(
    raw_group: Any,
    *,
    index: int,
    declared_fields: dict[str, MetadataField],
) -> None:
    if not isinstance(raw_group, dict):
        raise PipelinePluginContractError(f"retrieval_policy.response_hints.groups[{index}] must be an object")
    _validate_known_fields(
        raw_group,
        _SUPPORTED_RETRIEVAL_POLICY_RESPONSE_HINT_GROUP_KEYS,
        field_label=f"retrieval_policy.response_hints.groups[{index}]",
    )
    _validate_optional_string(raw_group.get("name"), key=f"response_hints.groups[{index}].name")
    for key in ("required_any_labels", "hint_labels"):
        labels = _validate_optional_string_list(raw_group.get(key), key=f"response_hints.groups[{index}].{key}")
        if not labels:
            raise PipelinePluginContractError(
                f"retrieval_policy.response_hints.groups[{index}].{key} must declare at least one label"
            )
    _validate_optional_string(
        raw_group.get("question_from_query_label"),
        key=f"response_hints.groups[{index}].question_from_query_label",
    )
    _validate_optional_string(raw_group.get("answer_label"), key=f"response_hints.groups[{index}].answer_label")
    _validate_response_hint_query_gate(raw_group.get("query_gate"), index=index, declared_fields=declared_fields)


def _validate_response_hint_query_gate(
    query_gate: Any,
    *,
    index: int,
    declared_fields: dict[str, MetadataField],
) -> None:
    if query_gate is None:
        return
    if not isinstance(query_gate, dict):
        raise PipelinePluginContractError(
            f"retrieval_policy.response_hints.groups[{index}].query_gate must be an object"
        )
    _validate_known_fields(
        query_gate,
        _SUPPORTED_RETRIEVAL_POLICY_RESPONSE_HINT_QUERY_GATE_KEYS,
        field_label=f"retrieval_policy.response_hints.groups[{index}].query_gate",
    )
    _validate_optional_string_list(
        query_gate.get("content_labels"),
        key=f"response_hints.groups[{index}].query_gate.content_labels",
    )
    metadata_fields = _validate_optional_string_list(
        query_gate.get("metadata"),
        key=f"response_hints.groups[{index}].query_gate.metadata",
    )
    _validate_declared_policy_fields(
        metadata_fields,
        declared_fields=declared_fields,
        key="response_hints.query_gate",
    )
    _validate_policy_chunk_stage_fields(
        metadata_fields,
        declared_fields=declared_fields,
        key="response_hints.query_gate",
    )
    for key, upper_bound in (("min_chars", 64), ("min_common_chars", 64)):
        value = query_gate.get(key)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > upper_bound
        ):
            raise PipelinePluginContractError(
                f"retrieval_policy.response_hints.groups[{index}].query_gate.{key} is out of range"
            )


def _validate_response_hint_enumeration(enumeration: Any) -> None:
    if enumeration is None:
        return
    if not isinstance(enumeration, dict):
        raise PipelinePluginContractError("retrieval_policy.response_hints.enumeration must be an object")
    _validate_known_fields(
        enumeration,
        _SUPPORTED_RETRIEVAL_POLICY_RESPONSE_HINT_ENUMERATION_KEYS,
        field_label="retrieval_policy.response_hints.enumeration",
    )
    enabled = enumeration.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise PipelinePluginContractError("retrieval_policy.response_hints.enumeration.enabled must be a boolean")
    for key in ("intro_terms", "query_terms"):
        _validate_optional_string_list(enumeration.get(key), key=f"response_hints.enumeration.{key}")
    for key in ("prefix", "message_template", "term_separator"):
        _validate_optional_string(enumeration.get(key), key=f"response_hints.enumeration.{key}")
    _validate_response_hint_named_markers(enumeration.get("named_markers"))
    max_terms = enumeration.get("max_terms")
    if max_terms is not None and (
        not isinstance(max_terms, int) or isinstance(max_terms, bool) or max_terms < 1 or max_terms > 20
    ):
        raise PipelinePluginContractError("retrieval_policy.response_hints.enumeration.max_terms is out of range")


def _validate_response_hint_named_markers(named_markers: Any) -> None:
    if named_markers is None:
        return
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


def _validate_retrieval_policy_service_anchor_query_rewrites(raw_rules: Any) -> None:
    if raw_rules is None:
        return
    if not isinstance(raw_rules, list):
        raise PipelinePluginContractError("retrieval_policy.service_anchor_query_rewrites must be a list")
    for index, raw in enumerate(raw_rules):
        if not isinstance(raw, dict):
            raise PipelinePluginContractError(
                f"retrieval_policy.service_anchor_query_rewrites[{index}] must be an object"
            )
        _validate_optional_string_list(
            raw.get("when_terms") if "when_terms" in raw else raw.get("when"),
            key=f"service_anchor_query_rewrites[{index}].when_terms",
        )
        _validate_optional_string_list(
            raw.get("terms") if "terms" in raw else raw.get("rewrite_terms"),
            key=f"service_anchor_query_rewrites[{index}].terms",
        )
        match = raw.get("match")
        if match is not None and str(match or "").strip().lower() not in {"all", "any"}:
            raise PipelinePluginContractError(
                f"retrieval_policy.service_anchor_query_rewrites[{index}].match must be all or any"
            )


def _validate_retrieval_policy_fast_response_field_rules(raw_rules: Any) -> None:
    if raw_rules is None:
        return
    if not isinstance(raw_rules, list):
        raise PipelinePluginContractError("retrieval_policy.fast_response_field_rules must be a list")
    for index, raw_rule in enumerate(raw_rules):
        if not isinstance(raw_rule, dict):
            raise PipelinePluginContractError(f"retrieval_policy.fast_response_field_rules[{index}] must be an object")
        unknown = _unknown_keys(raw_rule, _SUPPORTED_RETRIEVAL_POLICY_FAST_RESPONSE_FIELD_RULE_KEYS)
        if unknown:
            raise PipelinePluginContractError(
                f"retrieval_policy.fast_response_field_rules[{index}] contains unknown fields: "
                f"{', '.join(unknown[:20])}"
            )
        _validate_optional_string(raw_rule.get("label"), key=f"fast_response_field_rules[{index}].label")
        if not str(raw_rule.get("label") or "").strip():
            raise PipelinePluginContractError(
                f"retrieval_policy.fast_response_field_rules[{index}].label must be non-empty"
            )
        markers = _validate_optional_string_list(
            raw_rule.get("markers"),
            key=f"fast_response_field_rules[{index}].markers",
        )
        if not markers:
            raise PipelinePluginContractError(
                f"retrieval_policy.fast_response_field_rules[{index}].markers must declare at least one marker"
            )


def _validate_retrieval_policy_anchor_binding(
    raw_binding: Any,
    *,
    declared_fields: dict[str, MetadataField],
) -> None:
    if raw_binding is None:
        return
    if not isinstance(raw_binding, dict):
        raise PipelinePluginContractError("retrieval_policy.anchor_binding must be an object")
    unknown = _unknown_keys(raw_binding, _SUPPORTED_RETRIEVAL_POLICY_ANCHOR_BINDING_KEYS)
    if unknown:
        raise PipelinePluginContractError(
            f"retrieval_policy.anchor_binding contains unknown fields: {', '.join(unknown[:20])}"
        )
    enabled = raw_binding.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise PipelinePluginContractError("retrieval_policy.anchor_binding.enabled must be a boolean")
    anchor_fields = _validate_optional_string_list(raw_binding.get("anchor_fields"), key="anchor_binding.anchor_fields")
    slot_fields = _validate_optional_string_list(raw_binding.get("slot_fields"), key="anchor_binding.slot_fields")
    for key in ("anchor_match_bonus", "anchor_mismatch_penalty", "slot_only_penalty", "anchor_slot_match_bonus"):
        value = raw_binding.get(key)
        if value is None:
            continue
        if not isinstance(value, int | float) or isinstance(value, bool) or value < 0 or value > 2:
            raise PipelinePluginContractError(f"retrieval_policy.anchor_binding.{key} is out of range")
    referenced_fields = (*anchor_fields, *slot_fields)
    _validate_declared_policy_fields(
        referenced_fields,
        declared_fields=declared_fields,
        key="anchor_binding",
    )
    _validate_policy_chunk_stage_fields(
        referenced_fields,
        declared_fields=declared_fields,
        key="anchor_binding",
    )


def _validate_policy_metadata_field_list(
    retrieval_policy: dict[str, Any],
    *,
    declared_fields: dict[str, MetadataField],
    key: str,
) -> None:
    field_names = _policy_string_list(retrieval_policy.get(key), key=key)
    _validate_declared_policy_fields(field_names, declared_fields=declared_fields, key=key)
    _validate_policy_chunk_stage_fields(field_names, declared_fields=declared_fields, key=key)
    if key != "filter_fields":
        return
    non_filterable = [field_name for field_name in field_names if not declared_fields[field_name].filterable]
    if non_filterable:
        non_filterable_text = ", ".join(non_filterable[:20])
        raise PipelinePluginContractError(
            f"retrieval_policy.filter_fields references non-filterable metadata fields: {non_filterable_text}"
        )


def _validate_policy_string_list_sections(retrieval_policy: dict[str, Any]) -> None:
    for key in (
        "question_intent_terms",
        "mixed_intent_leading_noise_terms",
        "mixed_intent_subject_terms",
        "service_anchor_noise_terms",
        "service_anchor_priority_terms",
        "service_anchor_entity_terms",
        "service_anchor_leading_noise_terms",
        "service_anchor_cutoff_terms",
        "question_anchor_generic_subject_terms",
        "fast_response_always_labels",
        "metadata_anchor_preflight_block_terms",
    ):
        _validate_optional_string_list(retrieval_policy.get(key), key=key)


def _validate_policy_question_anchor_bonus(retrieval_policy: dict[str, Any]) -> None:
    question_anchor_bonus = retrieval_policy.get("question_anchor_bonus")
    if question_anchor_bonus is not None and (
        not isinstance(question_anchor_bonus, int | float)
        or isinstance(question_anchor_bonus, bool)
        or question_anchor_bonus < 0
        or question_anchor_bonus > 2
    ):
        raise PipelinePluginContractError("retrieval_policy.question_anchor_bonus is out of range")


def _validate_policy_boost_fields(
    raw_boosts: Any,
    *,
    declared_fields: dict[str, MetadataField],
) -> None:
    if raw_boosts is not None and not isinstance(raw_boosts, list):
        raise PipelinePluginContractError("retrieval_policy.boost_fields must be a list")
    for index, raw in enumerate(raw_boosts or []):
        _validate_policy_boost_field(raw, index=index, declared_fields=declared_fields)


def _validate_policy_boost_field(raw: Any, *, index: int, declared_fields: dict[str, MetadataField]) -> None:
    if not isinstance(raw, dict):
        raise PipelinePluginContractError(f"retrieval_policy.boost_fields[{index}] must be an object")
    _validate_known_fields(
        raw,
        _SUPPORTED_RETRIEVAL_POLICY_BOOST_KEYS,
        field_label=f"retrieval_policy.boost_fields[{index}]",
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


def _validate_policy_anchor_fields(
    raw_anchors: Any,
    *,
    declared_fields: dict[str, MetadataField],
) -> None:
    if raw_anchors is not None and not isinstance(raw_anchors, list):
        raise PipelinePluginContractError("retrieval_policy.anchor_fields must be a list")
    anchor_field_names = [
        _validate_policy_anchor_field(raw, index=index, declared_fields=declared_fields)
        for index, raw in enumerate(raw_anchors or [])
    ]
    _validate_declared_policy_fields(tuple(anchor_field_names), declared_fields=declared_fields, key="anchor_fields")
    _validate_policy_chunk_stage_fields(tuple(anchor_field_names), declared_fields=declared_fields, key="anchor_fields")


def _validate_policy_anchor_field(raw: Any, *, index: int, declared_fields: dict[str, MetadataField]) -> str:
    if not isinstance(raw, dict):
        raise PipelinePluginContractError(f"retrieval_policy.anchor_fields[{index}] must be an object")
    _validate_known_fields(
        raw,
        _SUPPORTED_RETRIEVAL_POLICY_ANCHOR_KEYS,
        field_label=f"retrieval_policy.anchor_fields[{index}]",
    )
    field_name = str(raw.get("metadata") or "").strip()
    if not field_name:
        raise PipelinePluginContractError(f"retrieval_policy.anchor_fields[{index}].metadata must be non-empty")
    role = str(raw.get("role") or "").strip()
    if role and role != "administrative_area":
        raise PipelinePluginContractError(f"retrieval_policy.anchor_fields[{index}].role is unsupported")
    weight = raw.get("weight", 1.0)
    if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0 or weight > 10:
        raise PipelinePluginContractError(f"retrieval_policy.anchor_fields[{index}].weight is out of range")
    _validate_policy_anchor_aliases(raw.get("aliases"), index=index)
    return field_name


def _validate_policy_anchor_aliases(aliases: Any, *, index: int) -> None:
    if aliases is None:
        return
    if not isinstance(aliases, dict):
        raise PipelinePluginContractError(f"retrieval_policy.anchor_fields[{index}].aliases must be an object")
    for raw_key, raw_values in aliases.items():
        key = str(raw_key or "").strip()
        if not key:
            raise PipelinePluginContractError(f"retrieval_policy.anchor_fields[{index}].aliases contains an empty key")
        if isinstance(raw_values, str):
            continue
        if not isinstance(raw_values, list):
            raise PipelinePluginContractError(
                f"retrieval_policy.anchor_fields[{index}].aliases.{key} must be a string or list"
            )
        _as_string_list(raw_values, field_label=f"retrieval_policy.anchor_fields[{index}].aliases.{key}")


def _validate_policy_fallback(fallback: Any) -> None:
    if fallback is None:
        return
    if not isinstance(fallback, dict):
        raise PipelinePluginContractError("retrieval_policy.fallback must be an object")
    _validate_known_fields(fallback, _SUPPORTED_RETRIEVAL_POLICY_FALLBACK_KEYS, field_label="retrieval_policy.fallback")
    enabled = fallback.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise PipelinePluginContractError("retrieval_policy.fallback.enabled must be a boolean")
    multiplier = fallback.get("expand_top_k_multiplier")
    if multiplier is not None and (
        not isinstance(multiplier, int) or isinstance(multiplier, bool) or multiplier < 1 or multiplier > 10
    ):
        raise PipelinePluginContractError("retrieval_policy.fallback.expand_top_k_multiplier is out of range")


def _validate_policy_response_compaction(response_compaction: Any) -> None:
    if response_compaction is None:
        return
    if not isinstance(response_compaction, dict):
        raise PipelinePluginContractError("retrieval_policy.response_compaction must be an object")
    _validate_known_fields(
        response_compaction,
        _SUPPORTED_RETRIEVAL_POLICY_RESPONSE_COMPACTION_KEYS,
        field_label="retrieval_policy.response_compaction",
    )
    enabled = response_compaction.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise PipelinePluginContractError("retrieval_policy.response_compaction.enabled must be a boolean")
    _validate_response_compaction_number(response_compaction.get("min_top_score"), key="min_top_score", upper_bound=2)
    _validate_response_compaction_number(
        response_compaction.get("relative_score_floor"),
        key="relative_score_floor",
        upper_bound=1,
    )
    min_records = response_compaction.get("min_records")
    if min_records is not None and (
        not isinstance(min_records, int) or isinstance(min_records, bool) or min_records < 1 or min_records > 20
    ):
        raise PipelinePluginContractError("retrieval_policy.response_compaction.min_records is out of range")


def _validate_response_compaction_number(value: Any, *, key: str, upper_bound: int) -> None:
    if value is not None and (
        not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0 or value > upper_bound
    ):
        raise PipelinePluginContractError(f"retrieval_policy.response_compaction.{key} is out of range")


def validate_retrieval_policy_metadata_fields(
    *,
    retrieval_policy: dict[str, Any] | None,
    metadata_schema: dict[str, Any] | None,
) -> None:
    if not isinstance(retrieval_policy, dict) or retrieval_policy.get("schema") != "mimirq.retrieval_policy.v1":
        return
    declared_fields = _declared_metadata_fields(metadata_schema)

    for key in ("query_expansion_fields", "filter_fields", "rerank_features"):
        _validate_policy_metadata_field_list(retrieval_policy, declared_fields=declared_fields, key=key)
    _validate_retrieval_policy_query_expansion_values(
        retrieval_policy.get("query_expansion_values"),
        declared_fields=declared_fields,
    )
    _validate_policy_string_list_sections(retrieval_policy)
    _validate_retrieval_policy_fast_response_field_rules(
        retrieval_policy.get("fast_response_field_rules"),
    )
    _validate_retrieval_policy_service_anchor_query_rewrites(
        retrieval_policy.get("service_anchor_query_rewrites"),
    )
    _validate_policy_question_anchor_bonus(retrieval_policy)
    _validate_retrieval_policy_response_hints(
        retrieval_policy.get("response_hints"),
        declared_fields=declared_fields,
    )
    _validate_retrieval_policy_anchor_binding(
        retrieval_policy.get("anchor_binding"),
        declared_fields=declared_fields,
    )
    _validate_policy_boost_fields(retrieval_policy.get("boost_fields"), declared_fields=declared_fields)
    _validate_policy_anchor_fields(retrieval_policy.get("anchor_fields"), declared_fields=declared_fields)
    _validate_policy_fallback(retrieval_policy.get("fallback"))
    _validate_policy_response_compaction(retrieval_policy.get("response_compaction"))


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


def _collect_metadata_schema_views(
    fields: list[MetadataField],
    *,
    meta: dict[str, Any],
    stage: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
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
    return indexed, display, evaluable


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
    indexed, display, evaluable = _collect_metadata_schema_views(fields, meta=meta, stage=stage)

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
