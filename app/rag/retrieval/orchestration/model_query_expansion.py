"""Bounded model query strategies sharing rules across native sync/async calls."""

import time
from dataclasses import dataclass
from typing import Any

from app.rag.core.hashing import stable_hash
from app.rag.core.json_text import parse_json_from_text
from app.rag.retrieval.orchestration.common import _log_orchestrator_fallback
from app.rag.retrieval.orchestration.query_contracts import (
    AsyncQueryVariantModels,
    AsyncTextQueryModel,
    DecompositionSettings,
    ModelQueryExpansions,
    ModelQueryRequest,
    MultiQuerySettings,
    QueryListOutcome,
    QueryVariantModels,
    StepBackQueryOutcome,
    TextQueryModel,
    TextQueryOutcome,
    TextQuerySettings,
)


class QueryModelOutputError(ValueError):
    """An optional strategy returned data outside its query output contract."""


@dataclass(frozen=True)
class _GeneratedText:
    text: str
    elapsed_sec: float
    model_used: str | None
    failure: Exception | None = None


def _checked_text(value: object) -> str:
    if not isinstance(value, str):
        raise QueryModelOutputError("Model output must be text")
    return value


def _invoke_text(model: TextQueryModel, *, query: str, operation: str) -> _GeneratedText:
    try:
        started = time.perf_counter()
        text = _checked_text(model.invoke(query=query))
        return _GeneratedText(text, time.perf_counter() - started, model.model_name)
    except Exception as exc:
        _log_orchestrator_fallback(operation, exc)
        return _GeneratedText("", 0.0, model.model_name, exc)


async def _ainvoke_text(model: AsyncTextQueryModel, *, query: str, operation: str) -> _GeneratedText:
    try:
        started = time.perf_counter()
        text = _checked_text(await model.ainvoke(query=query))
        return _GeneratedText(text, time.perf_counter() - started, model.model_name)
    except Exception as exc:
        _log_orchestrator_fallback(operation, exc)
        return _GeneratedText("", 0.0, model.model_name, exc)


def _not_run_metadata() -> dict[str, Any]:
    return {"ok": False, "method": None, "error": None}


def _failure_metadata(failure: Exception) -> dict[str, Any]:
    return {"ok": False, "method": None, "error": str(failure)[:200]}


def _normalized_queries(raw: object, *, query: str, count: int, max_chars: int) -> list[str]:
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise QueryModelOutputError("Model queries must be an array of text")
    seen = set()
    queries = []
    for item in raw:
        candidate = item.strip().strip('"').strip()
        if not candidate or candidate == query:
            continue
        if len(candidate) > max_chars:
            candidate = candidate[:max_chars] + "..."
        if candidate in seen:
            continue
        seen.add(candidate)
        queries.append(candidate)
        if len(queries) >= count:
            break
    return queries


def _query_array(
    raw: str, *, query: str, count: int, max_chars: int
) -> tuple[list[str], dict[str, Any], Exception | None]:
    data, metadata = parse_json_from_text(raw, expected="array")
    if not metadata["ok"]:
        return [], metadata, QueryModelOutputError(metadata["error"] or "Invalid model queries")
    try:
        return _normalized_queries(data, query=query, count=count, max_chars=max_chars), metadata, None
    except QueryModelOutputError as exc:
        return [], {**metadata, "ok": False, "error": str(exc)}, exc


def _multi_allowed(query: str, settings: MultiQuerySettings) -> bool:
    return settings.enabled and settings.count > 0 and settings.max_chars > 0 and len(query) <= settings.max_chars


def _text_allowed(query: str, settings: TextQuerySettings) -> bool:
    return settings.enabled and settings.max_chars > 0 and len(query) <= settings.max_chars


def _decomposition_allowed(query: str, settings: DecompositionSettings) -> bool:
    return bool(
        settings.enabled
        and settings.max_questions > 0
        and len(query) >= settings.min_chars
        and (settings.max_chars <= 0 or len(query) <= settings.max_chars)
    )


