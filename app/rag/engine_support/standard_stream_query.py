"""Query expansion phases for standard RAG streaming."""

import time
from typing import Any

from app.core.config import settings
from app.rag.core.text import (
    heuristic_decompose_query,
)
from app.rag.engine_support.standard_stream_state import (
    StandardStreamState,
    StreamOperation,
)


async def expand_aliases_dictionary_and_init_kg(runtime: StandardStreamState) -> None:
    # Step 0.5: Query Expansion (Multi-Query / HyDE, optional).
    runtime.data.alias_elapsed = 0.0
    runtime.data.alias_used = False
    runtime.data.alias_meta: dict[str, Any] = {"enabled": False, "used": False}
    runtime.data.alias_queries: list[str] = []

    runtime.data.alias_enabled = runtime.data.enable_query_alias_expansion
    if runtime.data.alias_enabled is None:
        # Default behavior: if a dataset provided aliases, apply them unless explicitly disabled.
        runtime.data.alias_enabled = bool(runtime.data.query_aliases)
    if bool(runtime.data.alias_enabled):
        runtime.data.t0 = time.time()
        runtime.data.alias_queries, runtime.data.alias_meta = runtime.module.generate_alias_queries(
            query=runtime.data.query_for_retrieval,
            aliases=runtime.data.query_aliases,
            max_queries=(
                5 if runtime.data.query_alias_max_queries is None else int(runtime.data.query_alias_max_queries or 0)
            ),
        )
        runtime.data.alias_elapsed = time.time() - runtime.data.t0
        runtime.data.alias_used = bool(runtime.data.alias_queries)

    # Deterministic dictionary expansion (bounded, auditable).
    runtime.data.dict_elapsed = 0.0
    runtime.data.dict_used = False
    runtime.data.dict_meta: dict[str, Any] = {"enabled": False, "used": False}
    runtime.data.dict_expansions: list[dict[str, Any]] = []
    try:
        from app.query.expand import generate_dictionary_expansions, load_base_dictionary_rules

        runtime.data.t0 = time.time()
        runtime.data.dict_expansions, runtime.data.dict_meta = generate_dictionary_expansions(
            query=runtime.data.query_for_retrieval,
            rules=load_base_dictionary_rules(),
            max_expansions_total=5,
            max_expansions_per_rule=1,
        )
        runtime.data.dict_elapsed = time.time() - runtime.data.t0
        runtime.data.dict_used = bool(runtime.data.dict_expansions)
    except Exception as exc:  # noqa: BLE001
        runtime.data.dict_elapsed = 0.0
        runtime.data.dict_used = False
        runtime.data.dict_expansions = []
        runtime.data.dict_meta = {"enabled": False, "used": False, "error": str(exc)[:200]}

    # KG query expansion (entity names, optional).
    #
    # Purpose: provide extra retrieval queries derived from KG entity recall
    # to reduce false negatives, with clear attribution ("kgq").
    runtime.data.kg_result_cached: dict[str, Any] | None = None
    runtime.data.kg_query_expansion_enabled = (
        bool(getattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False))
        if runtime.data.enable_kg_query_expansion is None
        else bool(runtime.data.enable_kg_query_expansion)
    )
    runtime.data.kg_query_expansion_used = False
    runtime.data.kg_query_expansion_elapsed = 0.0
    runtime.data.kg_query_expansion_error: str | None = None
    runtime.data.kg_query_expansion_entities_total = 0
    runtime.data.kg_query_expansion_entities_selected = 0
    runtime.data.kg_query_expansion_queries: list[str] = []
    runtime.data.kg_query_expansion_entity_names: list[str] = []


