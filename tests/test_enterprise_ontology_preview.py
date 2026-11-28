from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.rag.kg.enterprise_ontology.definition import load_ontology_definition
from app.rag.kg.enterprise_ontology.preview import ChunkPreview, _literal_identity, preview_ontology_extraction

SOURCE = "工单 WO-01 归属设备 E-102。另有一台相同名称的设备。"
MODEL = """
schema_version: 1
ontology: maintenance
object_types:
  equipment:
    label: 设备
    key: [id]
    properties: {id: string}
  work_order:
    label: 工单
    key: [id]
    properties: {id: string}
relations:
  order_for_equipment: {from: work_order, to: equipment, cardinality: many_to_one}
"""


def test_literal_identity_accepts_a_typed_letter_code_without_treating_plain_labels_as_ids():
    source = "已核对产线 LINE-A，同时记录产线 STAGING。"
    types = {"production_line": "产线"}

    identity = _literal_identity(source, "LINE-A", types)

    assert identity is not None
    type_id, evidence = identity
    assert type_id == "production_line"
    assert source[evidence.start_char : evidence.end_char] == evidence.quote == "产线 LINE-A"
    assert _literal_identity(source, "STAGING", types) is None


class ScriptedClient:
    async def chat_with_schema(self, messages, **kwargs):
        properties = kwargs["response_schema"]["properties"]
        if "events" in properties:
            return {
                "events": [
                    {
                        "title": "工单归属",
                        "summary": SOURCE,
                        "evidence_quote": SOURCE,
                        "entities": [
                            {"name": "WO-01", "type": "work_order", "evidence_quote": "工单WO-01"},
                            {"name": "E-102", "type": "设备", "evidence_quote": "设备 E-102"},
                            {"name": "同名设备", "type": "equipment", "evidence_quote": "相同名称的设备"},
                        ],
                    }
                ]
            }
        if "attributes" in properties:
            return {
                "attributes": [
                    {"entity_id": "E1", "field": "id", "value": "WO-01", "quote": "工单 WO-01"},
                    {"entity_id": "E2", "field": "id", "value": "E-102", "quote": "设备 E-102"},
                ],
                "metadata": [],
            }
        return {
            "relations": [
                {"subject_id": "E1", "object_id": "E2", "predicate": "order_for_equipment", "evidence_quote": SOURCE},
                {"subject_id": "E2", "object_id": "E1", "predicate": "order_for_equipment", "evidence_quote": SOURCE},
                {"subject_id": "E1", "object_id": "E2", "predicate": "unknown", "evidence_quote": SOURCE},
                {"subject_id": "E1", "object_id": "E2", "predicate": "order_for_equipment", "evidence_quote": "编造"},
            ]
        }


@pytest.mark.asyncio
async def test_preview_reuses_extraction_and_checks_types_and_source_evidence():
    chunk = SimpleNamespace(
        id=UUID(int=1),
        document_id=UUID(int=2),
        page_number=3,
        content=SOURCE,
    )
    [preview] = await preview_ontology_extraction(
        load_ontology_definition(MODEL, format="yaml"), [chunk], llm_client=ScriptedClient()
    )
    assert preview.chunk_id == chunk.id and preview.page == 3
    assert [item.name for item in preview.entities] == ["WO-01", "E-102"]
    assert [item.business_key for item in preview.entities] == [{"id": "WO-01"}, {"id": "E-102"}]
    assert len(preview.relations) == 1
    evidence = preview.relations[0].evidence
    assert SOURCE[evidence.start_char : evidence.end_char] == evidence.quote
    assert {item.reason for item in preview.rejected} == {
        "missing_entity_evidence",
        "relation_endpoint_type_mismatch",
        "unknown_relation",
        "missing_relation_evidence",
    }


@pytest.mark.asyncio
async def test_pdf_layout_tags_stay_out_of_model_prompts_and_evidence_offsets_remain_exact():
    tag = "@@1\t72.0\t251.6\t60.5\t74.9##"
    prefix = f"安装台账{tag}\n"
    chunk = SimpleNamespace(id=UUID(int=1), document_id=UUID(int=2), page_number=1, content=prefix + SOURCE)

    class Client(ScriptedClient):
        async def chat_with_schema(self, messages, **kwargs):
            assert all(tag not in message.content for message in messages)
            return await super().chat_with_schema(messages, **kwargs)

    [preview] = await preview_ontology_extraction(
        load_ontology_definition(MODEL, format="yaml"), [chunk], llm_client=Client()
    )
    [relation] = preview.relations
    evidence = relation.evidence
    assert evidence.start_char == len(prefix)
    assert evidence.quote == chunk.content[evidence.start_char : evidence.end_char] == SOURCE


