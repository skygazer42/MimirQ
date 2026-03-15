from __future__ import annotations

import asyncio

import pytest


class _FakeLLM:
    def __init__(self, payload):  # noqa: ANN001
        self._payload = payload

    async def chat_with_schema(self, *_a, **_k):  # noqa: ANN001
        await asyncio.sleep(0)  # Sonar S7503
        return self._payload


@pytest.mark.asyncio
async def test_relation_processor_filters_candidates_and_allowlists_predicates() -> None:
    from app.rag.kg.extraction.relation_processor import CandidateEntity, RelationProcessor

    llm = _FakeLLM(
        {
            "relations": [
                {"subject_id": "E1", "predicate": "works_with", "object_id": "E2", "confidence": 0.8},
                {"subject_id": "E1", "predicate": "Located In", "object_id": "E2", "confidence": 1.2},
                {"subject_id": "E9", "predicate": "works_with", "object_id": "E2", "confidence": 0.2},
                {"subject_id": "E1", "predicate": "works_with", "object_id": "E1", "confidence": 0.2},
            ]
        }
    )

    proc = RelationProcessor(llm, allowed_predicates=["works_with"])
    candidates = [
        CandidateEntity(cid="E1", name="Alice", type="Person"),
        CandidateEntity(cid="E2", name="Bob", type="Person"),
    ]

    out = await proc.extract_relations(text="Alice works with Bob.", candidates=candidates, max_relations=10)

    assert out[0]["subject_id"] == "E1"
    assert out[0]["object_id"] == "E2"
    assert out[0]["predicate"] == "works_with"
    assert out[0]["predicate_raw"] is None
    assert out[0]["confidence"] == pytest.approx(0.8)

    # "Located In" is not in allowlist => predicate becomes "unknown" and raw preserved; confidence clamped to 1.0
    assert out[1]["predicate"] == "unknown"
    assert out[1]["predicate_raw"] == "Located In"
    assert out[1]["confidence"] == pytest.approx(1.0)

    # Invalid candidate ids and self-loops are dropped.
    assert len(out) == 2


@pytest.mark.asyncio
async def test_relation_processor_maps_predicate_synonyms_to_allowlist() -> None:
    from app.rag.kg.extraction.relation_processor import CandidateEntity, RelationProcessor

    llm = _FakeLLM(
        {
            "relations": [
                {"subject_id": "E1", "predicate": "works at", "object_id": "E2", "confidence": 0.9},
            ]
        }
    )

    proc = RelationProcessor(llm, allowed_predicates=["works_for"])
    candidates = [
        CandidateEntity(cid="E1", name="Alice", type="Person"),
        CandidateEntity(cid="E2", name="ACME", type="Organization"),
    ]

    out = await proc.extract_relations(text="Alice works at ACME.", candidates=candidates, max_relations=10)
    assert len(out) == 1
    assert out[0]["predicate"] == "works_for"
    assert out[0]["predicate_raw"] == "works at"


def test_normalize_predicate_snake_cases_text() -> None:
    from app.rag.kg.extraction.relation_processor import normalize_predicate

    assert normalize_predicate("Works With") == "works_with"
    assert normalize_predicate("located-in") == "located_in"
    assert normalize_predicate("works at") == "works_for"
    assert normalize_predicate("employed_by") == "works_for"
    assert normalize_predicate("  ") == "unknown"