def _kg_query_expansion_allowed(runtime: StandardStreamState) -> bool:
    has_scope = bool(
        runtime.data.kg_document_ids or runtime.data.kg_dataset_id is not None or runtime.data.kg_dataset_ids
    )
    has_account_scope = bool(
        runtime.data.account_id is not None or (runtime.data.kg_dataset_id is None and not runtime.data.kg_dataset_ids)
    )
    return bool(
        runtime.data.kg_query_expansion_enabled
        and getattr(settings, "KG_ENABLED", False)
        and getattr(settings, "KG_CHAT_ENABLED", False)
        and runtime.data.tenant_id is not None
        and has_scope
        and has_account_scope
    )


def _score_kg_entities(runtime: StandardStreamState) -> None:
    runtime.data.scored = []
    for runtime.data.ent in runtime.data.entities:
        if not isinstance(runtime.data.ent, dict) or runtime.data.exclude_all:
            continue
        runtime.data.etype = str(runtime.data.ent.get("type") or "").strip()
        if runtime.data.etype and runtime.data.etype.casefold() in runtime.data.exclude_fold:
            continue
        runtime.data.name = (runtime.data.ent.get("name") or "").strip()
        if not runtime.data.name:
            continue
        try:
            runtime.data.w = float(runtime.data.ent.get("weight", 0.0) or 0.0)
        except Exception:
            runtime.data.w = 0.0
        if runtime.data.w >= runtime.data.min_weight:
            runtime.data.scored.append((runtime.data.w, runtime.data.name))


def _select_kg_entity_names(runtime: StandardStreamState) -> None:
    runtime.data.scored.sort(key=lambda item: (-item[0], item[1]))
    runtime.data.seen_names = set()
    runtime.data.base_folded = runtime.data.query_for_retrieval.casefold()
    runtime.data.selected_names = []
    for _weight, name in runtime.data.scored:
        key = name.casefold() if name.isascii() else name
        if key in runtime.data.seen_names:
            continue
        runtime.data.seen_names.add(key)
        if key and key in runtime.data.base_folded:
            continue
        runtime.data.selected_names.append(name)
        if runtime.data.max_entities > 0 and len(runtime.data.selected_names) >= runtime.data.max_entities:
            break


def _build_kg_expansion_queries(runtime: StandardStreamState) -> None:
    for name in runtime.data.kg_query_expansion_entity_names:
        query = f"{runtime.data.query_for_retrieval} {name}".strip()
        if len(query) > 500:
            query = query[:500] + "..."
        runtime.data.kg_query_expansion_queries.append(query)
        if runtime.data.max_queries > 0 and len(runtime.data.kg_query_expansion_queries) >= runtime.data.max_queries:
            break


async def expand_kg_queries(runtime: StandardStreamState) -> None:
    try:
        (
            runtime.data.kg_document_ids,
            runtime.data.kg_dataset_id,
            runtime.data.kg_dataset_ids,
        ) = runtime.module._resolve_kg_scope(
            {
                "document_ids": runtime.data.document_ids,
                "dataset_id": runtime.data.dataset_id,
                "dataset_ids": runtime.data.dataset_ids,
            }
        )
        if not _kg_query_expansion_allowed(runtime):
            return
        runtime.data.t0 = time.time()
        runtime.data.kg_kwargs = {
            "query": runtime.data.query_for_retrieval,
            "tenant_id": runtime.data.tenant_id,
            "document_ids": runtime.data.kg_document_ids or None,
            "dataset_id": runtime.data.kg_dataset_id,
            "account_id": runtime.data.account_id,
        }
        if runtime.data.kg_dataset_ids:
            runtime.data.kg_kwargs["dataset_ids"] = runtime.data.kg_dataset_ids
        runtime.data.kg_result_cached = await runtime.module.kg_search(**runtime.data.kg_kwargs)
        runtime.data.kg_query_expansion_elapsed = time.time() - runtime.data.t0
        entities = (runtime.data.kg_result_cached or {}).get("entities") or []
        runtime.data.entities = entities if isinstance(entities, list) else []
        runtime.data.kg_query_expansion_entities_total = len(runtime.data.entities)
        runtime.data.max_entities = max(0, int(getattr(settings, "RAG_KG_QUERY_EXPANSION_MAX_ENTITIES", 5) or 5))
        runtime.data.max_queries = max(0, int(getattr(settings, "RAG_KG_QUERY_EXPANSION_MAX_QUERIES", 5) or 5))
        runtime.data.min_weight = float(getattr(settings, "RAG_KG_QUERY_EXPANSION_MIN_ENTITY_WEIGHT", 0.15) or 0.15)
        runtime.data.exclude_types = runtime.module.parse_csv(
            str(getattr(settings, "RAG_KG_QUERY_EXPANSION_EXCLUDE_ENTITY_TYPES", "") or "")
        )
        runtime.data.exclude_all = "*" in runtime.data.exclude_types
        runtime.data.exclude_fold = {
            item.casefold() for item in runtime.data.exclude_types if str(item or "").strip() and item != "*"
        }
        _score_kg_entities(runtime)
        _select_kg_entity_names(runtime)
        runtime.data.kg_query_expansion_entities_selected = len(runtime.data.selected_names)
        limit = runtime.data.max_queries or len(runtime.data.selected_names)
        runtime.data.kg_query_expansion_entity_names = runtime.data.selected_names[:limit]
        _build_kg_expansion_queries(runtime)
        runtime.data.kg_query_expansion_used = bool(runtime.data.kg_query_expansion_queries)
    except Exception as exc:  # noqa: BLE001
        runtime.data.kg_query_expansion_used = False
        runtime.data.kg_query_expansion_queries = []
        runtime.data.kg_query_expansion_entity_names = []
        runtime.data.kg_query_expansion_error = str(exc)[:200]


