"""Plan the primary and expansion dataset scopes from ordered route hints."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class DatasetRouteHint:
    terms: tuple[str, ...] = ()
    dataset_ids: tuple[UUID, ...] = ()
    mode: str = "prepend"


@dataclass(frozen=True)
class DatasetScopePlan:
    dataset_ids: tuple[UUID, ...]
    primary_dataset_ids: tuple[UUID, ...]
    expansion_dataset_ids: tuple[UUID, ...]
    base_dataset_ids: tuple[UUID, ...]
    matched_dataset_ids: tuple[UUID, ...]
    matched_terms: tuple[str, ...]
    strict_scope: bool
    route_count: int
    matched_route_count: int
    included_hint_dataset_count: int


@dataclass(frozen=True)
class _DatasetRouteState:
    current: tuple[UUID, ...]
    strict_scope: bool
    matched_dataset_ids: tuple[UUID, ...]
    matched_replace_dataset_ids: tuple[UUID, ...]
    matched_terms: tuple[str, ...]
    matched_route_count: int


def normalize_route_mode(value: Any) -> str:
    mode = str(value or "prepend").strip().lower()
    if mode in {"replace", "override"}:
        return "replace"
    if mode in {"append", "extend"}:
        return "append"
    return "prepend"


def _dedupe_dataset_ids(dataset_ids: list[UUID] | tuple[UUID, ...]) -> tuple[UUID, ...]:
    return tuple(dict.fromkeys(dataset_ids))


def _hint_dataset_ids(route_hints: list[DatasetRouteHint] | tuple[DatasetRouteHint, ...]) -> tuple[UUID, ...]:
    out: list[UUID] = []
    for route in route_hints:
        out.extend(route.dataset_ids)
    return _dedupe_dataset_ids(out)


def _without_dataset_ids(dataset_ids: tuple[UUID, ...], excluded: tuple[UUID, ...]) -> tuple[UUID, ...]:
    excluded_set = set(excluded)
    return tuple(dataset_id for dataset_id in dataset_ids if dataset_id not in excluded_set)


def _matched_terms(route: DatasetRouteHint, query_text: str) -> tuple[str, ...]:
    if not query_text:
        return ()
    out: list[str] = []
    for raw in route.terms:
        term = raw.strip()
        if term and term.casefold() in query_text:
            out.append(term)
    return tuple(out)


def _initial_dataset_scope(
    base_ids: tuple[UUID, ...],
    *,
    hint_ids: tuple[UUID, ...],
    strict_routes: bool,
    include_unmatched_hint_datasets: bool,
) -> tuple[UUID, ...]:
    if strict_routes or not include_unmatched_hint_datasets:
        return base_ids
    return _dedupe_dataset_ids([*base_ids, *hint_ids])


def _apply_dataset_route(
    current: tuple[UUID, ...],
    *,
    route_dataset_ids: tuple[UUID, ...],
    mode: str,
    strict_routes: bool,
    strict_scope: bool,
) -> tuple[tuple[UUID, ...], bool]:
    if strict_routes and mode == "replace":
        return route_dataset_ids, True
    if mode == "append":
        return _dedupe_dataset_ids([*current, *route_dataset_ids]), strict_scope
    return _dedupe_dataset_ids([*route_dataset_ids, *current]), strict_scope


def _apply_dataset_route_hints(
    hints: tuple[DatasetRouteHint, ...],
    *,
    query: str,
    strict_routes: bool,
    current: tuple[UUID, ...],
) -> _DatasetRouteState:
    matched_dataset_ids: list[UUID] = []
    matched_replace_dataset_ids: list[UUID] = []
    matched_terms: list[str] = []
    matched_route_count = 0
    strict_scope = False
    query_text = query.strip().casefold()

    for route in hints:
        terms = _matched_terms(route, query_text)
        if not terms:
            continue
        route_dataset_ids = _dedupe_dataset_ids(route.dataset_ids)
        if not route_dataset_ids:
            continue
        matched_route_count += 1
        matched_dataset_ids.extend(route_dataset_ids)
        matched_terms.extend(terms)
        mode = normalize_route_mode(route.mode)
        current, strict_scope = _apply_dataset_route(
            current,
            route_dataset_ids=route_dataset_ids,
            mode=mode,
            strict_routes=strict_routes,
            strict_scope=strict_scope,
        )
        if mode == "replace":
            matched_replace_dataset_ids.extend(route_dataset_ids)
    return _DatasetRouteState(
        current=current,
        strict_scope=strict_scope,
        matched_dataset_ids=tuple(matched_dataset_ids),
        matched_replace_dataset_ids=tuple(matched_replace_dataset_ids),
        matched_terms=tuple(matched_terms),
        matched_route_count=matched_route_count,
    )


def _plan_primary_and_expansion_scope(
    *,
    base_ids: tuple[UUID, ...],
    current: tuple[UUID, ...],
    hint_ids: tuple[UUID, ...],
    matched_ids: tuple[UUID, ...],
    matched_replace_ids: tuple[UUID, ...],
    strict_scope: bool,
    strict_routes: bool,
    include_unmatched_hint_datasets: bool,
    matched_replace_routes_as_primary_scope: bool,
) -> tuple[tuple[UUID, ...], tuple[UUID, ...]]:
    if strict_scope:
        return current, ()
    if matched_replace_routes_as_primary_scope and matched_replace_ids:
        return matched_replace_ids, _without_dataset_ids(current, matched_replace_ids)
    if matched_ids:
        return current, ()
    if hint_ids and not strict_routes and include_unmatched_hint_datasets:
        return current, ()
    if base_ids:
        return base_ids, _without_dataset_ids(current, base_ids)
    return current, ()


def plan_dataset_scope(
    *,
    base_dataset_ids: list[UUID] | tuple[UUID, ...],
    route_hints: list[DatasetRouteHint] | tuple[DatasetRouteHint, ...] = (),
    query: str,
    strict_routes: bool = False,
    include_unmatched_hint_datasets: bool = True,
    matched_replace_routes_as_primary_scope: bool = False,
) -> DatasetScopePlan:
    base_ids = _dedupe_dataset_ids(base_dataset_ids)
    hints = tuple(route_hints)
    hint_ids = _hint_dataset_ids(hints)
    current = _initial_dataset_scope(
        base_ids,
        hint_ids=hint_ids,
        strict_routes=strict_routes,
        include_unmatched_hint_datasets=include_unmatched_hint_datasets,
    )
    route_state = _apply_dataset_route_hints(hints, query=query, strict_routes=strict_routes, current=current)
    current = route_state.current
    strict_scope = route_state.strict_scope
    matched_ids = _dedupe_dataset_ids(route_state.matched_dataset_ids)
    matched_replace_ids = _dedupe_dataset_ids(route_state.matched_replace_dataset_ids)
    primary_ids, expansion_ids = _plan_primary_and_expansion_scope(
        base_ids=base_ids,
        current=current,
        hint_ids=hint_ids,
        matched_ids=matched_ids,
        matched_replace_ids=matched_replace_ids,
        strict_scope=strict_scope,
        strict_routes=strict_routes,
        include_unmatched_hint_datasets=include_unmatched_hint_datasets,
        matched_replace_routes_as_primary_scope=matched_replace_routes_as_primary_scope,
    )

    return DatasetScopePlan(
        dataset_ids=current,
        primary_dataset_ids=primary_ids,
        expansion_dataset_ids=expansion_ids,
        base_dataset_ids=base_ids,
        matched_dataset_ids=matched_ids,
        matched_terms=tuple(dict.fromkeys(route_state.matched_terms)),
        strict_scope=strict_scope,
        route_count=len(hints),
        matched_route_count=route_state.matched_route_count,
        included_hint_dataset_count=len(hint_ids),
    )


__all__ = [
    "DatasetRouteHint",
    "DatasetScopePlan",
    "normalize_route_mode",
    "plan_dataset_scope",
]
