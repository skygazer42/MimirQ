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

    assert by_key["judge_faithfulness_ragas_zh"].category == "llm_judge"
    assert {"question", "answer", "contexts"}.issubset(set(by_key["judge_faithfulness_ragas_zh"].variables))
    assert "atomic_facts" in by_key["judge_faithfulness_ragas_zh"].content

    assert by_key["testset_generation_ragas_zh"].category == "testset_generation"
    assert {"document_chunk", "n", "existing_questions"}.issubset(
        set(by_key["testset_generation_ragas_zh"].variables)
    )
    assert "qa_pairs" in by_key["testset_generation_ragas_zh"].content


def test_builtin_prompt_sync_endpoint_creates_and_updates_system_templates(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_prompt_templates_endpoints import _build_client

    tenant_id = uuid.uuid4()
    client, db = _build_client(monkeypatch=monkeypatch, tenant_id=tenant_id)

    first = client.post("/api/v1/prompt-templates/builtins/sync")
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["created"] == 4
    assert first_body["updated"] == 0
    assert set(first_body["template_keys"]) == {
        "rag_answer_claude_xml_zh",
        "kg_extract_graphrag_zh",
        "judge_faithfulness_ragas_zh",
        "testset_generation_ragas_zh",
    }

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
    assert second_body["updated"] == 4
    assert len(db.items) == 4
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
