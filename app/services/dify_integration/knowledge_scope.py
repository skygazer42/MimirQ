import json
from functools import partial
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from app.core.config import settings
from app.core.env import is_production_env
from app.rag.retrieval.planner import (
    DatasetRouteHint,
    DatasetScopePlan,
    normalize_route_mode,
    plan_dataset_scope,
    retrieval_policy_fallback_multiplier,
)
from app.services.dify_integration import common, policy_helpers
from app.services.dify_integration.auth import _coerce_uuid, _split_items
from app.services.dify_integration.policy_helpers import knowledge_mapping_plugin_refs
from app.services.dify_integration.query_terms import query_has_specific_service_anchor_candidate


def load_knowledge_map() -> dict[str, Any]:
    raw = settings.DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON.strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=503, detail="Dify knowledge map JSON is invalid") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=503, detail="Dify knowledge map JSON must be an object")
    return data


def _coerce_dataset_id_list(value: Any) -> list[UUID]:
    if isinstance(value, dict):
        for key in ("dataset_ids", "datasets", "dataset_id"):
            if key in value:
                return _coerce_dataset_id_list(value[key])
        raise HTTPException(status_code=400, detail="Dify knowledge mapping must include dataset_id or dataset_ids")
    if isinstance(value, str):
        return [_coerce_uuid(value, label="dataset id")]
    if isinstance(value, list | tuple | set):
        dataset_ids: list[UUID] = []
        for item in value:
            if isinstance(item, dict):
                dataset_ids.extend(_coerce_dataset_id_list(item))
            else:
                dataset_ids.append(_coerce_uuid(item, label="dataset id"))
        return common._dedupe_dataset_ids(dataset_ids)
    raise HTTPException(status_code=400, detail="Dify knowledge mapping must be a dataset id or list")


def _route_hint_terms(raw_route: dict[str, Any]) -> tuple[str, ...]:
    raw_terms = raw_route.get("terms") or raw_route.get("query_terms") or raw_route.get("contains")
    terms = raw_terms if isinstance(raw_terms, list | tuple | set) else [raw_terms]
    return tuple(str(term).strip() for term in terms if term is not None and str(term).strip())


def _mapping_query_routes(mapping: dict[str, Any]) -> list[Any] | None:
    routes = mapping.get("query_routes") or mapping.get("query_dataset_routes") or mapping.get("routes")
    return routes if isinstance(routes, list) else None


def _route_hints_from_routes(routes: list[Any]) -> list[DatasetRouteHint]:
    hints: list[DatasetRouteHint] = []
    for raw_route in routes:
        if not isinstance(raw_route, dict):
            continue
        dataset_ids = _coerce_dataset_id_list(raw_route)
        if dataset_ids:
            hints.append(
                DatasetRouteHint(
                    terms=_route_hint_terms(raw_route),
                    dataset_ids=tuple(dataset_ids),
                    mode=normalize_route_mode(raw_route.get("mode") or raw_route.get("merge") or "prepend"),
                )
            )
    return hints


def _merge_route_hints(*groups: list[DatasetRouteHint]) -> list[DatasetRouteHint]:
    merged: list[DatasetRouteHint] = []
    seen: set[tuple[tuple[str, ...], tuple[UUID, ...], str]] = set()
    for group in groups:
        for hint in group:
            identity = (hint.terms, hint.dataset_ids, hint.mode)
            if identity not in seen:
                seen.add(identity)
                merged.append(hint)
    return merged


def _normalized_inherited_route_sources(raw_sources: Any) -> list[str]:
    if isinstance(raw_sources, set):
        sources = sorted(raw_sources, key=str)
    elif isinstance(raw_sources, list | tuple):
        sources = raw_sources
    else:
        sources = [raw_sources]
    result: list[str] = []
    seen: set[str] = set()
    for source in sources:
        key = common._first_nonempty_str(source)
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result


def _append_unique_route_hints(
    inherited: list[DatasetRouteHint],
    *,
    raw_mapping: Any,
    seen: set[tuple[tuple[str, ...], tuple[UUID, ...], str]],
) -> None:
    if not isinstance(raw_mapping, dict):
        return
    routes = _mapping_query_routes(raw_mapping)
    for hint in _route_hints_from_routes(routes or []):
        identity = (hint.terms, hint.dataset_ids, hint.mode)
        if hint.dataset_ids and identity not in seen:
            seen.add(identity)
            inherited.append(hint)