async def expand_generated_queries(runtime: StandardStreamState) -> None:

    runtime.data.multi_query_elapsed = 0.0
    runtime.data.multi_query_used = False
    runtime.data.multi_query_model_used = None
    runtime.data.multi_query_parse_meta: dict[str, Any] = {"ok": False, "method": None, "error": None}
    runtime.data.multi_queries: list[str] = []

    runtime.data.mq_enabled = (
        bool(settings.ENABLE_MULTI_QUERY)
        if runtime.data.enable_multi_query is None
        else bool(runtime.data.enable_multi_query)
    )
    runtime.data.mq_n = (
        settings.MULTI_QUERY_COUNT
        if runtime.data.multi_query_count is None
        else int(runtime.data.multi_query_count or 0)
    )
    runtime.data.mq_temp = (
        settings.MULTI_QUERY_TEMPERATURE
        if runtime.data.multi_query_temperature is None
        else float(runtime.data.multi_query_temperature or 0.0)
    )
    runtime.data.mq_max_chars = (
        settings.MULTI_QUERY_MAX_CHARS
        if runtime.data.multi_query_max_chars is None
        else int(runtime.data.multi_query_max_chars or 0)
    )

    runtime.data.mq_cap = max(0, int(getattr(settings, "MULTI_QUERY_COUNT_CAP", 8) or 8))
    runtime.data.mq_n = max(0, min(int(runtime.data.mq_n or 0), int(runtime.data.mq_cap)))
    runtime.data.mq_temp = min(2.0, max(0.0, float(runtime.data.mq_temp or 0.0)))
    runtime.data.mq_max_chars = max(0, int(runtime.data.mq_max_chars or 0))

    (
        runtime.data.multi_queries,
        runtime.data.multi_query_elapsed,
        runtime.data.multi_query_model_used,
        runtime.data.multi_query_parse_meta,
    ) = await runtime.engine._generate_multi_queries(
        query=runtime.data.query_for_retrieval,
        llm=runtime.data.llm,
        enabled=bool(runtime.data.mq_enabled),
        count=int(runtime.data.mq_n or 0),
        temperature=float(runtime.data.mq_temp or 0.0),
        max_chars=int(runtime.data.mq_max_chars or 0),
    )

    runtime.data.multi_query_used = bool(runtime.data.multi_queries)

    runtime.data.hyde_used = False
    runtime.data.hyde_elapsed = 0.0
    runtime.data.hyde_model_used = None
    runtime.data.hyde_text = ""
    runtime.data.hyde_max_chars = max(0, int(settings.HYDE_MAX_CHARS or 0))
    runtime.data.retrieval_mode_norm = (runtime.data.mode_used or "hybrid").lower()
    runtime.data.hyde_enabled = (
        bool(settings.ENABLE_HYDE) if runtime.data.enable_hyde is None else bool(runtime.data.enable_hyde)
    )
    if (
        runtime.data.hyde_enabled
        and runtime.data.retrieval_mode_norm not in ("keyword",)
        and runtime.data.hyde_max_chars > 0
        and len(runtime.data.query_for_retrieval) <= runtime.data.hyde_max_chars
    ):
        runtime.data.hyde_llm = runtime.engine.models.get("fast") or runtime.data.llm
        runtime.data.hyde_model_used = getattr(runtime.data.hyde_llm, "model_name", None) or getattr(
            runtime.data.hyde_llm, "model", None
        )
        try:
            runtime.data.hyde_chain = (
                runtime.engine.hyde_prompt
                | runtime.data.hyde_llm.bind(temperature=settings.HYDE_TEMPERATURE)
                | runtime.module.StrOutputParser()
            )
            runtime.data.hyde_start = time.time()
            runtime.data.hyde_text = await runtime.data.hyde_chain.ainvoke({"query": runtime.data.query_for_retrieval})
            runtime.data.hyde_elapsed = time.time() - runtime.data.hyde_start
            runtime.data.hyde_text = (runtime.data.hyde_text or "").strip()
            runtime.data.out_max = max(0, int(settings.HYDE_OUTPUT_MAX_CHARS or 0))
            if runtime.data.out_max and len(runtime.data.hyde_text) > runtime.data.out_max:
                runtime.data.hyde_text = runtime.data.hyde_text[: runtime.data.out_max] + "..."
            runtime.data.hyde_used = bool(runtime.data.hyde_text)
        except Exception:  # noqa: BLE001
            runtime.data.hyde_text = ""
            runtime.data.hyde_elapsed = 0.0
            runtime.data.hyde_used = False

    runtime.data.step_back_enabled = bool(getattr(settings, "ENABLE_STEP_BACK_QUERY", False))
    runtime.data.step_back_elapsed = 0.0
    runtime.data.step_back_used = False
    runtime.data.step_back_model_used = None
    runtime.data.step_back_parse_meta: dict[str, Any] = {"ok": False, "method": None, "error": None}
    runtime.data.step_back_query = ""
    runtime.data.step_back_max_chars = max(0, int(getattr(settings, "STEP_BACK_MAX_CHARS", 0) or 0))
    runtime.data.step_back_temp = min(2.0, max(0.0, float(getattr(settings, "STEP_BACK_TEMPERATURE", 0.2) or 0.0)))
    runtime.data.step_back_output_max = max(0, int(getattr(settings, "STEP_BACK_OUTPUT_MAX_CHARS", 0) or 0))
    if (
        runtime.data.step_back_enabled
        and runtime.data.step_back_max_chars > 0
        and len(runtime.data.query_for_retrieval) <= runtime.data.step_back_max_chars
    ):
        runtime.data.sb_llm = runtime.engine.models.get("fast") or runtime.data.llm
        runtime.data.step_back_model_used = getattr(runtime.data.sb_llm, "model_name", None) or getattr(
            runtime.data.sb_llm, "model", None
        )
        try:
            runtime.data.sb_chain = (
                runtime.engine.step_back_prompt
                | runtime.data.sb_llm.bind(temperature=runtime.data.step_back_temp)
                | runtime.module.StrOutputParser()
            )
            runtime.data.sb_start = time.time()
            runtime.data.sb_raw = await runtime.data.sb_chain.ainvoke({"query": runtime.data.query_for_retrieval})
            runtime.data.step_back_elapsed = time.time() - runtime.data.sb_start
            runtime.data.step_back_query = (runtime.data.sb_raw or "").strip().strip('"').strip()
            if (
                runtime.data.step_back_output_max > 0
                and len(runtime.data.step_back_query) > runtime.data.step_back_output_max
            ):
                runtime.data.step_back_query = runtime.data.step_back_query[: runtime.data.step_back_output_max] + "..."
            if runtime.data.step_back_query and runtime.data.step_back_query != runtime.data.query_for_retrieval:
                runtime.data.step_back_parse_meta = {"ok": True, "method": "text", "error": None}
            else:
                runtime.data.step_back_query = ""
                runtime.data.step_back_parse_meta = {"ok": False, "method": "text", "error": "empty_or_duplicate"}
        except Exception as exc:  # noqa: BLE001
            runtime.data.step_back_query = ""
            runtime.data.step_back_elapsed = 0.0
            runtime.data.step_back_parse_meta = {"ok": False, "method": None, "error": str(exc)[:200]}
    runtime.data.step_back_used = bool(runtime.data.step_back_query)

    runtime.data.decompose_elapsed = 0.0
    runtime.data.decompose_used = False
    runtime.data.decompose_model_used = None
    runtime.data.decompose_parse_meta: dict[str, Any] = {"ok": False, "method": None, "error": None}
    runtime.data.sub_questions: list[str] = []

    runtime.data.dq_n = max(0, min(int(settings.QUERY_DECOMPOSITION_MAX_SUBQUESTIONS or 0), 8))
    runtime.data.dq_min_chars = max(0, int(settings.QUERY_DECOMPOSITION_MIN_CHARS or 0))
    runtime.data.dq_max_chars = max(0, int(settings.QUERY_DECOMPOSITION_MAX_CHARS or 0))
    runtime.data.dq_enabled = (
        bool(settings.ENABLE_QUERY_DECOMPOSITION)
        if runtime.data.enable_query_decomposition is None
        else bool(runtime.data.enable_query_decomposition)
    )


