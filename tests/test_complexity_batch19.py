from __future__ import annotations

import datetime as dt
from uuid import UUID

import pytest
from starlette import status as starlette_status

if not hasattr(dt, "UTC"):
    dt.UTC = dt.timezone.utc
if not hasattr(starlette_status, "HTTP_413_CONTENT_TOO_LARGE"):
    starlette_status.HTTP_413_CONTENT_TOO_LARGE = starlette_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
if not hasattr(starlette_status, "HTTP_422_UNPROCESSABLE_CONTENT"):
    starlette_status.HTTP_422_UNPROCESSABLE_CONTENT = starlette_status.HTTP_422_UNPROCESSABLE_ENTITY

from app.rag.kg.extraction.extractor import (
    _canonicalize_entities_for_chunk,
    _uniform_sample_indices,
)
from app.rag.kg.extraction.parser import EntityValueParser
from app.rag.pipeline_plugins.registry import (
    PipelinePluginEntry,
    _manifest_entries,
    _test_status,
)
from app.rag.preprocessing import tokenization as tokenization_module
from app.rag.preprocessing.tokenization import tokenize_for_bm25
from app.rag.retrieval.planner import (
    DatasetRouteHint,
    plan_dataset_scope,
    retrieval_policy_boost_score,
    retrieval_policy_query_terms,
    retrieval_policy_service_anchor_query_rewrite_terms,
)


def _policy() -> dict[str, object]:
    return {"schema": "mimirq.retrieval_policy.v1"}


def test_retrieval_policy_query_terms_preserves_field_and_mapping_order() -> None:
    policy = {
        **_policy(),
        "query_expansion_fields": ["service", "topic", "service"],
        "query_expansion_values": [
            {"metadata": "intent", "values": ["reset"], "terms": ["password reset", "account recovery"]},
            {"metadata": "service", "values": ["mail"], "terms": ["mail routing"]},
        ],
    }

    terms = retrieval_policy_query_terms(
        policy,
        metadata_layers=[
            {"service": ["mail", "mail"], "topic": "deliverability", "intent": "reset"},
            {"service": "backup", "topic": "ignored"},
        ],
    )

    assert terms == (
        "mail",
        "deliverability",
        "password reset",
        "account recovery",
        "mail routing",
        "backup",
        "ignored",
    )


def test_retrieval_policy_service_anchor_query_rewrite_terms_respects_match_modes_and_dedupes() -> None:
    policy = {
        **_policy(),
        "service_anchor_query_rewrites": [
            {"when_terms": ["smtp", "mail"], "terms": ["outbound queue"], "match": "all"},
            {"when": ["mail"], "rewrite_terms": ["queue health", "Outbound Queue"], "match": "any"},
            {"when_terms": ["dns"], "terms": ["mx record"]},
        ],
    }

    terms = retrieval_policy_service_anchor_query_rewrite_terms(policy, query="Mail SMTP delay")

    assert terms == ("outbound queue", "queue health")


def test_retrieval_policy_boost_score_caps_bonus_after_multiple_matches() -> None:
    policy = {
        **_policy(),
        "boost_fields": [
            {"metadata": "service", "weight": 2, "match": "contains"},
            {"metadata": "component", "weight": 3, "match": "overlap"},
            {"metadata": "slug", "weight": 4, "match": "fuzzy_overlap"},
        ],
    }

    score = retrieval_policy_boost_score(
        policy,
        metadata_layers=[
            {"service": "smtp", "component": "mail-router", "slug": "mailrouterv2"},
        ],
        query="smtp mail router v2 queue",
        base_bonus=0.05,
        max_bonus=0.2,
    )

    assert score == pytest.approx(0.2)


