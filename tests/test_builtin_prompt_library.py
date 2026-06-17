from __future__ import annotations

import uuid

import pytest


def test_builtin_prompt_library_exposes_core_operational_templates() -> None:
    from app.rag.llm.prompts.builtin_library import list_builtin_prompt_templates

    builtins = list_builtin_prompt_templates()
    keys = {template.template_key for template in builtins}

    assert {
        "rag_answer_claude_xml_zh",
        "kg_extract_graphrag_zh",
        "kg_extract_event_schema_zh",
        "judge_faithfulness_ragas_zh",
        "testset_generation_ragas_zh",
    }.issubset(keys)
    assert len(keys) == len(builtins)

    by_key = {template.template_key: template for template in builtins}
    assert by_key["rag_answer_claude_xml_zh"].category == "rag_answer"
    assert {"context", "history", "question", "format_instructions"}.issubset(
        set(by_key["rag_answer_claude_xml_zh"].variables)
    )
    assert "<context>" in by_key["rag_answer_claude_xml_zh"].content

    assert by_key["kg_extract_graphrag_zh"].category == "kg_extract"
    assert {"context", "max_events", "max_entities"}.issubset(set(by_key["kg_extract_graphrag_zh"].variables))
    assert '"events"' in by_key["kg_extract_graphrag_zh"].content

    event_schema = by_key["kg_extract_event_schema_zh"]
    assert event_schema.category == "kg_extract"
    assert {"context", "max_events", "max_entities"}.issubset(set(event_schema.variables))
    assert "event_schema" in event_schema.content
    assert '"role"' in event_schema.content
    assert '"weight"' in event_schema.content
    assert "source_span" in event_schema.content
    assert "evidence_quote" in event_schema.content
    assert "Hyper-Extract" in event_schema.content
    assert "Apache-2.0" in event_schema.content

    assert by_key["judge_faithfulness_ragas_zh"].category == "llm_judge"
    assert {"question", "answer", "contexts"}.issubset(set(by_key["judge_faithfulness_ragas_zh"].variables))
    assert "atomic_facts" in by_key["judge_faithfulness_ragas_zh"].content

    assert by_key["testset_generation_ragas_zh"].category == "testset_generation"
    assert {"document_chunk", "n", "existing_questions"}.issubset(
        set(by_key["testset_generation_ragas_zh"].variables)
    )
    assert "qa_pairs" in by_key["testset_generation_ragas_zh"].content


def test_builtin_prompt_templates_inherit_formal_plan_rules() -> None:
    from app.rag.llm.prompts.builtin_library import list_builtin_prompt_templates

    by_key = {template.template_key: template for template in list_builtin_prompt_templates()}

    for template in by_key.values():
        haystack = " ".join(
            [
                template.name,
                template.description,
                template.content,
                " ".join(template.tags),
            ]
        ).casefold()
        assert "smoke" not in haystack
        assert template.version >= 2
        assert {"formal", "prompt-as-code", "plans-derived"}.issubset(set(template.tags))

    answer = by_key["rag_answer_claude_xml_zh"].content
    assert "<instructions>" in answer
    assert "<documents>" in answer
    assert "<citation_policy>" in answer
    assert "<refusal_policy>" in answer
    assert "<conflict_policy>" in answer
    assert '<source idx="' in answer

    kg = by_key["kg_extract_graphrag_zh"].content
    assert "Few-shot" in kg
    assert "gleaning" in kg.lower()
    assert "evidence_quote" in kg
    assert '"required"' in kg

    event_schema_kg = by_key["kg_extract_event_schema_zh"].content
    assert "event-as-container" in event_schema_kg
    assert "schema_version" in event_schema_kg
    assert "participants" in event_schema_kg
    assert "不得把共现实体当作强关系" in event_schema_kg
    assert "实体先抽取，事件/关系后抽取" in event_schema_kg
    assert "每个参与者必须来自已抽取实体列表" in event_schema_kg

    judge = by_key["judge_faithfulness_ragas_zh"].content
    assert "atomic_facts" in judge
    assert "supported | contradicted | not_found" in judge
    assert "仅输出 JSON" in judge

    testgen = by_key["testset_generation_ragas_zh"].content
    assert "时态陷阱" in testgen
    assert "术语变体" in testgen
    assert "refusal" in testgen


