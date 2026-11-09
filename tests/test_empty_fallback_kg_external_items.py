from uuid import UUID

import pytest

from app.models.document import DocumentChunk
from app.rag.kg.extraction.processor import EventProcessor, _collect_event_entities
from app.rag.kg.extraction.entity_verifier import EntityCandidate, EntityVerifier
from app.rag.kg.extraction.relation_processor import CandidateEntity, RelationProcessor
from app.rag.kg.extraction.relation_verifier import RelationCandidate, RelationVerifier
from app.rag.kg.extraction.skill_processor import SkillProcessor, _coerce_str_list


class StructuredClient:
    def __init__(self, payload):
        self.payload = payload

    async def chat_with_schema(self, messages, **kwargs):
        return self.payload


@pytest.mark.parametrize("value", [0, False, 3])
def test_skill_text_coercion_preserves_scalar_siblings(value):
    assert _coerce_str_list([None, value, "valid"]) == [str(value), "valid"]


@pytest.mark.asyncio
async def test_skill_extraction_keeps_valid_siblings_of_malformed_items():
    class Client:
        async def chat_with_schema(self, messages, **kwargs):
            return {
                "skills": [
                    {},
                    {"name": None},
                    {"name": []},
                    {"name": "valid", "category": None, "summary": None, "evidence_quote": None, "steps": [0, False]},
                ]
            }

    skills = await SkillProcessor(Client()).extract_skills(text="valid evidence")
    assert len(skills) == 1
    assert skills[0]["name"] == "valid"
    assert skills[0]["steps"] == ["0", "False"]
    assert skills[0]["summary"] is None


@pytest.mark.asyncio
async def test_event_extraction_keeps_valid_siblings_of_malformed_items():
    class Client:
        async def chat_with_schema(self, messages, **kwargs):
            return {
                "events": [
                    {},
                    {"title": None, "summary": "bad"},
                    {"title": "bad", "summary": False},
                    {"title": "valid", "summary": "evidence", "schema_version": None, "event_schema": None},
                ]
            }

    events = await EventProcessor(Client()).extract_from_sections(
        [DocumentChunk(id=UUID(int=1), content="valid evidence", doc_metadata={})], batch_index=0
    )
    assert [event["title"] for event in events] == ["valid"]
    assert events[0]["schema_version"] is None


def test_event_entity_parser_keeps_valid_siblings_and_absent_optional_text():
    entities = _collect_event_entities(
        [
            {"name": None},
            {"name": False},
            {"name": []},
            {"name": "valid", "description": None, "role": None, "evidence_quote": None},
        ]
    )
    assert [entity["name"] for entity in entities] == ["valid"]
    assert entities[0]["description"] is None
    assert entities[0]["evidence_quote"] is None


@pytest.mark.asyncio
async def test_entity_verification_preserves_nullable_text_and_valid_siblings():
    result = await EntityVerifier(
        StructuredClient(
            {
                "kept": [
                    {"id": "E1", "description": None},
                    {"id": "E2", "description": []},
                    {"id": "E3", "description": "valid", "evidence_quote": None},
                ]
            }
        )
    ).verify(text="evidence", candidates=[EntityCandidate(cid=f"E{i}", name=f"entity{i}") for i in range(1, 4)])
    assert [item["id"] for item in result["kept"]] == ["E1", "E3"]
    assert result["kept"][0]["description"] is None


@pytest.mark.asyncio
async def test_entity_alias_verification_keeps_valid_siblings():
    result = await EntityVerifier(
        StructuredClient(
            {
                "aliases": [
                    {"alias_id": "E1", "canonical_id": "E2", "evidence_quote": []},
                    {"alias_id": False, "canonical_id": "E2"},
                    {"alias_id": "E2", "canonical_id": "E3", "evidence_quote": None},
                ]
            }
        )
    ).verify(text="evidence", candidates=[EntityCandidate(cid=f"E{i}", name=f"entity{i}") for i in range(1, 4)])
    assert [(item["alias_id"], item["canonical_id"]) for item in result["aliases"]] == [("E2", "E3")]


@pytest.mark.asyncio
async def test_relation_extraction_keeps_valid_siblings():
    relations = await RelationProcessor(
        StructuredClient(
            {
                "relations": [
                    {"subject_id": "E1", "object_id": "E2"},
                    {"subject_id": False, "object_id": "E2", "predicate": "uses"},
                    {"subject_id": "E1", "object_id": "E2", "predicate": "uses", "evidence_quote": None},
                ]
            }
        )
    ).extract_relations(
        text="entity1 uses entity2", candidates=[CandidateEntity(cid=f"E{i}", name=f"entity{i}") for i in (1, 2)]
    )
    assert [item["predicate"] for item in relations] == ["uses"]
    assert relations[0]["evidence_quote"] is None


@pytest.mark.asyncio
async def test_relation_verification_keeps_valid_siblings():
    result = await RelationVerifier(
        StructuredClient(
            {"kept": [{"rid": None}, {"rid": "R1", "predicate": []}, {"rid": "R2", "predicate": "uses", "evidence_quote": None}]}
        )
    ).verify(
        text="entity1 uses entity2",
        candidates=[RelationCandidate(rid=f"R{i}", subject_id="E1", object_id="E2", predicate="uses") for i in (1, 2)],
    )
    assert [item["rid"] for item in result["kept"]] == ["R2"]
    assert result["kept"][0]["evidence_quote"] is None