def _multi_result(query: str, settings: MultiQuerySettings, generated: _GeneratedText) -> QueryListOutcome:
    if generated.failure is not None:
        return QueryListOutcome(
            settings.enabled,
            [],
            generated.elapsed_sec,
            generated.model_used,
            _failure_metadata(generated.failure),
            generated.failure,
        )
    queries, metadata, failure = _query_array(generated.text, query=query, count=settings.count, max_chars=400)
    if settings.experiment.seed is not None and queries:
        seed = str(settings.experiment.seed)
        queries.sort(key=lambda item: (stable_hash(f"{seed}:{item}", length=16), item))
    return QueryListOutcome(settings.enabled, queries, generated.elapsed_sec, generated.model_used, metadata, failure)


def _hyde_result(settings: TextQuerySettings, generated: _GeneratedText) -> TextQueryOutcome:
    text = generated.text.strip()
    if settings.output_max_chars > 0 and len(text) > settings.output_max_chars:
        text = text[: settings.output_max_chars] + "..."
    return TextQueryOutcome(settings.enabled, text, generated.elapsed_sec, generated.model_used, generated.failure)


def _step_back_result(query: str, settings: TextQuerySettings, generated: _GeneratedText) -> StepBackQueryOutcome:
    if generated.failure is not None:
        return StepBackQueryOutcome(
            settings.enabled,
            "",
            generated.elapsed_sec,
            generated.model_used,
            _failure_metadata(generated.failure),
            generated.failure,
        )
    text = generated.text.strip().strip('"').strip()
    if settings.output_max_chars > 0 and len(text) > settings.output_max_chars:
        text = text[: settings.output_max_chars] + "..."
    if text and text != query:
        metadata = {"ok": True, "method": "text", "error": None}
    else:
        text = ""
        metadata = {"ok": False, "method": "text", "error": "empty_or_duplicate"}
    return StepBackQueryOutcome(settings.enabled, text, generated.elapsed_sec, generated.model_used, metadata)


def _heuristic(query: str, *, settings: DecompositionSettings, failure: Exception | None = None) -> QueryListOutcome:
    from app.rag.core.text import heuristic_decompose_query

    questions = heuristic_decompose_query(query, max_subquestions=settings.max_questions)
    metadata = {"ok": True, "method": "heuristic", "error": None} if questions else _not_run_metadata()
    return QueryListOutcome(settings.enabled, questions, 0.0, None, metadata, failure)


def _decomposition_result(query: str, settings: DecompositionSettings, generated: _GeneratedText) -> QueryListOutcome:
    if generated.failure is not None:
        result = QueryListOutcome(
            settings.enabled,
            [],
            generated.elapsed_sec,
            generated.model_used,
            _failure_metadata(generated.failure),
            generated.failure,
        )
    else:
        queries, metadata, failure = _query_array(
            generated.text, query=query, count=settings.max_questions, max_chars=500
        )
        result = QueryListOutcome(
            settings.enabled, queries, generated.elapsed_sec, generated.model_used, metadata, failure
        )
    if settings.heuristic_enabled and not result.queries and not result.parse_metadata["ok"]:
        fallback = _heuristic(query, settings=settings, failure=result.failure)
        if fallback.queries:
            return fallback
    return result


def generate_multi_queries(query: str, *, settings: MultiQuerySettings, models: QueryVariantModels) -> QueryListOutcome:
    if not _multi_allowed(query, settings):
        return QueryListOutcome(settings.enabled, [], 0.0, None, _not_run_metadata())
    model = models.multi_query(count=settings.count, temperature=settings.temperature)
    return _multi_result(query, settings, _invoke_text(model, query=query, operation="generate_multi_queries"))


async def generate_multi_queries_async(
    query: str, *, settings: MultiQuerySettings, models: AsyncQueryVariantModels
) -> QueryListOutcome:
    if not _multi_allowed(query, settings):
        return QueryListOutcome(settings.enabled, [], 0.0, None, _not_run_metadata())
    model = models.multi_query(count=settings.count, temperature=settings.temperature)
    return _multi_result(query, settings, await _ainvoke_text(model, query=query, operation="generate_multi_queries"))


