"""Scoped KG query expansion and the shared synchronous KG read operation."""

import asyncio
import concurrent.futures
import time
from typing import Any

from app.rag.retrieval.orchestration.common import _log_orchestrator_fallback
from app.rag.retrieval.orchestration.query_contracts import KGExpansionSettings, KGQueryExpansion, KGQueryRequest


class KGResponseContractError(TypeError):
    """The service returned a value outside its required response contract."""


def raise_for_rejected_response(expansion: KGQueryExpansion | None) -> None:
    if expansion is not None and isinstance(expansion.failure, KGResponseContractError):
        raise expansion.failure


async def search_kg_query_async(request: KGQueryRequest) -> dict[str, Any]:
    from app.rag.kg.pipeline import kg_search

    scope = request.scope
    result = await kg_search(
        query=request.query,
        tenant_id=scope.tenant_id,
        account_id=scope.account_id,
        document_ids=None if scope.document_ids is None else list(scope.document_ids),
        dataset_id=scope.dataset_id,
        dataset_ids=list(scope.dataset_ids) if scope.dataset_ids else None,
    )
    if not isinstance(result, dict):
        raise KGResponseContractError("KG search must return an object")
    return result


def search_kg_query(request: KGQueryRequest) -> dict[str, Any]:
    """Read the actual KG service, preserving the caller's existing event loop."""
    coro = search_kg_query_async(request)
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    if loop is not None:
        return loop.run_until_complete(coro)
    return asyncio.run(coro)


def _scored_entities(entities: list[object], settings: KGExpansionSettings) -> list[tuple[float, str]]:
    if "*" in settings.exclude_types:
        return []
    excluded = {name.casefold() for name in settings.exclude_types}
    scored = []
    for entity in entities:
        if not isinstance(entity, dict):
            raise TypeError("KG entity must be an object")
        entity_type = entity.get("type", "")
        if not isinstance(entity_type, str):
            raise TypeError("KG entity type must be text")
        if entity_type.strip().casefold() in excluded:
            continue
        name = entity["name"]
        if not isinstance(name, str):
            raise TypeError("KG entity name must be text")
        name = name.strip()
        if not name:
            continue
        weight = float(entity.get("weight", 0.0))
        if weight >= settings.min_weight:
            scored.append((weight, name))
    return sorted(scored, key=lambda item: (-item[0], item[1]))


def _select_entity_names(scored: list[tuple[float, str]], *, query: str, max_entities: int) -> list[str]:
    seen = set()
    base_folded = query.casefold()
    names = []
    for _weight, name in scored:
        key = name.casefold() if name.isascii() else name
        if key in seen:
            continue
        seen.add(key)
        if key in base_folded:
            continue
        names.append(name)
        if max_entities > 0 and len(names) >= max_entities:
            break
    return names


def _allowed(request: KGQueryRequest, settings: KGExpansionSettings) -> bool:
    scope = request.scope
    return bool(
        settings.enabled
        and settings.service_enabled
        and scope.tenant_id is not None
        and (scope.document_ids or scope.dataset_id is not None or scope.dataset_ids)
        and (scope.account_id is not None or (scope.dataset_id is None and not scope.dataset_ids))
    )


def _response_entities(response: dict[str, Any]) -> list[object]:
    entities = response.get("entities")
    if entities is None:
        return []
    if not isinstance(entities, list):
        raise TypeError("KG entities must be an array")
    return entities


def _expanded_queries(
    request: KGQueryRequest, settings: KGExpansionSettings, entities: list[object]
) -> tuple[list[str], list[str], int]:
    scored = _scored_entities(entities, settings)
    names = _select_entity_names(scored, query=request.query, max_entities=settings.max_entities)
    selected_count = len(names)
    if settings.max_queries > 0:
        names = names[: settings.max_queries]
    queries = []
    for name in names:
        expanded = f"{request.query} {name}".strip()
        queries.append(expanded[:500] + "..." if len(expanded) > 500 else expanded)
    return queries, names, selected_count


def expand_kg_query(request: KGQueryRequest, *, settings: KGExpansionSettings) -> KGQueryExpansion:
    if not _allowed(request, settings):
        return KGQueryExpansion(settings.enabled, [], [], 0, 0, 0.0, None)
    response = None
    elapsed = 0.0
    total = 0
    try:
        started = time.perf_counter()
        response = search_kg_query(request)
        elapsed = time.perf_counter() - started
        entities = _response_entities(response)
        total = len(entities)
        queries, names, selected_count = _expanded_queries(request, settings, entities)
        return KGQueryExpansion(settings.enabled, queries, names, total, selected_count, elapsed, response)
    except Exception as exc:
        _log_orchestrator_fallback("expand_kg_query", exc)
        return KGQueryExpansion(settings.enabled, [], [], total, 0, elapsed, response, exc)


async def expand_kg_query_async(request: KGQueryRequest, *, settings: KGExpansionSettings) -> KGQueryExpansion:
    if not _allowed(request, settings):
        return KGQueryExpansion(settings.enabled, [], [], 0, 0, 0.0, None)
    response = None
    elapsed = 0.0
    total = 0
    try:
        started = time.perf_counter()
        response = await search_kg_query_async(request)
        elapsed = time.perf_counter() - started
        entities = _response_entities(response)
        total = len(entities)
        queries, names, selected_count = _expanded_queries(request, settings, entities)
        return KGQueryExpansion(settings.enabled, queries, names, total, selected_count, elapsed, response)
    except Exception as exc:
        _log_orchestrator_fallback("expand_kg_query", exc)
        return KGQueryExpansion(settings.enabled, [], [], total, 0, elapsed, response, exc)