def _inherited_query_route_hints(
    *,
    knowledge_map: dict[str, Any],
    current_key: str,
    base_dataset_ids: list[UUID],
) -> list[DatasetRouteHint]:
    if not base_dataset_ids:
        return []
    current = knowledge_map.get(current_key)
    raw_sources = current.get("inherit_query_routes_from") if isinstance(current, dict) else None
    inherited_sources = _normalized_inherited_route_sources(raw_sources)
    inherited: list[DatasetRouteHint] = []
    seen: set[tuple[tuple[str, ...], tuple[UUID, ...], str]] = set()
    for mapping_key in inherited_sources:
        _append_unique_route_hints(
            inherited,
            raw_mapping=knowledge_map.get(mapping_key),
            seen=seen,
        )
    return inherited


def _plan_query_dataset_scope(
    base_dataset_ids: list[UUID],
    mapping: dict[str, Any],
    *,
    query: str,
    inherited_route_hints: list[DatasetRouteHint] | None = None,
) -> DatasetScopePlan:
    routes = _mapping_query_routes(mapping)
    if not routes and not inherited_route_hints:
        return plan_dataset_scope(base_dataset_ids=base_dataset_ids, query=query)
    hints = _merge_route_hints(list(inherited_route_hints or []), _route_hints_from_routes(routes or []))
    strict_routes = bool(hints and (mapping.get("strict_query_routes") or mapping.get("query_routes_strict")))
    return plan_dataset_scope(
        base_dataset_ids=base_dataset_ids,
        route_hints=hints,
        query=query,
        strict_routes=strict_routes,
        include_unmatched_hint_datasets=settings.DIFY_EXTERNAL_KNOWLEDGE_INCLUDE_UNMATCHED_ROUTE_HINTS,
        matched_replace_routes_as_primary_scope=strict_routes,
    )


def knowledge_resolution_mode() -> str:
    mode = settings.DIFY_EXTERNAL_KNOWLEDGE_RESOLUTION_MODE or "mapped_only"
    return mode.strip().lower() or "mapped_only"