def test_builtin_prompt_library_keeps_common_vertical_templates_without_task_specific_terms() -> None:
    from app.rag.llm.prompts.builtin_library import list_builtin_prompt_templates

    builtins = list_builtin_prompt_templates()
    keys = {template.template_key for template in builtins}
    joined = "\n".join(
        "\n".join(
            [
                template.template_key,
                template.name,
                template.description,
                template.category,
                template.content,
                " ".join(template.tags),
            ]
        )
        for template in builtins
    )

    assert {
        "vertical_finance_annual_report_zh",
        "vertical_legal_clause_compare_zh",
        "vertical_legal_redline_zh",
        "vertical_government_redhead_zh",
    }.issubset(keys)
    for forbidden in (
        "常州",
        "经开区",
        "天宁区",
        "新北区",
        "公积金",
        "不动产",
        "一件事一次办",
        "12345QA",
        "苏服办",
    ):
        assert forbidden not in joined


def test_builtin_prompt_templates_compile_with_langchain_f_string_format() -> None:
    from langchain_core.prompts import PromptTemplate

    from app.rag.llm.prompts.builtin_library import list_builtin_prompt_templates

    placeholders = {
        "context": "Alpha rollout uses the blue flag.",
        "history": "",
        "question": "What flag does Alpha use?",
        "format_instructions": "Answer in text.",
        "max_events": 3,
        "max_entities": 5,
        "contexts": "[C1] Alpha rollout uses the blue flag.",
        "answer": "Alpha uses the blue flag.",
        "document_chunk": "Alpha rollout uses the blue flag.",
        "document_summary": "A document about Alpha rollout and blue flag usage.",
        "n": 2,
        "existing_questions": "",
        "draft_answer": "Alpha uses the blue flag.",
        "retrieved_chunks": "[C1] Alpha rollout uses the blue flag.",
        "documents": "[D1] Alpha rollout uses the blue flag.",
        "entities": "Alpha rollout; blue flag",
        "candidate_entities": "Alpha rollout; blue flag",
        "candidate_relations": "Alpha rollout -> uses -> blue flag",
        "ontology": "Event, Concept",
        "path_triples": "(Alpha rollout, uses, blue flag)",
        "chunk": "Alpha rollout uses the blue flag.",
        "ground_truth": "Alpha rollout uses the blue flag.",
        "citations": "[C1]",
        "clause_a": "Alpha rollout uses the blue flag.",
        "clause_b": "Alpha rollout does not use the red flag.",
        "document": "Alpha rollout uses the blue flag.",
        "redlines": "No redlines.",
    }

    for template in list_builtin_prompt_templates():
        prompt = PromptTemplate(template=template.content, input_variables=template.variables)
        rendered = prompt.format(**{name: placeholders[name] for name in template.variables})
        assert "Invalid format specifier" not in rendered
        assert "<prompt_provenance>" in rendered

    testset_prompt = next(
        item
        for item in list_builtin_prompt_templates()
        if item.template_key == "testset_generation_ragas_zh"
    )
    rendered_testset = PromptTemplate(
        template=testset_prompt.content,
        input_variables=testset_prompt.variables,
    ).format(
        document_chunk=placeholders["document_chunk"],
        n=placeholders["n"],
        existing_questions=placeholders["existing_questions"],
    )
    assert '"qa_pairs": {' in rendered_testset


@pytest.mark.asyncio
async def test_event_processor_template_vars_support_builtin_kg_aliases() -> None:
    from types import SimpleNamespace

    from app.rag.kg.extraction.processor import EventProcessor
    from tests.helpers.async_utils import yield_control

    captured: dict[str, str] = {}

    class _FakeLLM:
        async def chat_with_schema(self, messages, response_schema, temperature=0.2):  # noqa: ANN001
            await yield_control()
            captured["prompt"] = messages[0].content
            return {"events": []}

    processor = EventProcessor(
        llm_client=_FakeLLM(),
        prompt_template="Extract {max_events} events and {max_entities} entities from:\n{context}",
    )

    await processor.extract_from_sections(
        [SimpleNamespace(id="chunk-1", content="Alpha uses the blue flag.", page_number=None)],
        1,
        max_events=3,
        max_entities_per_event=7,
    )

    assert "Extract 3 events and 7 entities" in captured["prompt"]
    assert "{max_entities}" not in captured["prompt"]


