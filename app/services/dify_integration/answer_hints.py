"""Dify answer hints rules and operations."""

from collections.abc import Callable
from typing import Any

from app.services.dify_integration.common import (
    _DEFAULT_RESPONSE_HINT_ANSWER_PREFIX as _DEFAULT_RESPONSE_HINT_ANSWER_PREFIX,
)
from app.services.dify_integration.common import _DEFAULT_RESPONSE_HINT_SOURCE_PREFIX, _first_nonempty_str
from app.services.dify_integration.common import _MAX_HINT_VALUE_CHARS as _MAX_HINT_VALUE_CHARS
from app.services.dify_integration.common import _PUBLIC_METADATA_VIEW_KEYS as _PUBLIC_METADATA_VIEW_KEYS
from app.services.dify_integration.common import _metadata_terms as _metadata_terms
from app.services.dify_integration.common import _normalize_match_term as _normalize_match_term
from app.services.dify_integration.common import (
    _response_hint_metadata_conditions_match as _response_hint_metadata_conditions_match,
)
from app.services.dify_integration.policy_helpers import (
    fast_response_always_labels_for_policy_refs as _fast_response_always_labels_for_policy_refs,
)
from app.services.dify_integration.policy_helpers import (
    fast_response_field_rules_for_policy_refs as _fast_response_field_rules_for_policy_refs,
)
from app.services.dify_integration.policy_helpers import response_hints_for_metadata as _response_hints_for_metadata
from app.services.dify_integration.scoring import _answer_hints_from_fields as _answer_hints_from_fields
from app.services.dify_integration.scoring import _clamp_hint_value as _clamp_hint_value
from app.services.dify_integration.scoring import (
    _content_starts_with_response_hint as _content_starts_with_response_hint,
)
from app.services.dify_integration.scoring import _enumerated_answer_hints as _enumerated_answer_hints
from app.services.dify_integration.scoring import _matching_response_hint_group as _matching_response_hint_group
from app.services.dify_integration.scoring import _response_hint_dict_list as _response_hint_dict_list
from app.services.dify_integration.scoring import _response_hint_string_list as _response_hint_string_list
from app.services.dify_integration.scoring import _response_hint_text as _response_hint_text
from app.services.dify_integration.scoring import _structured_fields_from_content as _structured_fields_from_content


