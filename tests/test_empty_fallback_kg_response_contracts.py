from uuid import UUID

import pytest

from app.rag.kg.api.routes_support.undo import _restored_relation_row_payload
from app.rag.kg.extraction.entity_verifier import EntityCandidate, EntityVerifier
from app.rag.kg.extraction.processor import _collect_event_entities
from app.rag.kg.extraction.relation_processor import CandidateEntity, RelationProcessor
from app.rag.kg.extraction.relation_verifier import RelationCandidate, RelationVerifier
from app.rag.kg.extraction.skill_processor import SkillProcessor


class StructuredClient:
    def __init__(self, payload):
        self.payload = payload

    async def chat_with_schema(self, messages, **kwargs):
        return self.payload


@pytest.mark.asyncio
async def test_entity_verification_keeps_valid_matches_beside_invalid_items():
    verifier = EntityVerifier(StructuredClient({"kept": [{}, {"id": "E1"}]}))

    result = await verifier.verify(text="MimirQ", candidates=[EntityCandidate(cid="E1", name="MimirQ")])

    assert [item["id"] for item in result["kept"]] == ["E1"]


@pytest.mark.asyncio
async def test_entity_verification_keeps_absent_optional_text():
    verifier = EntityVerifier(StructuredClient({"kept": [{"id": "E1"}]}))

    result = await verifier.verify(text="MimirQ", candidates=[EntityCandidate(cid="E1", name="MimirQ")])

    assert result["kept"][0]["description"] is None
    assert result["kept"][0]["evidence_quote"] is None


@pytest.mark.asyncio
async def test_relation_extraction_rejects_a_missing_external_predicate():
    processor = RelationProcessor(StructuredClient({"relations": [{"subject_id": "E1", "object_id": "E2"}]}))

    assert await processor.extract_relations(
        text="MimirQ uses a database",
        candidates=[CandidateEntity(cid="E1", name="MimirQ"), CandidateEntity(cid="E2", name="database")],
    ) == []


@pytest.mark.asyncio
async def test_relation_verification_rejects_an_invalid_candidate_id():
    verifier = RelationVerifier(StructuredClient({"kept": [{"rid": None}]}))

    result = await verifier.verify(
        text="MimirQ uses a database",
        candidates=[RelationCandidate(rid="R1", subject_id="E1", object_id="E2", predicate="uses")],
    )
    assert result == {"kept": []}


@pytest.mark.asyncio
async def test_skill_extraction_rejects_a_missing_external_skill_name():
    processor = SkillProcessor(StructuredClient({"skills": [{"steps": ["copy the file"]}]}))

    assert await processor.extract_skills(text="Copy the file") == []


@pytest.mark.asyncio
async def test_skill_extraction_coerces_a_scalar_step():
    processor = SkillProcessor(StructuredClient({"skills": [{"name": "Copy", "steps": [0]}]}))

    result = await processor.extract_skills(text="Copy the file")
    assert result[0]["steps"] == ["0"]


def test_entity_extraction_rejects_an_invalid_external_role():
    assert _collect_event_entities([{"name": "MimirQ", "role": 0}]) == []


def test_relation_undo_requires_the_recorded_predicate():
    row = {"id": str(UUID(int=1)), "subject_entity_id": str(UUID(int=2)), "object_entity_id": str(UUID(int=3))}

    with pytest.raises(KeyError, match="predicate"):
        _restored_relation_row_payload(row=row, tenant_id=UUID(int=4), source_id=UUID(int=2))