@pytest.mark.asyncio
async def test_event_processor_preserves_event_schema_entity_fields() -> None:
    from types import SimpleNamespace

    from app.rag.kg.extraction.processor import EventProcessor
    from tests.helpers.async_utils import yield_control

    class _FakeLLM:
        async def chat_with_schema(self, messages, response_schema, temperature=0.2):  # noqa: ANN001
            await yield_control()
            return {
                "events": [
                    {
                        "title": "Project Atlas launch",
                        "summary": "Project Atlas uses Orion billing.",
                        "schema_version": "event-as-container.v1",
                        "event_schema": "event-as-container.v1",
                        "entities": [
                            {
                                "name": "Orion billing",
                                "type": "Product",
                                "role": "dependency",
                                "weight": 0.8,
                                "description": "Billing dependency",
                                "evidence_quote": "uses Orion billing",
                                "source_span": {"source": "target", "start_char": 14, "end_char": 33},
                            }
                        ],
                    }
                ]
            }

    processor = EventProcessor(llm_client=_FakeLLM())
    events = await processor.extract_from_sections(
        [SimpleNamespace(id="chunk-1", content="Project Atlas uses Orion billing.", page_number=None)],
        1,
    )

    assert events[0]["schema_version"] == "event-as-container.v1"
    assert events[0]["event_schema"] == "event-as-container.v1"
    entity = events[0]["entities"][0]
    assert entity["role"] == "dependency"
    assert entity["weight"] == 0.8
    assert entity["evidence_source"] == "target"
    assert entity["evidence_start_char"] == 14
    assert entity["evidence_end_char"] == 33


def test_builtin_prompt_sync_endpoint_creates_and_updates_system_templates(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.llm.prompts.builtin_library import list_builtin_prompt_templates
    from tests.test_prompt_templates_endpoints import _build_client

    tenant_id = uuid.uuid4()
    client, db = _build_client(monkeypatch=monkeypatch, tenant_id=tenant_id)
    builtins = list_builtin_prompt_templates()
    builtin_keys = {template.template_key for template in builtins}

    first = client.post("/api/v1/prompt-templates/builtins/sync")
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["created"] == len(builtins)
    assert first_body["updated"] == 0
    assert set(first_body["template_keys"]) == builtin_keys

    stored = {item.template_key: item for item in db.items}
    assert all(item.tenant_id == tenant_id for item in stored.values())
    assert all(item.is_system is True for item in stored.values())
    assert all(item.is_active is True for item in stored.values())
    assert stored["rag_answer_claude_xml_zh"].variables == [
        "context",
        "history",
        "question",
        "format_instructions",
    ]

    stored["rag_answer_claude_xml_zh"].content = "stale"

    second = client.post("/api/v1/prompt-templates/builtins/sync")
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["created"] == 0
    assert second_body["updated"] == len(builtins)
    assert len(db.items) == len(builtins)
    assert stored["rag_answer_claude_xml_zh"].content != "stale"


def test_builtin_prompt_sync_does_not_overwrite_user_template_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.llm.prompts.builtin_library import list_builtin_prompt_templates
    from tests.test_prompt_templates_endpoints import _build_client, _seed_template

    tenant_id = uuid.uuid4()
    builtin_key = list_builtin_prompt_templates()[0].template_key
    user_template = _seed_template(
        tenant_id=tenant_id,
        name="User-owned template",
        template_key=builtin_key,
        is_system=False,
        is_active=True,
        category="rag_answer",
    )
    user_template.content = "user content"
    client, db = _build_client(monkeypatch=monkeypatch, tenant_id=tenant_id, items=[user_template])

    response = client.post("/api/v1/prompt-templates/builtins/sync")

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == f"Prompt template key already exists as a user template: {builtin_key}"
    assert len(db.items) == 1
    assert db.items[0].content == "user content"
