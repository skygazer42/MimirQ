from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    def commit(self) -> None:
        return None

    def refresh(self, obj) -> None:  # noqa: ANN001
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.uuid4()


def _override_get_current_account_id() -> str:
    return "test-account"


def _build_client(monkeypatch):  # noqa: ANN001
    from app.api.v1.pipeline import auto_annotations
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tenant_id, _account_id: None, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/pipeline/auto-annotations")(auto_annotations)
    return TestClient(app)


def test_pipeline_auto_annotations_returns_document_focus_by_default(monkeypatch):  # noqa: ANN001
    client = _build_client(monkeypatch)

    text = (
        "MimirQ 项目由星海智能有限公司建设，联系人 zhangsan@example.com，"
        "手机号 13800138000。核心能力包括知识库检索、数据治理和入库质量分析，"
        "建议后续重点完善入库流程。"
    )
    res = client.post(
        "/api/v1/pipeline/auto-annotations",
        json={
            "text": text,
            "enable_keywords": True,
            "enable_entities": True,
            "max_annotations": 20,
            "keyword_top_k": 5,
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["text_chars"] == len(text)
    assert body["truncated"] is False
    items = body["annotations"]
    assert isinstance(items, list)
    assert items

    by_type = {item["type"] for item in items}
    assert {"keyword", "custom"}.issubset(by_type)

    for item in items:
        assert text[item["start"] : item["end"]] == item["text"]
        assert item["confidence"] >= 0
        assert item["source"] in {"cpu", "keyword", "regex_entity", "rule_focus", "llm"}

    assert any(item["label"] in {"文档重点", "动作项", "关键结论"} for item in items)
    assert any("数据治理" in item["text"] or "知识库检索" in item["text"] for item in items)
    assert not any(item["text"] == "zhangsan@example.com" for item in items)
    assert not any(item["text"] == "13800138000" for item in items)
    assert body["keyword_provider"] == "simple"
    assert body["strategy"] in {"llm", "rules", "hybrid"}
    assert any(tag["type"] == "topic" and tag["value"] in {"数据治理", "知识库检索"} for tag in body["document_tags"])
    assert not any(item["type"] == "keyword" and item["text"] in {"联系人", "手机号", "zhangsan", "example", "com"} for item in items)


def test_pipeline_auto_annotations_uses_llm_focus_when_available(monkeypatch):  # noqa: ANN001
    import app.api.v1.pipeline as pipeline_module
    from app.rag.preprocessing.llm_tagger import LLMDocumentTag, LLMSpanAnnotation, LLMTaggingResult

    async def _fake_extract_llm_tags(*_args, **_kwargs):  # noqa: ANN202
        return LLMTaggingResult(
            summary="围绕数据治理策略和入库流程优化。",
            document_tags=[
                LLMDocumentTag(type="topic", value="数据治理", label="主题", confidence=0.9),
                LLMDocumentTag(type="category", value="入库流程", label="分类", confidence=0.88),
            ],
            span_annotations=[
                LLMSpanAnnotation(text="数据治理", type="keyword", label="主题关键词", confidence=0.92),
                LLMSpanAnnotation(text="完善入库流程", type="custom", label="动作项", confidence=0.88),
            ],
        )

    monkeypatch.setattr(pipeline_module, "extract_llm_tags", _fake_extract_llm_tags, raising=True)
    client = _build_client(monkeypatch)

    text = "本文讨论数据治理策略，并建议完善入库流程。"
    res = client.post(
        "/api/v1/pipeline/auto-annotations",
            json={"text": text, "providers": ["llm"], "enable_llm": True, "max_annotations": 10},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["strategy"] in {"llm", "hybrid"}
    assert body["summary"] == "围绕数据治理策略和入库流程优化。"
    assert ("topic", "数据治理") in {(item["type"], item["value"]) for item in body["document_tags"]}
    assert "llm" in body["providers_used"]
    items = body["annotations"]
    assert any(item["text"] == "数据治理" and item["label"] == "主题关键词" and item["source"] == "llm" for item in items)
    assert any(item["text"] == "完善入库流程" and item["label"] == "动作项" and item["source"] == "llm" for item in items)


def test_pipeline_auto_annotations_uses_cpu_provider_without_llm(monkeypatch):  # noqa: ANN001
    client = _build_client(monkeypatch)

    text = (
        "MimirQ 文档治理方案：核心能力包括知识库检索、数据治理和入库质量分析，"
        "建议后续重点完善入库流程。联系人 zhangsan@example.com。"
    )
    res = client.post(
        "/api/v1/pipeline/auto-annotations",
        json={
            "text": text,
            "providers": ["cpu"],
            "enable_llm": False,
            "enable_llm_topics": False,
            "max_annotations": 20,
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["providers_used"] == ["cpu"]
    assert body["strategy"] == "rules"
    tags = {(tag["type"], tag["value"], tag["source"]) for tag in body["document_tags"]}
    assert ("topic", "知识库检索", "cpu") in tags
    assert ("category", "入库流程", "cpu") in tags
    assert ("doc_type", "治理方案", "cpu") in tags
    assert ("sensitivity", "restricted", "cpu") in tags

    items = body["annotations"]
    assert any(item["text"] == "知识库检索" and item["source"] == "cpu" for item in items)
    assert any(item["text"] == "完善入库流程" and item["label"] == "动作项" for item in items)


def test_pipeline_auto_annotations_can_run_compliance_sensitive_detectors(monkeypatch):  # noqa: ANN001
    client = _build_client(monkeypatch)

    res = client.post(
        "/api/v1/pipeline/auto-annotations",
        json={
            "text": "联系人 zhangsan@example.com，项目是星海智能有限公司。",
            "mode": "compliance",
            "enable_keywords": False,
            "enable_entities": False,
            "enable_sensitive": True,
            "max_annotations": 10,
        },
    )

    assert res.status_code == 200, res.text
    items = res.json()["annotations"]
    assert items
    assert {item["type"] for item in items} == {"sensitive"}
    assert {item["label"] for item in items} == {"email"}