@pytest.mark.asyncio
async def test_preview_keeps_source_identifiers_when_attribute_extraction_omits_them():
    class Client(ScriptedClient):
        async def chat_with_schema(self, messages, **kwargs):
            if "attributes" in kwargs["response_schema"]["properties"]:
                return {"attributes": [], "metadata": []}
            return await super().chat_with_schema(messages, **kwargs)

    chunk = SimpleNamespace(id=UUID(int=1), document_id=UUID(int=2), page_number=1, content=SOURCE)
    [preview] = await preview_ontology_extraction(
        load_ontology_definition(MODEL, format="yaml"), [chunk], llm_client=Client()
    )

    assert [entity.business_key for entity in preview.entities] == [{"id": "WO-01"}, {"id": "E-102"}]
    for entity in preview.entities:
        [key] = entity.attributes["id"]
        span = key.evidence
        assert SOURCE[span.start_char : span.end_char] == span.quote
        assert span.quote.endswith(entity.name)


@pytest.mark.asyncio
@pytest.mark.parametrize("display, expected", [("泵 E-102", {"id": "E-102"}), ("泵 E-102 和 E-103", None)])
@pytest.mark.parametrize("model_copies_name", [False, True])
async def test_preview_recovers_one_identifier_from_a_grounded_display_name(display, expected, model_copies_name):
    source = f"工单 WO-01 关联设备{display}。"

    class Client:
        async def chat_with_schema(self, messages, **kwargs):
            fields = kwargs["response_schema"]["properties"]
            if "events" in fields:
                return {
                    "events": [
                        {
                            "title": "维修",
                            "summary": source,
                            "evidence_quote": source,
                            "entities": [{"name": display, "type": "equipment", "evidence_quote": "设备" + display}],
                        }
                    ]
                }
            if "attributes" in fields:
                if model_copies_name and expected is not None:
                    return {
                        "attributes": [{"entity_id": "E1", "field": "id", "value": display, "quote": "设备" + display}],
                        "metadata": [],
                    }
                return {"attributes": [], "metadata": []}
            return {"relations": []}

    chunk = SimpleNamespace(id=UUID(int=1), document_id=UUID(int=2), page_number=1, content=source)
    [preview] = await preview_ontology_extraction(
        load_ontology_definition(MODEL, format="yaml"), [chunk], llm_client=Client()
    )
    [entity] = preview.entities
    assert entity.business_key == expected
    if expected is not None:
        [key] = entity.attributes["id"]
        assert source[key.evidence.start_char : key.evidence.end_char] == key.evidence.quote == "设备" + display


class OntologyFieldsClient:
    async def chat_with_schema(self, messages, **kwargs):
        properties = kwargs["response_schema"]["properties"]
        first = "设备空压机 E-102 的压力为 42，状态为 OPEN"
        second = "设备空压机 E-103 的压力为 7，状态为 INVALID"
        if "events" in properties:
            return {
                "events": [
                    {
                        "title": "设备状态",
                        "summary": first,
                        "entities": [
                            {"name": "空压机", "type": "equipment", "evidence_quote": first},
                            {"name": "空压机", "type": "equipment", "evidence_quote": second},
                            {"name": "空压机", "type": "equipment", "evidence_quote": "另有空压机待登记"},
                        ],
                    },
                ]
            }
        return {
            "attributes": [
                {"entity_id": "E1", "field": "id", "value": "E-102", "quote": first},
                {"entity_id": "E1", "field": "pressure", "value": "42", "quote": first},
                {"entity_id": "E1", "field": "status", "value": "OPEN", "quote": first},
                {"entity_id": "E2", "field": "id", "value": "E-103", "quote": second},
                {"entity_id": "E2", "field": "status", "value": "INVALID", "quote": second},
                {"entity_id": "E3", "field": "id", "value": "E-102", "quote": first},
            ],
            "metadata": [
                {"field": "effective_at", "value": "2026年11月1日", "quote": "2026年11月1日生效"},
                {"field": "effective_at", "value": "2026-11-03", "quote": "2026-11-03生效"},
                {"field": "effective_at", "value": "2026-11-05", "quote": "2026-11-03生效"},
            ],
        }