def resolve_scope(knowledge_id: str, *, query: str = "") -> DatasetScopePlan:
    key = knowledge_id.strip()
    knowledge_map = load_knowledge_map()
    if key in knowledge_map:
        mapping = knowledge_map[key]
        dataset_ids = _coerce_dataset_id_list(mapping)
        if isinstance(mapping, dict):
            plan = _plan_query_dataset_scope(
                dataset_ids,
                mapping,
                query=query,
                inherited_route_hints=_inherited_query_route_hints(
                    knowledge_map=knowledge_map,
                    current_key=key,
                    base_dataset_ids=dataset_ids,
                ),
            )
        else:
            plan = plan_dataset_scope(base_dataset_ids=dataset_ids, query=query)
        if not plan.dataset_ids:
            raise HTTPException(status_code=404, detail="Dify knowledge mapping is empty")
        return plan

    if knowledge_resolution_mode() != "allow_dataset_uuid" or is_production_env():
        raise HTTPException(status_code=404, detail="Dify knowledge mapping not found")
    try:
        dataset_id = UUID(key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Dify knowledge mapping not found") from exc
    return plan_dataset_scope(base_dataset_ids=[dataset_id], query=query)


def resolve_dataset_ids(knowledge_id: str, *, query: str = "") -> list[UUID]:
    return list(resolve_scope(knowledge_id, query=query).dataset_ids)


def resolve_policy_plugin_refs(knowledge_id: str) -> tuple[str, ...]:
    return policy_helpers.resolve_knowledge_policy_plugin_refs(
        knowledge_id,
        knowledge_map=load_knowledge_map(),
        knowledge_mapping_plugin_refs=policy_helpers.knowledge_mapping_plugin_refs,
    )


def resolve_policy_filter_fields(knowledge_id: str) -> set[str] | None:
    return policy_helpers.resolve_knowledge_policy_filter_fields(
        knowledge_id,
        knowledge_map=load_knowledge_map(),
        knowledge_mapping_plugin_refs=policy_helpers.knowledge_mapping_plugin_refs,
        retrieval_policy_filter_fields_for_plugin_refs=partial(
            policy_helpers.retrieval_policy_filter_fields_for_plugin_refs,
            policy_resolver=policy_helpers.retrieval_policy_for_plugin_ref,
        ),
    )


def resolve_policy_fallback_multiplier(knowledge_id: str) -> int:
    return policy_helpers.resolve_knowledge_policy_fallback_multiplier(
        knowledge_id,
        knowledge_map=load_knowledge_map(),
        knowledge_mapping_plugin_refs=policy_helpers.knowledge_mapping_plugin_refs,
        retrieval_policy_fallback_multiplier_for_plugin_refs=partial(
            policy_helpers.retrieval_policy_fallback_multiplier_for_plugin_refs,
            policy_resolver=policy_helpers.retrieval_policy_for_plugin_ref,
            fallback_multiplier_resolver=retrieval_policy_fallback_multiplier,
        ),
    )


def resolve_warmup_knowledge_ids(knowledge_map: dict[str, Any] | None = None) -> tuple[str, ...]:
    raw_ids = _split_items(settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_KNOWLEDGE_IDS)
    candidates = raw_ids if raw_ids else [str(key).strip() for key in (knowledge_map or load_knowledge_map())]
    try:
        max_ids = settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_MAX_KNOWLEDGE_IDS
    except (TypeError, ValueError):
        max_ids = 8
    if max_ids <= 0:
        return ()

    seen: set[str] = set()
    out: list[str] = []
    for item in candidates:
        knowledge_id = item.strip()
        if knowledge_id and knowledge_id not in seen:
            seen.add(knowledge_id)
            out.append(knowledge_id)
            if len(out) >= max_ids:
                break
    return tuple(out)


def _mapping_has_external_route_hint(mapping: dict[str, Any], *, base_dataset_ids: list[UUID]) -> bool:
    base_ids = set(base_dataset_ids)
    return any(
        route_dataset_id not in base_ids
        for hint in _route_hints_from_routes(_mapping_query_routes(mapping) or [])
        for route_dataset_id in hint.dataset_ids
    )


def _expanded_metadata_anchor_dataset_ids(
    knowledge_map: dict[str, Any],
    *,
    requested_refs: set[str],
    dataset_ids: list[UUID],
) -> list[UUID]:
    expanded = list(dataset_ids)
    for mapping in knowledge_map.values():
        if not isinstance(mapping, dict):
            continue
        mapping_refs = set(knowledge_mapping_plugin_refs(mapping))
        if not mapping_refs or requested_refs.isdisjoint(mapping_refs):
            continue
        try:
            expanded.extend(_coerce_dataset_id_list(mapping))
        except HTTPException:
            continue
        expanded.extend(
            dataset_id
            for hint in _route_hints_from_routes(_mapping_query_routes(mapping) or [])
            for dataset_id in hint.dataset_ids
        )
    return expanded


def extend_sibling_policy_scope(
    *,
    knowledge_id: str,
    base_dataset_ids: list[UUID] | tuple[UUID, ...],
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[UUID]:
    dataset_ids = common._dedupe_dataset_ids(base_dataset_ids)
    if not dataset_ids:
        return []
    if (
        not settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_EXTEND_SIBLING_POLICY_SCOPE_ENABLED
        or not query_has_specific_service_anchor_candidate(query, policy_plugin_refs=policy_plugin_refs)
    ):
        return dataset_ids

    requested_refs = {ref.strip() for ref in policy_plugin_refs if ref.strip()}
    if not requested_refs:
        return dataset_ids
    knowledge_map = load_knowledge_map()
    current_mapping = knowledge_map.get(knowledge_id.strip())
    if not isinstance(current_mapping, dict):
        return dataset_ids
    try:
        current_base_ids = common._dedupe_dataset_ids(_coerce_dataset_id_list(current_mapping))
    except HTTPException:
        return dataset_ids
    if set(dataset_ids) != set(current_base_ids):
        return dataset_ids
    if not _mapping_has_external_route_hint(current_mapping, base_dataset_ids=current_base_ids):
        return dataset_ids

    expanded = _expanded_metadata_anchor_dataset_ids(
        knowledge_map,
        requested_refs=requested_refs,
        dataset_ids=dataset_ids,
    )
    max_datasets = max(
        len(dataset_ids),
        min(200, settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_EXTENDED_SCOPE_MAX_DATASETS),
    )
    return common._dedupe_dataset_ids(expanded)[:max_datasets]


def apply_query_dataset_routes(base_dataset_ids: list[UUID], mapping: dict[str, Any], *, query: str) -> list[UUID]:
    return list(_plan_query_dataset_scope(base_dataset_ids, mapping, query=query).dataset_ids)


__all__ = [
    "apply_query_dataset_routes",
    "extend_sibling_policy_scope",
    "knowledge_resolution_mode",
    "load_knowledge_map",
    "resolve_dataset_ids",
    "resolve_policy_fallback_multiplier",
    "resolve_policy_filter_fields",
    "resolve_policy_plugin_refs",
    "resolve_scope",
    "resolve_warmup_knowledge_ids",
]