def generate_hyde_query(
    query: str, *, retrieval_mode: str, settings: TextQuerySettings, models: QueryVariantModels
) -> TextQueryOutcome:
    if retrieval_mode.lower() == "keyword" or not _text_allowed(query, settings):
        return TextQueryOutcome(settings.enabled, "", 0.0, None)
    model = models.hyde(temperature=settings.temperature)
    return _hyde_result(settings, _invoke_text(model, query=query, operation="generate_hyde_query"))


async def generate_hyde_query_async(
    query: str, *, retrieval_mode: str, settings: TextQuerySettings, models: AsyncQueryVariantModels
) -> TextQueryOutcome:
    if retrieval_mode.lower() == "keyword" or not _text_allowed(query, settings):
        return TextQueryOutcome(settings.enabled, "", 0.0, None)
    model = models.hyde(temperature=settings.temperature)
    return _hyde_result(settings, await _ainvoke_text(model, query=query, operation="generate_hyde_query"))


def generate_step_back_query(
    query: str, *, settings: TextQuerySettings, models: QueryVariantModels
) -> StepBackQueryOutcome:
    if not _text_allowed(query, settings):
        return StepBackQueryOutcome(settings.enabled, "", 0.0, None, _not_run_metadata())
    model = models.step_back(temperature=settings.temperature)
    return _step_back_result(query, settings, _invoke_text(model, query=query, operation="generate_step_back_query"))


async def generate_step_back_query_async(
    query: str, *, settings: TextQuerySettings, models: AsyncQueryVariantModels
) -> StepBackQueryOutcome:
    if not _text_allowed(query, settings):
        return StepBackQueryOutcome(settings.enabled, "", 0.0, None, _not_run_metadata())
    model = models.step_back(temperature=settings.temperature)
    return _step_back_result(
        query, settings, await _ainvoke_text(model, query=query, operation="generate_step_back_query")
    )


def decompose_query(query: str, *, settings: DecompositionSettings, models: QueryVariantModels) -> QueryListOutcome:
    if not _decomposition_allowed(query, settings):
        return QueryListOutcome(settings.enabled, [], 0.0, None, _not_run_metadata())
    if settings.heuristic_enabled and not settings.model_api_key_present:
        return _heuristic(query, settings=settings)
    model = models.decompose(max_questions=settings.max_questions, temperature=settings.temperature)
    return _decomposition_result(query, settings, _invoke_text(model, query=query, operation="decompose_query"))


async def decompose_query_async(
    query: str, *, settings: DecompositionSettings, models: AsyncQueryVariantModels
) -> QueryListOutcome:
    if not _decomposition_allowed(query, settings):
        return QueryListOutcome(settings.enabled, [], 0.0, None, _not_run_metadata())
    if settings.heuristic_enabled and not settings.model_api_key_present:
        return _heuristic(query, settings=settings)
    model = models.decompose(max_questions=settings.max_questions, temperature=settings.temperature)
    return _decomposition_result(query, settings, await _ainvoke_text(model, query=query, operation="decompose_query"))


def expand_model_queries(request: ModelQueryRequest, *, models: QueryVariantModels) -> ModelQueryExpansions:
    started = time.perf_counter()
    settings = request.settings
    multi = generate_multi_queries(request.query, settings=settings.multi_query, models=models)
    hyde = generate_hyde_query(
        request.query, retrieval_mode=request.retrieval_mode, settings=settings.hyde, models=models
    )
    step_back = generate_step_back_query(request.query, settings=settings.step_back, models=models)
    decomposition = decompose_query(request.query, settings=settings.decomposition, models=models)
    return ModelQueryExpansions(multi, hyde, step_back, decomposition, time.perf_counter() - started)


async def expand_model_queries_async(
    request: ModelQueryRequest, *, models: AsyncQueryVariantModels
) -> ModelQueryExpansions:
    started = time.perf_counter()
    settings = request.settings
    multi = await generate_multi_queries_async(request.query, settings=settings.multi_query, models=models)
    hyde = await generate_hyde_query_async(
        request.query, retrieval_mode=request.retrieval_mode, settings=settings.hyde, models=models
    )
    step_back = await generate_step_back_query_async(request.query, settings=settings.step_back, models=models)
    decomposition = await decompose_query_async(request.query, settings=settings.decomposition, models=models)
    return ModelQueryExpansions(multi, hyde, step_back, decomposition, time.perf_counter() - started)