@pytest.mark.asyncio
async def test_explicit_key_uses_entity_evidence_when_a_pdf_quote_crosses_layout_markers():
    mention = "设备 E-102 安装在产线 LINE-A。"
    repeated = "设备 E-102 的显示名为水泵。"
    chunk = SimpleNamespace(
        id=UUID(int=1),
        document_id=UUID(int=2),
        page_number=1,
        content=mention + "@@1 48.0 212.2 58.4 72.9##\n\n" + repeated,
    )

    class Client:
        async def chat_with_schema(self, *_args, **kwargs):
            if "events" in kwargs["response_schema"]["properties"]:
                return {
                    "events": [
                        {
                            "title": "设备台账",
                            "summary": mention,
                            "evidence_quote": mention,
                            "entities": [
                                {"name": "设备 E-102", "type": "equipment", "evidence_quote": mention},
                            ],
                        }
                    ]
                }
            return {
                "attributes": [
                    {"entity_id": "E1", "field": "id", "value": "E-102", "quote": mention + repeated},
                    {"entity_id": "E1", "field": "id", "value": "LINE-A", "quote": mention + repeated},
                ],
                "metadata": [],
            }

    [preview] = await preview_ontology_extraction(
        load_ontology_definition(MODEL, format="yaml"), [chunk], llm_client=Client()
    )
    [equipment] = preview.entities
    assert equipment.business_key == {"id": "E-102"}
    [key] = equipment.attributes["id"]
    assert (key.evidence.quote, key.evidence.start_char, key.evidence.end_char) == (mention, 0, len(mention))


@pytest.mark.asyncio
async def test_preview_preserves_same_name_mentions_and_grounded_typed_values():
    model = """
schema_version: 1
ontology: maintenance
object_types:
  equipment:
    key: [id]
    properties:
      id: string
      pressure: integer
      status: {type: string, required: true, enum: [OPEN, CLOSED]}
document_metadata:
  effective_at: {type: date, label: 生效日期}
"""
    text = (
        "设备空压机 E-102 的压力为 42，状态为 OPEN。设备空压机 E-103 的压力为 7，状态为 INVALID。"
        "另有空压机待登记。正文称2026年11月1日生效，补充条款称2026-11-03生效。"
    )
    chunk = SimpleNamespace(id=UUID(int=1), document_id=UUID(int=2), page_number=3, content=text)
    [preview] = await preview_ontology_extraction(
        load_ontology_definition(model, format="yaml"), [chunk], llm_client=OntologyFieldsClient()
    )
    [first, second, third] = preview.entities
    assert first.business_key == {"id": "E-102"}
    assert first.attributes["pressure"][0].value == 42
    assert second.business_key == {"id": "E-103"}
    assert third.business_key is None and third.identity_status == "unresolved"
    assert {issue.reason for issue in preview.rejected} >= {
        "invalid_attribute_value",
        "missing_required_attribute",
        "missing_attribute_evidence",
        "missing_metadata_evidence",
    }
    restored = ChunkPreview.model_validate(preview.model_dump(mode="json"))
    assert [candidate.value for candidate in restored.metadata_candidates] == [date(2026, 11, 1), date(2026, 11, 3)]
    for candidate in restored.metadata_candidates:
        span = candidate.evidence
        assert text[span.start_char : span.end_char] == span.quote
    assert restored.extracted_at is not None


