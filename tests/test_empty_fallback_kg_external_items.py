from types import SimpleNamespace
from uuid import UUID

import pytest

from app.rag.kg.extraction.entity_verifier import EntityCandidate, EntityVerifier
from app.rag.kg.extraction.processor import EventProcessor, _collect_event_entities
from app.rag.kg.extraction.relation_processor import CandidateEntity, RelationProcessor
from app.rag.kg.extraction.relation_verifier import RelationCandidate, RelationVerifier
from app.rag.kg.extraction.skill_processor import SkillProcessor, _coerce_str_list
from app.rag.llm.models import LLMMessage, LLMRole


class StructuredClient:
    def __init__(self, payload):
        self.payload = payload
        self.messages: list[LLMMessage] = []

    async def chat_with_schema(self, messages: list[LLMMessage], **kwargs):
        self.messages = messages
        return self.payload


@pytest.mark.parametrize("value", [0, False, 3])
def test_skill_text_coercion_preserves_scalar_siblings(value):
    assert _coerce_str_list([None, value, "valid"]) == [str(value), "valid"]


@pytest.mark.asyncio
async def test_skill_extraction_preserves_optional_text_and_rejects_malformed_siblings():
    skill = {"name": "valid", "category": None, "summary": None, "evidence_quote": None, "steps": [0, False]}
    client = StructuredClient({"skills": [skill]})
    processor = SkillProcessor(client)
    skills = await processor.extract_skills(text="valid evidence")
    assert len(skills) == 1
    assert skills[0]["name"] == "valid"
    assert skills[0]["steps"] == ["0", "False"]
    assert skills[0]["summary"] is None
    client.payload = {"skills": [skill, {"name": []}]}
    with pytest.raises(ValueError, match="Extracted skill name must be a string"):
        await processor.extract_skills(text="valid evidence")


@pytest.mark.asyncio
async def test_builtin_event_extraction_sends_chunks_as_source_data():
    client = StructuredClient({"events": []})
    sections = [
        SimpleNamespace(id=UUID(int=1), content="The access window is 30 days.", page_number=4),
        SimpleNamespace(id=UUID(int=2), content="This section covers contractor accounts.", page_number=5),
    ]

    await EventProcessor(client).extract_from_sections(sections, batch_index=0)

    assert [message.role for message in client.messages] == [LLMRole.SYSTEM, LLMRole.USER]
    instructions, source = client.messages
    assert all(section.content not in instructions.content for section in sections)
    assert source.content == (
        "[Target p4] The access window is 30 days.\n\n[Context 1 p5] This section covers contractor accounts."
    )


@pytest.mark.asyncio
async def test_event_extraction_preserves_optional_schema_and_rejects_malformed_siblings():
    event = {"title": "valid", "summary": "evidence", "schema_version": None, "event_schema": None}
    client = StructuredClient({"events": [event]})
    processor = EventProcessor(client)
    sections = [SimpleNamespace(id=UUID(int=1), content="valid evidence")]
    events = await processor.extract_from_sections(sections, batch_index=0)
    assert [event["title"] for event in events] == ["valid"]
    assert events[0]["schema_version"] is None
    client.payload = {"events": [event, {"title": "bad", "summary": False}]}
    with pytest.raises(ValueError, match="Extracted event title and summary must be strings"):
        await processor.extract_from_sections(sections, batch_index=0)
    client.payload = {"events": [event, {**event, "evidence_quote": []}]}
    with pytest.raises(ValueError, match="Extracted event evidence quote must be a string or null"):
        await processor.extract_from_sections(sections, batch_index=0)


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
async def test_entity_verification_preserves_nullable_text_and_rejects_nontext_fields():
    kept = [{"id": "E1", "description": None}, {"id": "E3", "description": "valid", "evidence_quote": None}]
    client = StructuredClient({"kept": kept})
    verifier = EntityVerifier(client)
    candidates = [EntityCandidate(cid=f"E{i}", name=f"entity{i}") for i in range(1, 4)]
    result = await verifier.verify(text="evidence", candidates=candidates)
    assert [item["id"] for item in result["kept"]] == ["E1", "E3"]
    assert result["kept"][0]["description"] is None
    client.payload = {"kept": [*kept, {"id": "E2", "description": []}]}
    with pytest.raises(ValueError, match="Verified entity text fields must be strings or null"):
        await verifier.verify(text="evidence", candidates=candidates)


@pytest.mark.asyncio
async def test_entity_alias_verification_preserves_nullable_quote_and_rejects_invalid_evidence():
    alias = {"alias_id": "E2", "canonical_id": "E3", "evidence_quote": None}
    client = StructuredClient({"kept": [], "aliases": [alias]})
    verifier = EntityVerifier(client)
    candidates = [EntityCandidate(cid=f"E{i}", name=f"entity{i}") for i in range(1, 4)]
    result = await verifier.verify(text="evidence", candidates=candidates)
    assert [(item["alias_id"], item["canonical_id"]) for item in result["aliases"]] == [("E2", "E3")]
    assert result["aliases"][0]["evidence_quote"] is None
    client.payload = {"kept": [], "aliases": [alias, {**alias, "alias_id": "E1", "evidence_quote": []}]}
    with pytest.raises(ValueError, match="Verified alias evidence must be text or null"):
        await verifier.verify(text="evidence", candidates=candidates)


@pytest.mark.asyncio
async def test_relation_extraction_preserves_nullable_quote_and_rejects_nontext_endpoints():
    relation = {"subject_id": "E1", "object_id": "E2", "predicate": "uses", "evidence_quote": None}
    client = StructuredClient({"relations": [relation]})
    processor = RelationProcessor(client)
    candidates = [CandidateEntity(cid=f"E{i}", name=f"entity{i}") for i in (1, 2)]
    relations = await processor.extract_relations(text="entity1 uses entity2", candidates=candidates)
    assert [item["predicate"] for item in relations] == ["uses"]
    assert relations[0]["evidence_quote"] is None
    client.payload = {"relations": [relation, {**relation, "subject_id": False}]}
    with pytest.raises(ValueError, match="Extracted relation endpoints and predicate must be strings"):
        await processor.extract_relations(text="entity1 uses entity2", candidates=candidates)


@pytest.mark.asyncio
async def test_relation_verification_preserves_nullable_quote_and_rejects_nontext_predicates():
    relation = {"rid": "R2", "predicate": "uses", "evidence_quote": None}
    client = StructuredClient({"kept": [relation]})
    verifier = RelationVerifier(client)
    candidates = [RelationCandidate(rid=f"R{i}", subject_id="E1", object_id="E2", predicate="uses") for i in (1, 2)]
    result = await verifier.verify(text="entity1 uses entity2", candidates=candidates)
    assert [item["rid"] for item in result["kept"]] == ["R2"]
    assert result["kept"][0]["evidence_quote"] is None
    client.payload = {"kept": [relation, {"rid": "R1", "predicate": []}]}
    with pytest.raises(ValueError, match="Verified predicate and evidence must be text or null"):
        await verifier.verify(text="entity1 uses entity2", candidates=candidates)