def _decomposition_allowed(runtime: StandardStreamState) -> bool:
    query_length = len(runtime.data.query_for_retrieval)
    return bool(
        runtime.data.dq_enabled
        and runtime.data.dq_n > 0
        and query_length >= runtime.data.dq_min_chars
        and (runtime.data.dq_max_chars <= 0 or query_length <= runtime.data.dq_max_chars)
    )


def _apply_heuristic_decomposition(runtime: StandardStreamState) -> None:
    runtime.data.sub_questions = heuristic_decompose_query(
        runtime.data.query_for_retrieval,
        max_subquestions=runtime.data.dq_n,
    )
    if runtime.data.sub_questions:
        runtime.data.decompose_model_used = None
        runtime.data.decompose_elapsed = 0.0
        runtime.data.decompose_parse_meta = {"ok": True, "method": "heuristic", "error": None}


def _normalize_decomposed_questions(runtime: StandardStreamState) -> None:
    runtime.data.seen = set()
    for item in runtime.data.dq_data:
        if not isinstance(item, str):
            continue
        query = (item or "").strip().strip('"').strip()
        if not query or query == runtime.data.query_for_retrieval or query in runtime.data.seen:
            continue
        if len(query) > 500:
            query = query[:500] + "..."
        runtime.data.seen.add(query)
        runtime.data.sub_questions.append(query)
        if len(runtime.data.sub_questions) >= runtime.data.dq_n:
            break