def test_plan_dataset_scope_promotes_replace_routes_to_primary_scope_without_losing_expansion() -> None:
    base_a = UUID(int=1)
    hint_b = UUID(int=2)
    hint_c = UUID(int=3)

    plan = plan_dataset_scope(
        base_dataset_ids=[base_a],
        route_hints=[
            DatasetRouteHint(terms=("billing",), dataset_ids=(hint_b,), mode="replace"),
            DatasetRouteHint(terms=("invoice",), dataset_ids=(hint_c,), mode="append"),
        ],
        query="billing invoice export",
        matched_replace_routes_as_primary_scope=True,
    )

    assert plan.dataset_ids == (hint_b, base_a, hint_c)
    assert plan.primary_dataset_ids == (hint_b,)
    assert plan.expansion_dataset_ids == (base_a, hint_c)
    assert plan.matched_dataset_ids == (hint_b, hint_c)
    assert plan.matched_terms == ("billing", "invoice")


def test_uniform_sample_indices_keeps_endpoints_and_backfills_unique_positions() -> None:
    sampled = _uniform_sample_indices(list(range(7)), 4)

    assert sampled == [0, 2, 4, 6]


def test_canonicalize_entities_for_chunk_splits_parenthetical_aliases_and_keeps_longer_description() -> None:
    entities = [
        {"name": "Large Language Model (LLM)", "type": "Concept", "description": "first"},
        {"name": "Large Language Model", "type": "Concept", "description": "better description"},
    ]

    result = _canonicalize_entities_for_chunk(
        entities,
        chunk_text="Large Language Model (LLM) systems are often called LLM systems.",
        max_entities=5,
        parser=EntityValueParser(),
    )

    assert result == [
        {
            "name": "Large Language Model",
            "normalized_name": "large language model",
            "type": "Concept",
            "description": "better description",
            "role": None,
            "evidence_quote": None,
        },
        {
            "name": "LLM",
            "normalized_name": "llm",
            "type": "Concept",
            "description": "",
            "role": None,
            "evidence_quote": None,
        },
    ]


def test_tokenize_for_bm25_expands_ascii_paths_versions_and_numeric_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tokenization_module.settings, "BM25_TOKENIZE_ASCII_EXPAND_ENABLED", True, raising=False)
    monkeypatch.setattr(
        tokenization_module.settings,
        "BM25_TOKENIZE_NUMERIC_NORMALIZATION_ENABLED",
        True,
        raising=False,
    )

    tokens = tokenize_for_bm25("API/v1.2.3 Release_2026 build 1,024")

    assert tokens == [
        "api/v1.2.3",
        "api",
        "v1.2.3",
        "v1",
        "release_2026",
        "release",
        "2026",
        "build",
        "024",
        "1024",
    ]


def test_manifest_entries_preserves_supported_stage_targets() -> None:
    entries = _manifest_entries(
        {
            "entry": {
                "chunk": "chunk_impl.py:run",
                "kg": "kg_impl:extract",
            }
        }
    )

    assert entries == {
        "chunk": PipelinePluginEntry(stage="chunk", target="chunk_impl.py:run"),
        "kg": PipelinePluginEntry(stage="kg", target="kg_impl:extract"),
    }


@pytest.mark.parametrize(
    ("report", "expected"),
    [
        (
            {
                "plugin_id": "demo",
                "version": "1.0.0",
                "package_hash": "abc",
                "passed": True,
                "stages": {
                    "chunk": {
                        "passed": True,
                        "input_count": 1,
                        "output_count": 1,
                        "metadata_validation": {"ok": True},
                    }
                },
                "golden_draft": {"passed": True},
            },
            (True, "passed"),
        ),
        (
            {
                "plugin_id": "demo",
                "version": "1.0.0",
                "package_hash": "abc",
                "passed": True,
                "stages": {},
                "golden_draft": {"passed": True},
            },
            (False, "missing"),
        ),
    ],
)
def test_test_status_preserves_stage_and_golden_rule_requirements(
    report: dict[str, object],
    expected: tuple[bool, str],
) -> None:
    status = _test_status(
        plugin_id="demo",
        version="1.0.0",
        published=True,
        require_test_report=True,
        package_hash="abc",
        entries={"chunk": PipelinePluginEntry(stage="chunk", target="chunk.py:run")},
        golden_rules={"schema": "mimirq.golden_rules.v1"},
        report=report,
    )

    assert status == expected