def _metadata_answer_highlights(
    metadata: dict[str, Any],
    *,
    response_hints: dict[str, Any],
    query: str = "",
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[str]:
    highlights: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        value = text.strip()
        if not value or value in seen:
            return
        seen.add(value)
        highlights.append(value)

    highlight_keys = _response_hint_string_list(response_hints, "answer_highlight_metadata")
    field_specs = _response_hint_dict_list(response_hints, "answer_highlight_metadata_fields")
    answer_field_configured = _metadata_answer_field_configured(highlight_keys, field_specs)
    for layer in _metadata_answer_highlight_layers(metadata):
        if not isinstance(layer, dict):
            continue
        _add_metadata_answer_default_highlight(
            layer,
            add=add,
            answer_field_configured=answer_field_configured,
        )
        _add_metadata_answer_hint_values(layer, highlight_keys=highlight_keys, add=add)
        for field_spec in field_specs:
            _add_metadata_answer_field_spec_highlights(
                layer,
                field_spec=field_spec,
                query=query,
                policy_plugin_refs=policy_plugin_refs,
                add=add,
            )
    return highlights


def _metadata_answer_field_configured(
    highlight_keys: tuple[str, ...],
    field_specs: tuple[dict[str, Any], ...],
) -> bool:
    return "answer" in highlight_keys or any(
        _first_nonempty_str(spec.get("metadata"), spec.get("key"), spec.get("field")) == "answer"
        for spec in field_specs
    )


def _metadata_answer_highlight_layers(metadata: dict[str, Any]) -> list[Any]:
    return [metadata, *[metadata.get(key) for key in _PUBLIC_METADATA_VIEW_KEYS]]


def _add_metadata_answer_default_highlight(
    layer: dict[str, Any],
    *,
    add: Callable[[str], None],
    answer_field_configured: bool,
) -> None:
    if answer_field_configured:
        return
    for value in _metadata_terms(layer.get("answer")):
        add(f"答案：{_clamp_hint_value(value, limit=1600)}")


def _add_metadata_answer_hint_values(
    layer: dict[str, Any],
    *,
    highlight_keys: tuple[str, ...],
    add: Callable[[str], None],
) -> None:
    for key in highlight_keys:
        for value in _metadata_terms(layer.get(key)):
            add(_clamp_hint_value(value))


def _response_hint_metadata_fields(field_spec: dict[str, Any]) -> tuple[str, ...]:
    fields = _response_hint_string_list(field_spec, "fields")
    single_field = _first_nonempty_str(field_spec.get("field"))
    if single_field and single_field not in fields:
        fields = (*fields, single_field)
    return fields


def _add_metadata_answer_field_spec_highlights(
    layer: dict[str, Any],
    *,
    field_spec: dict[str, Any],
    query: str,
    policy_plugin_refs: tuple[str, ...],
    add: Callable[[str], None],
) -> None:
    if not _response_hint_metadata_conditions_match(layer, field_spec):
        return
    metadata_key = _first_nonempty_str(field_spec.get("metadata"), field_spec.get("key"))
    source = layer.get(metadata_key) if metadata_key else layer
    if source is None:
        return
    max_chars = max(1, min(3000, int(field_spec.get("max_chars") or _MAX_HINT_VALUE_CHARS)))
    if isinstance(source, dict):
        _add_metadata_answer_dict_field_spec_highlights(
            source,
            field_spec=field_spec,
            max_chars=max_chars,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
            add=add,
        )
        return
    label = str(field_spec.get("label") or metadata_key).strip()
    if not label:
        return
    for value in _metadata_terms(source):
        add(f"{label}：{_clamp_hint_value(value, limit=max_chars)}")


def _add_metadata_answer_dict_field_spec_highlights(
    source: dict[str, Any],
    *,
    field_spec: dict[str, Any],
    max_chars: int,
    query: str,
    policy_plugin_refs: tuple[str, ...],
    add: Callable[[str], None],
) -> None:
    labels = field_spec.get("labels") if isinstance(field_spec.get("labels"), dict) else {}
    ordered_fields = _prioritized_response_hint_metadata_fields(
        _response_hint_metadata_fields(field_spec),
        query=query,
        policy_plugin_refs=policy_plugin_refs,
        enabled=field_spec.get("prioritize_query_fields") is True,
    )
    requested_labels = _requested_response_hint_metadata_labels(
        ordered_fields,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
        enabled=field_spec.get("prioritize_query_fields") is True,
    )
    requested_prefix = _first_nonempty_str(field_spec.get("requested_labels_prefix"))
    if requested_prefix and requested_labels:
        separator = str(field_spec.get("requested_labels_separator") or "、")
        add(f"{requested_prefix}：{separator.join(requested_labels)}")
    for field in ordered_fields:
        label = str(labels.get(field) or field).strip()
        if not label:
            continue
        for value in _metadata_terms(source.get(field)):
            add(f"{label}：{_clamp_hint_value(value, limit=max_chars)}")


def _content_with_answer_hints(
    content: str,
    metadata: dict[str, Any],
    *,
    query: str = "",
    policy_plugin_refs: tuple[str, ...] = (),
) -> str:
    body = content.strip()
    if not body:
        return body
    response_hints = _response_hints_for_metadata(metadata, policy_plugin_refs=policy_plugin_refs)
    enumerated_hints = _enumerated_answer_hints(body, query=query, response_hints=response_hints)
    enumerated_prefix = "；".join(enumerated_hints)
    if _content_starts_with_response_hint(body, response_hints=response_hints):
        if enumerated_prefix and not body.startswith(enumerated_prefix):
            return f"{enumerated_prefix}\n\n{body}"
        return body
    metadata_hints = _metadata_answer_highlights(
        metadata,
        response_hints=response_hints,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )
    fields = _structured_fields_from_content(body, response_hints=response_hints)
    if (
        fields
        and not metadata_hints
        and not _matching_response_hint_group(fields, metadata, response_hints=response_hints, query=query)
    ):
        return body
    hints = metadata_hints or _answer_hints_from_fields(
        fields,
        metadata,
        response_hints=response_hints,
        query=query,
    )
    if not hints and not enumerated_prefix:
        return body
    answer_prefix = _response_hint_text(
        response_hints,
        "answer_prefix",
        default=_DEFAULT_RESPONSE_HINT_ANSWER_PREFIX,
    )
    source_prefix = _response_hint_text(
        response_hints,
        "source_prefix",
        default=_DEFAULT_RESPONSE_HINT_SOURCE_PREFIX,
    )
    if enumerated_prefix and not hints:
        return f"{enumerated_prefix}\n\n{source_prefix}：\n{body}"
    if enumerated_prefix:
        return f"{enumerated_prefix}\n\n{answer_prefix}：{'；'.join(hints)}\n\n{source_prefix}：\n{body}"
    return f"{answer_prefix}：{'；'.join(hints)}\n\n{source_prefix}：\n{body}"


def _requested_fast_response_labels(
    query: str,
    fields: dict[str, str],
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> tuple[str, ...]:
    query_text = query
    labels: list[str] = []
    seen: set[str] = set()

    def add(label: str) -> None:
        if label in seen or label not in fields:
            return
        seen.add(label)
        labels.append(label)

    if "答案" in fields:
        add("问题")
        add("答案")
        return tuple(labels)

    rules = _fast_response_field_rules_for_policy_refs(policy_plugin_refs)
    exact_labels = _requested_fast_response_exact_labels(
        query_text,
        rules,
        add=add,
        policy_plugin_refs=policy_plugin_refs,
    )
    normalized_exact_labels = tuple(
        normalized for normalized in (_normalize_match_term(label) for label in exact_labels) if normalized
    )
    for label, markers in rules:
        if label in exact_labels or _fast_response_rule_is_shadowed(
            markers=markers,
            query_text=query_text,
            normalized_exact_labels=normalized_exact_labels,
        ):
            continue
        add(label)
    return tuple(labels)


def _requested_fast_response_exact_labels(
    query_text: str,
    rules: tuple[tuple[str, tuple[str, ...]], ...],
    *,
    add: Callable[[str], None],
    policy_plugin_refs: tuple[str, ...] = (),
) -> set[str]:
    exact_labels: set[str] = set()
    for label in _fast_response_always_labels_for_policy_refs(policy_plugin_refs):
        add(label)
    for label, _markers in rules:
        if label not in query_text:
            continue
        exact_labels.add(label)
        add(label)
    return exact_labels


def _fast_response_rule_is_shadowed(
    *,
    markers: tuple[str, ...],
    query_text: str,
    normalized_exact_labels: tuple[str, ...],
) -> bool:
    matched_markers = tuple(marker for marker in markers if marker in query_text)
    if not matched_markers:
        return True
    if not normalized_exact_labels:
        return False
    for marker in matched_markers:
        normalized_marker = _normalize_match_term(marker)
        if not normalized_marker:
            continue
        if not any(
            normalized_marker != exact_label and normalized_marker in exact_label
            for exact_label in normalized_exact_labels
        ):
            return False
    return True


def _requested_response_hint_metadata_labels(
    fields: tuple[str, ...],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
    enabled: bool,
) -> tuple[str, ...]:
    if not enabled:
        return ()
    query_text = query
    if not query_text:
        return ()
    available = set(fields)
    labels: list[str] = []
    seen: set[str] = set()
    for label, markers in _fast_response_field_rules_for_policy_refs(policy_plugin_refs):
        if label not in available or label in seen:
            continue
        if not any(marker in query_text for marker in markers):
            continue
        seen.add(label)
        labels.append(label)
    return tuple(labels)


def _prioritized_response_hint_metadata_fields(
    fields: tuple[str, ...],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
    enabled: bool,
) -> tuple[str, ...]:
    if not enabled:
        return fields
    requested = _requested_response_hint_metadata_labels(
        fields,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
        enabled=True,
    )
    if not requested:
        return fields
    ordered: list[str] = []
    seen: set[str] = set()
    for field in (*requested, *fields):
        if field in seen:
            continue
        seen.add(field)
        ordered.append(field)
    return tuple(ordered)