async def _invoke_query_decomposition(runtime: StandardStreamState) -> None:
    runtime.data.dq_llm = runtime.engine.models.get("fast") or runtime.data.llm
    runtime.data.decompose_model_used = getattr(runtime.data.dq_llm, "model_name", None) or getattr(
        runtime.data.dq_llm, "model", None
    )
    try:
        runtime.data.dq_chain = (
            runtime.engine.decompose_prompt
            | runtime.data.dq_llm.bind(temperature=settings.QUERY_DECOMPOSITION_TEMPERATURE)
            | runtime.module.StrOutputParser()
        )
        runtime.data.dq_start = time.time()
        runtime.data.dq_raw = await runtime.data.dq_chain.ainvoke(
            {"query": runtime.data.query_for_retrieval, "n": runtime.data.dq_n}
        )
        runtime.data.decompose_elapsed = time.time() - runtime.data.dq_start
        runtime.data.dq_data, runtime.data.decompose_parse_meta = runtime.module.parse_json_from_text(
            runtime.data.dq_raw, expected="array"
        )
        if isinstance(runtime.data.dq_data, list):
            _normalize_decomposed_questions(runtime)
    except Exception as exc:  # noqa: BLE001
        runtime.data.decompose_elapsed = 0.0
        runtime.data.decompose_parse_meta = {"ok": False, "method": None, "error": str(exc)[:200]}
        runtime.data.sub_questions = []