def test_metadata_review_keeps_conflicting_candidates_and_uses_confirmed_boundaries():
    from app.rag.kg.enterprise_ontology.metadata import (
        DocumentMetadataReview,
        apply_metadata_review,
        document_applicability,
        document_metadata_candidate,
        read_document_metadata,
    )
    from app.rag.kg.extraction.evidence import EvidenceSpan

    definition = load_ontology_definition(MODEL + "\ndocument_metadata:\n  effective_at: {type: date}\n", format="yaml")
    preview = ChunkPreview(document_id=UUID(int=2), chunk_id=UUID(int=1), page=3)
    for offset, raw in enumerate(("2026-11-01", "2026-11-03")):
        preview.metadata_candidates.append(
            document_metadata_candidate(
                definition.document_metadata["effective_at"],
                field="effective_at",
                chunk_id=preview.chunk_id,
                page=preview.page,
                raw=raw,
                evidence=EvidenceSpan(raw, offset, offset + len(raw), "quote"),
            )
        )
    fields = read_document_metadata(definition, [preview])
    assert fields["effective_at"].state == "conflict"
    observed = datetime(2026, 11, 1, tzinfo=UTC)
    assert document_applicability(fields, observed) == "pending"

    chosen = preview.metadata_candidates[0]
    apply_metadata_review(
        definition,
        [preview],
        DocumentMetadataReview(field="effective_at", candidate_ids=[chosen.id]),
        reviewed_by="reviewer",
        reviewed_at=observed,
    )
    fields = read_document_metadata(definition, [preview])
    assert fields["effective_at"].state == "confirmed"
    assert len(fields["effective_at"].candidates) == 2
    assert fields["effective_at"].confirmed[0].confirmed_by == "reviewer"
    assert document_applicability(fields, observed) == "applicable"
    assert document_applicability(fields, datetime(2026, 10, 31, tzinfo=UTC)) == "outside_window"


def test_confirmed_expiry_alone_does_not_confirm_when_a_document_became_effective():
    from app.rag.kg.enterprise_ontology.metadata import (
        DocumentMetadataReview,
        apply_metadata_review,
        document_applicability,
        document_metadata_candidate,
        read_document_metadata,
    )
    from app.rag.kg.extraction.evidence import EvidenceSpan

    definition = load_ontology_definition(MODEL + "\ndocument_metadata:\n  expires_at: {type: date}\n", format="yaml")
    preview = ChunkPreview(document_id=UUID(int=2), chunk_id=UUID(int=1), page=3)
    expiry = "2026-12-01"
    candidate = document_metadata_candidate(
        definition.document_metadata["expires_at"],
        field="expires_at",
        chunk_id=preview.chunk_id,
        page=preview.page,
        raw=expiry,
        evidence=EvidenceSpan(expiry, 0, len(expiry), "quote"),
    )
    preview.metadata_candidates.append(candidate)
    observed = datetime(2026, 11, 1, tzinfo=UTC)
    apply_metadata_review(
        definition,
        [preview],
        DocumentMetadataReview(field="expires_at", candidate_ids=[candidate.id]),
        reviewed_by="reviewer",
        reviewed_at=observed,
    )
    fields = read_document_metadata(definition, [preview])

    assert document_applicability(fields, observed) == "pending"
    assert document_applicability(fields, datetime(2026, 12, 1, tzinfo=UTC)) == "outside_window"


@pytest.mark.asyncio
async def test_preview_rejects_all_conflicting_forward_cardinality_claims():
    text = "工单 WO-01 归属设备 E-102。工单 WO-01 同时归属设备 E-103。"

    class ConflictingRelationsClient:
        async def chat_with_schema(self, messages, **kwargs):
            properties = kwargs["response_schema"]["properties"]
            if "events" in properties:
                return {
                    "events": [
                        {
                            "title": "工单归属",
                            "summary": text,
                            "entities": [
                                {"name": "WO-01", "type": "work_order", "evidence_quote": "工单 WO-01"},
                                {"name": "E-102", "type": "equipment", "evidence_quote": "设备 E-102"},
                                {"name": "E-103", "type": "equipment", "evidence_quote": "设备 E-103"},
                            ],
                        }
                    ]
                }
            if "attributes" in properties:
                return {"attributes": [], "metadata": []}
            return {
                "relations": [
                    {
                        "subject_id": "E1",
                        "object_id": "E2",
                        "predicate": "order_for_equipment",
                        "evidence_quote": "工单 WO-01 归属设备 E-102",
                    },
                    {
                        "subject_id": "E1",
                        "object_id": "E3",
                        "predicate": "order_for_equipment",
                        "evidence_quote": "工单 WO-01 同时归属设备 E-103",
                    },
                ]
            }

    chunk = SimpleNamespace(id=UUID(int=1), document_id=UUID(int=2), page_number=3, content=text)
    [preview] = await preview_ontology_extraction(
        load_ontology_definition(MODEL, format="yaml"), [chunk], llm_client=ConflictingRelationsClient()
    )
    assert not preview.relations
    conflicts = [issue for issue in preview.rejected if issue.reason == "relation_cardinality_violation"]
    assert len(conflicts) == 2
    assert all(text[issue.evidence.start_char : issue.evidence.end_char] == issue.evidence.quote for issue in conflicts)