async def decompose_query(runtime: StandardStreamState) -> None:
    if not _decomposition_allowed(runtime):
        return
    runtime.data.heuristic_fallback_enabled = bool(
        getattr(settings, "QUERY_DECOMPOSITION_HEURISTIC_FALLBACK_ENABLED", True)
    )
    runtime.data.llm_api_key = str(getattr(settings, "LLM_API_KEY", "") or "").strip()
    if runtime.data.heuristic_fallback_enabled and not runtime.data.llm_api_key:
        _apply_heuristic_decomposition(runtime)
        return
    await _invoke_query_decomposition(runtime)
    if (
        runtime.data.heuristic_fallback_enabled
        and not runtime.data.sub_questions
        and not runtime.data.decompose_parse_meta.get("ok")
    ):
        _apply_heuristic_decomposition(runtime)


async def configure_corrective_retrieval(runtime: StandardStreamState) -> None:

    runtime.data.decompose_used = bool(runtime.data.sub_questions)

    runtime.data.corrective_enabled = bool(getattr(settings, "RAG_CORRECTIVE_ENABLED", False))
    runtime.data.corrective_max_attempts = max(1, min(int(getattr(settings, "RAG_CORRECTIVE_MAX_ATTEMPTS", 2) or 2), 3))
    runtime.data.corrective_min_faithfulness = float(
        getattr(settings, "RAG_CORRECTIVE_MIN_FAITHFULNESS_SCORE", 0.75) or 0.75
    )
    runtime.data.corrective_second_profile = (
        str(getattr(settings, "RAG_CORRECTIVE_SECOND_PASS_PROFILE", "recall50") or "recall50").strip().lower()
        or "recall50"
    )
    if runtime.data.corrective_second_profile not in {
        "recall20",
        "recall50",
        "coverage80",
        "expanded",
        "hierarchy_recall20",
        "hierarchy_recall20_expand",
    }:
        runtime.data.corrective_second_profile = "recall50"
    runtime.data.corrective_second_enable_mq = bool(
        getattr(settings, "RAG_CORRECTIVE_SECOND_PASS_ENABLE_MULTI_QUERY", True)
    )
    runtime.data.corrective_second_mq_count = max(
        0,
        min(
            int(getattr(settings, "RAG_CORRECTIVE_SECOND_PASS_MULTI_QUERY_COUNT", 5) or 5),
            int(getattr(settings, "MULTI_QUERY_COUNT_CAP", 8) or 8),
        ),
    )
    runtime.data.corrective_reason_codes: list[str] = []
    runtime.data.corrective_attempts: list[dict[str, Any]] = []
    runtime.data.corrective_used = False
    runtime.data.corrective_attempt_count = 1


QUERY_OPERATIONS = (
    StreamOperation(expand_aliases_dictionary_and_init_kg, streams=False),
    StreamOperation(expand_kg_queries, streams=False),
    StreamOperation(expand_generated_queries, streams=False),
    StreamOperation(decompose_query, streams=False),
    StreamOperation(configure_corrective_retrieval, streams=False),
)

__all__ = ["QUERY_OPERATIONS"]
