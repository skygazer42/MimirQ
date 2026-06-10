from __future__ import annotations

import logging
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database import get_db


class _DummyDB:
    pass


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


_DEMO_PLUGIN_REF = "plugin:demo-service@1.0.0:chunk"


def _demo_response_hints() -> dict[str, object]:
    return {
        "answer_prefix": "答案要点",
        "source_prefix": "原始证据",
        "structured_labels": ["答案", "事项名称", "问题", "办理地点", "收费情况", "咨询方式", "办理时间", "受理条件"],
        "answer_labels": ["答案"],
        "answer_keywords": ["答案"],
        "answer_highlight_metadata": ["answer_highlights", "answer_key_points", "summary_points"],
        "existing_hint_prefixes": ["答案要点"],
        "anchor_only_chunk_kinds": ["qa_pair", "qa"],
        "anchor_only_markers": ["问题", "检索锚点", "相似问"],
        "groups": [
            {"name": "qa", "required_any_labels": ["答案"], "hint_labels": ["问题", "答案"]},
            {
                "name": "service_item",
                "required_any_labels": ["事项名称", "办理地点"],
                "hint_labels": ["事项名称", "办理地点", "收费情况", "咨询方式", "办理时间", "受理条件"],
                "question_from_query_label": "问题",
                "answer_label": "答案",
                "query_gate": {
                    "content_labels": ["事项名称"],
                    "metadata": ["service_name", "service_aliases", "aliases", "primary_alias"],
                    "min_chars": 4,
                },
            },
        ],
        "enumeration": {
            "enabled": True,
            "intro_terms": ["类型", "类别", "方式", "入口"],
            "query_terms": ["申请", "入口", "类型", "类别", "哪些", "什么", "如何"],
            "max_terms": 4,
            "named_markers": {"1": "方式一", "2": "方式二", "3": "方式三", "4": "方式四"},
            "prefix": "必答要点",
            "message_template": "回答申请/入口/类型类问题时必须保留这些选项名称：{terms}",
            "term_separator": "、",
        },
    }


def _demo_policy(**overrides: object) -> dict[str, object]:
    policy: dict[str, object] = {
        "schema": "mimirq.retrieval_policy.v1",
        "question_intent_terms": ["材料", "证件", "地点", "在哪里", "哪里办理", "办理地点", "渠道", "入口", "方式", "流程", "步骤", "操作", "进度", "查询", "费用", "收费", "电话", "咨询", "条件", "时限"],
        "response_hints": _demo_response_hints(),
    }
    policy.update(overrides)
    return policy


def _patch_demo_policy(
    monkeypatch: pytest.MonkeyPatch,
    dify_api,  # noqa: ANN001
    *,
    plugin_ref: str = _DEMO_PLUGIN_REF,
    **overrides: object,
) -> dict[str, object]:
    policy = _demo_policy(**overrides)
    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: policy if ref == plugin_ref else {},
        raising=True,
    )
    return policy


def test_dify_retrieval_logs_request_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_HIGH_CONFIDENCE_ENABLED",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": "问题：如何查询身份证办理进度？\n答案：下载苏证通 APP 查询。",
                "relevance_score": 1.0,
                "document_name": "城市本级12345QA.txt",
                "metadata": {"question": "如何查询身份证办理进度？"},
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)
    caplog.set_level(logging.INFO, logger=dify_api.logger.name)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers={**_auth(token), "X-Forwarded-For": "10.168.2.251, 127.0.0.1"},
        json={
            "knowledge_id": "city",
            "query": "如何查询身份证办理进度？",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    finished = [
        record
        for record in caplog.records
        if getattr(record, "event", "") == "dify_external_retrieval" and getattr(record, "phase", "") == "finished"
    ]
    assert finished, "Expected Dify retrieval diagnostic log"
    record = finished[-1]
    assert record.client_ip == "10.168.2.251"
    assert record.knowledge_id == "city"
    assert record.query_preview == "如何查询身份证办理进度？"
    assert record.query_hash
    assert record.top_k == 5
    assert record.dataset_count == 1
    assert record.citation_count == 1
    assert record.record_count == 1
    assert record.retrieval_policy_record_count == 0
    assert record.retrieval_policy_boosted_record_count == 0
    assert record.retrieval_policy_boost_field_record_count == 0
    assert record.retrieval_policy_query_expansion_record_count == 0
    assert record.retrieval_policy_rerank_feature_record_count == 0
    assert record.retrieval_policy_anchor_mismatch_record_count == 0
    assert record.retrieval_policy_plugin_refs == []
    assert record.elapsed_ms >= 0
    message = record.getMessage()
    assert "client_ip=10.168.2.251" in message
    assert "knowledge_id=city" in message
    assert "records=1" in message


@pytest.mark.asyncio
async def test_dify_direct_retrieval_uses_reranker_free_overfetch_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api
    import app.api.v1.rag as rag_api

    captured: dict[str, object] = {}

    monkeypatch.setattr(dify_api.settings, "ENABLE_RERANKER", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "RERANKER_PROVIDER", "openai", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_QUERY_EXPANSION_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_MAX_CHUNKS", 3, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_WEIGHT", 0.25, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_MAX_PROMOTED", 2, raising=False)

    async def _fake_retrieve_evidence(**kwargs):  # noqa: ANN003, ANN202
        captured["body"] = kwargs["body"]
        captured["rag_config"] = kwargs["body"].rag_config

        class _Response:
            citations: list[dict[str, object]] = []

        return _Response()

    monkeypatch.setattr(rag_api, "retrieve_evidence", _fake_retrieve_evidence, raising=True)

    await dify_api._retrieve_dataset_citations(
        db=_DummyDB(),
        tenant_id=uuid.uuid4(),
        account_id="system:dify",
        dataset_ids=[uuid.uuid4()],
        query="区域乙在哪里办理企业社会保险登记",
        top_k=5,
        score_threshold=0.0,
    )

    body = captured["body"]
    rag_config = captured["rag_config"]
    assert body.dataset_id is None
    assert len(body.dataset_ids) == 1
    assert rag_config.top_k == 20
    assert rag_config.enable_reranker is False
    assert rag_config.reranker_provider == "none"
    assert rag_config.reranker_top_n == 20
    assert rag_config.lexical_db_hybrid_metadata_exact_fallback_enabled is True
    assert rag_config.metadata_exact_db_fallback_enabled is True
    assert rag_config.enable_kg_query_expansion is True
    assert rag_config.enable_kg_chunk_injection is True
    assert rag_config.kg_chunk_injection_max_chunks == 3
    assert rag_config.enable_kg_chunk_boost is True
    assert rag_config.kg_chunk_boost_weight == pytest.approx(0.25)
    assert rag_config.kg_chunk_boost_max_promoted == 2


@pytest.mark.asyncio
async def test_dify_single_dataset_keeps_dataset_ids_when_kg_assist_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api
    import app.api.v1.rag as rag_api

    captured: dict[str, object] = {}

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_QUERY_EXPANSION_ENABLED", False, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_ENABLED", False, raising=False)

    async def _fake_retrieve_evidence(**kwargs):  # noqa: ANN003, ANN202
        captured["body"] = kwargs["body"]

        class _Response:
            citations: list[dict[str, object]] = []

        return _Response()

    monkeypatch.setattr(rag_api, "retrieve_evidence", _fake_retrieve_evidence, raising=True)

    dataset_id = uuid.uuid4()
    await dify_api._retrieve_dataset_citations(
        db=_DummyDB(),
        tenant_id=uuid.uuid4(),
        account_id="system:dify",
        dataset_ids=[dataset_id],
        query="普通检索",
        top_k=5,
        score_threshold=0.0,
    )

    body = captured["body"]
    assert body.dataset_id is None
    assert body.dataset_ids == [dataset_id]
    assert body.rag_config.enable_kg_query_expansion is False
    assert body.rag_config.enable_kg_chunk_injection is False
    assert body.rag_config.enable_kg_chunk_boost is False


@pytest.mark.asyncio
async def test_dify_direct_retrieval_request_can_override_kg_assist_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api
    import app.api.v1.rag as rag_api

    captured: dict[str, object] = {}

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_QUERY_EXPANSION_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_ENABLED", True, raising=False)

    async def _fake_retrieve_evidence(**kwargs):  # noqa: ANN003, ANN202
        captured["body"] = kwargs["body"]

        class _Response:
            citations: list[dict[str, object]] = []

        return _Response()

    monkeypatch.setattr(rag_api, "retrieve_evidence", _fake_retrieve_evidence, raising=True)

    dataset_id = uuid.uuid4()
    await dify_api._retrieve_dataset_citations(
        db=_DummyDB(),
        tenant_id=uuid.uuid4(),
        account_id="system:dify",
        dataset_ids=[dataset_id],
        query="普通检索",
        top_k=5,
        score_threshold=0.0,
        enable_kg_query_expansion=False,
        enable_kg_chunk_injection=False,
        enable_kg_chunk_boost=False,
    )

    body = captured["body"]
    assert body.dataset_id is None
    assert body.dataset_ids == [dataset_id]
    assert body.rag_config.enable_kg_query_expansion is False
    assert body.rag_config.enable_kg_chunk_injection is False
    assert body.rag_config.enable_kg_chunk_boost is False


@pytest.mark.asyncio
async def test_dify_multi_dataset_scope_keeps_dataset_ids_for_rag(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api
    import app.api.v1.rag as rag_api

    captured: dict[str, object] = {}

    async def _fake_retrieve_evidence(**kwargs):  # noqa: ANN003, ANN202
        captured["body"] = kwargs["body"]

        class _Response:
            citations: list[dict[str, object]] = []

        return _Response()

    monkeypatch.setattr(rag_api, "retrieve_evidence", _fake_retrieve_evidence, raising=True)

    dataset_a = uuid.uuid4()
    dataset_b = uuid.uuid4()
    await dify_api._retrieve_dataset_citations(
        db=_DummyDB(),
        tenant_id=uuid.uuid4(),
        account_id="system:dify",
        dataset_ids=[dataset_a, dataset_b],
        query="跨库检索",
        top_k=5,
        score_threshold=0.0,
    )

    body = captured["body"]
    assert body.dataset_id is None
    assert body.dataset_ids == [dataset_a, dataset_b]


def test_dify_retrieval_uses_rag_path_without_fast_chunk_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_HIGH_CONFIDENCE_ENABLED",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": "问题：如何查询身份证办理进度？\n答案：下载苏证通 APP 查询。",
                "relevance_score": 0.88,
                "document_name": "城市本级12345QA.txt",
                "document_id": str(uuid.uuid4()),
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
            }
        ]

    assert not any("fast_chunk" in name.lower() for name in dir(dify_api))
    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "如何查询身份证办理进度？",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert [record["title"] for record in body["records"]] == ["城市本级12345QA.txt"]


def test_dify_retrieval_request_passes_kg_overrides_to_rag(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        calls.append(kwargs)
        return []

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "如何查询身份证办理进度？",
            "retrieval_setting": {
                "top_k": 5,
                "score_threshold": 0.0,
                "enable_kg_query_expansion": False,
                "enable_kg_chunk_injection": False,
                "enable_kg_chunk_boost": False,
            },
        },
    )

    assert res.status_code == 200, res.text
    assert calls
    assert calls[0]["enable_kg_query_expansion"] is False
    assert calls[0]["enable_kg_chunk_injection"] is False
    assert calls[0]["enable_kg_chunk_boost"] is False


def test_dify_retrieval_maps_knowledge_id_to_multiple_datasets(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_a = uuid.uuid4()
    dataset_b = uuid.uuid4()
    calls: list[tuple[list[uuid.UUID], str, int, float]] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_HIGH_CONFIDENCE_ENABLED",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"sales-all": ["{dataset_a}", "{dataset_b}"]}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        dataset_ids = kwargs["dataset_ids"]
        calls.append((dataset_ids, kwargs["query"], kwargs["top_k"], kwargs["score_threshold"]))
        return [
            {
                "chunk_content": "B top-ranked sales policy chunk",
                "retrieval_score": 0.91,
                "document_name": "sales-b.md",
                "document_id": str(uuid.uuid4()),
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_b),
                "header_path": "Pricing / Exceptions",
            },
            {
                "chunk_content": "A lower-ranked sales policy chunk",
                "relevance_score": 0.42,
                "document_name": "sales-a.md",
                "document_id": str(uuid.uuid4()),
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_a),
                "page_number": 3,
            },
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "sales-all",
            "query": "报价例外条件",
            "retrieval_setting": {"top_k": 2, "score_threshold": 0.35},
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert [call[0] for call in calls] == [[dataset_a, dataset_b]]
    assert all(call[1] == "报价例外条件" for call in calls)
    assert all(call[2] == 20 for call in calls)
    assert all(call[3] == pytest.approx(0.35) for call in calls)
    assert [record["content"] for record in body["records"]] == [
        "B top-ranked sales policy chunk",
        "A lower-ranked sales policy chunk",
    ]
    assert body["records"][0]["score"] == pytest.approx(0.91)
    assert body["records"][0]["title"] == "sales-b.md"
    assert body["records"][0]["metadata"]["dataset_id"] == str(dataset_b)
    assert body["records"][0]["metadata"]["header_path"] == "Pricing / Exceptions"
    assert body["records"][0]["metadata"] is not None


def test_dify_retrieval_caps_top_k_for_external_timeout_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    observed_top_k: list[int] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX", 5, raising=False)

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        observed_top_k.append(kwargs["top_k"])
        return [
            {
                "chunk_content": f"政策命中片段 {idx}",
                "retrieval_score": 1.0 - (idx / 100),
                "document_name": f"policy-{idx}.md",
                "document_id": str(uuid.uuid4()),
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
            }
            for idx in range(10)
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "服务卡在哪里补办",
            "retrieval_setting": {"top_k": 10, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert observed_top_k == [20]
    assert len(body["records"]) == 5


def test_dify_compacts_high_confidence_score_cliff_records(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_HIGH_CONFIDENCE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_TOP_SCORE", 0.8, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_RELATIVE_SCORE_FLOOR", 0.65, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_RECORDS", 1, raising=False)
    records = [
        {
            "content": "事项名称：服务卡补卡\n办理地点：区域甲政务服务中心",
            "score": 0.83,
            "title": "区域甲事项列表.txt",
            "metadata": {"service_name": "服务卡补卡"},
        },
        {
            "content": "事项名称：个体演出经纪人备案\n办理地点：区域甲政务服务中心",
            "score": 0.36,
            "title": "区域甲事项列表.txt",
            "metadata": {"service_name": "个体演出经纪人备案"},
        },
        {
            "content": "事项名称：个体工商户信息确认\n办理地点：区域甲政务服务中心",
            "score": 0.34,
            "title": "区域甲事项列表.txt",
            "metadata": {"service_name": "个体工商户信息确认"},
        },
    ]

    dify_api._sort_records_for_query(records, query="区域甲服务卡补卡在哪里办理")

    compacted = dify_api._compact_records_for_response(records, query="区域甲服务卡补卡在哪里办理", top_k=3)

    assert [item["metadata"]["service_name"] for item in compacted] == ["服务卡补卡"]


def test_dify_compaction_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_HIGH_CONFIDENCE_ENABLED",
        False,
        raising=False,
    )
    records = [
        {"content": "exact", "score": 0.95, "title": "a", "metadata": {"question": "如何查询身份证办理进度？"}},
        {"content": "backup", "score": 0.2, "title": "b", "metadata": {"question": "身份证可以代领吗"}},
    ]

    compacted = dify_api._compact_records_for_response(records, query="如何查询身份证办理进度？", top_k=2)

    assert [item["content"] for item in compacted] == ["exact", "backup"]


def test_dify_record_ranking_uses_registered_plugin_retrieval_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: {
            "schema": "mimirq.retrieval_policy.v1",
            "boost_fields": [{"metadata": "product_line", "weight": 2.0, "match": "contains"}],
        }
        if ref == plugin_ref
        else {},
        raising=False,
    )
    records = [
        {
            "content": "generic but slightly higher score",
            "score": 0.54,
            "title": "generic.md",
            "metadata": {"chunk_python_plugin": plugin_ref, "product_line": "Beta Desk"},
        },
        {
            "content": "policy match",
            "score": 0.5,
            "title": "policy.md",
            "metadata": {"chunk_python_plugin": plugin_ref, "product_line": "Alpha Desk"},
        },
    ]

    dify_api._sort_records_for_query(records, query="Alpha Desk escalation path")

    assert [item["content"] for item in records] == ["policy match", "generic but slightly higher score"]


def test_dify_record_ranking_uses_plugin_policy_from_indexed_metadata_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: {
            "schema": "mimirq.retrieval_policy.v1",
            "boost_fields": [{"metadata": "product_line", "weight": 2.0, "match": "contains"}],
        }
        if ref == plugin_ref
        else {},
        raising=False,
    )
    records = [
        {
            "content": "generic but slightly higher score",
            "score": 0.54,
            "title": "generic.md",
            "metadata": {
                "chunk_python_plugin": plugin_ref,
                "_indexed_metadata": {"product_line": "Beta Desk"},
            },
        },
        {
            "content": "indexed policy match",
            "score": 0.5,
            "title": "policy.md",
            "metadata": {
                "chunk_python_plugin": plugin_ref,
                "_indexed_metadata": {"product_line": "Alpha Desk"},
            },
        },
    ]

    dify_api._sort_records_for_query(records, query="Alpha Desk escalation path")

    assert [item["content"] for item in records] == ["indexed policy match", "generic but slightly higher score"]


def test_dify_record_ranking_uses_plugin_query_expansion_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: {
            "schema": "mimirq.retrieval_policy.v1",
            "query_expansion_fields": ["product_line"],
        }
        if ref == plugin_ref
        else {},
        raising=False,
    )
    records = [
        {
            "content": "generic but slightly higher score",
            "score": 0.54,
            "title": "generic.md",
            "metadata": {"chunk_python_plugin": plugin_ref, "product_line": "Beta Desk"},
        },
        {
            "content": "query expansion field match",
            "score": 0.5,
            "title": "policy.md",
            "metadata": {"chunk_python_plugin": plugin_ref, "product_line": "Alpha Desk"},
        },
    ]

    dify_api._sort_records_for_query(records, query="Alpha Desk escalation path")

    assert [item["content"] for item in records] == [
        "query expansion field match",
        "generic but slightly higher score",
    ]


def test_dify_record_ranking_uses_knowledge_map_plugin_policy_when_records_lack_plugin_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: {
            "schema": "mimirq.retrieval_policy.v1",
            "query_expansion_values": [
                {"metadata": "section_type", "value": "steps", "terms": ["how to operate"]},
            ],
        }
        if ref == plugin_ref
        else {},
        raising=False,
    )
    records = [
        {
            "content": "entry chunk has slightly higher vector score",
            "score": 0.54,
            "title": "guide.md",
            "metadata": {"section_type": "entry"},
        },
        {
            "content": "step chunk should be promoted by map-level plugin policy",
            "score": 0.5,
            "title": "guide.md",
            "metadata": {"section_type": "steps"},
        },
    ]

    dify_api._sort_records_for_query(
        records,
        query="how to operate the service",
        policy_plugin_refs=(plugin_ref,),
    )
    diagnostics = dify_api._records_retrieval_policy_diagnostics(
        records,
        query="how to operate the service",
        policy_plugin_refs=(plugin_ref,),
    )

    assert [item["content"] for item in records] == [
        "step chunk should be promoted by map-level plugin policy",
        "entry chunk has slightly higher vector score",
    ]
    assert diagnostics["retrieval_policy_record_count"] == 2
    assert diagnostics["retrieval_policy_query_expansion_record_count"] == 1
    assert diagnostics["retrieval_policy_plugin_refs"] == [plugin_ref]


def test_dify_record_ranking_uses_plugin_rerank_features(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: {
            "schema": "mimirq.retrieval_policy.v1",
            "rerank_features": ["support_tier"],
        }
        if ref == plugin_ref
        else {},
        raising=False,
    )
    records = [
        {
            "content": "generic but slightly higher score",
            "score": 0.54,
            "title": "generic.md",
            "metadata": {"chunk_python_plugin": plugin_ref, "support_tier": "standard"},
        },
        {
            "content": "rerank feature match",
            "score": 0.5,
            "title": "policy.md",
            "metadata": {"chunk_python_plugin": plugin_ref, "support_tier": "priority escalation"},
        },
    ]

    dify_api._sort_records_for_query(records, query="priority escalation path")

    assert [item["content"] for item in records] == [
        "rerank feature match",
        "generic but slightly higher score",
    ]


def test_dify_record_ranking_demotes_plugin_anchor_mismatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: {
            "schema": "mimirq.retrieval_policy.v1",
            "anchor_fields": [
                {
                    "metadata": "region",
                    "weight": 2.0,
                    "aliases": {
                        "north": ["north", "north district"],
                        "south": ["south", "south district"],
                    },
                }
            ],
        }
        if ref == plugin_ref
        else {},
        raising=False,
    )
    records = [
        {
            "content": "wrong region but higher vector score",
            "score": 0.62,
            "title": "north.md",
            "metadata": {"chunk_python_plugin": plugin_ref, "region": "north"},
        },
        {
            "content": "matching region",
            "score": 0.5,
            "title": "south.md",
            "metadata": {"chunk_python_plugin": plugin_ref, "region": "south"},
        },
    ]

    dify_api._sort_records_for_query(records, query="How do I renew a permit in south district?")

    assert [item["content"] for item in records] == ["matching region", "wrong region but higher vector score"]
    diagnostics = dify_api._records_retrieval_policy_diagnostics(
        records,
        query="How do I renew a permit in south district?",
    )
    assert diagnostics["retrieval_policy_anchor_mismatch_record_count"] == 1


def test_dify_record_policy_diagnostics_summarize_active_plugin_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: {
            "schema": "mimirq.retrieval_policy.v1",
            "boost_fields": [{"metadata": "product_line", "weight": 2.0, "match": "contains"}],
        }
        if ref == plugin_ref
        else {},
        raising=False,
    )
    records = [
        {
            "content": "policy match",
            "score": 0.5,
            "title": "policy.md",
            "metadata": {"chunk_python_plugin": plugin_ref, "product_line": "Alpha Desk"},
        },
        {
            "content": "no policy",
            "score": 0.49,
            "title": "plain.md",
            "metadata": {"product_line": "Alpha Desk"},
        },
    ]

    diagnostics = dify_api._records_retrieval_policy_diagnostics(
        records,
        query="Alpha Desk escalation path",
    )

    assert diagnostics == {
        "retrieval_policy_record_count": 1,
        "retrieval_policy_boosted_record_count": 1,
        "retrieval_policy_boost_field_record_count": 1,
        "retrieval_policy_query_expansion_record_count": 0,
        "retrieval_policy_rerank_feature_record_count": 0,
        "retrieval_policy_anchor_mismatch_record_count": 0,
        "retrieval_policy_plugin_refs": ["plugin:demo-service@1.0.0:chunk"],
    }


def test_dify_record_policy_diagnostics_split_policy_signal_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: {
            "schema": "mimirq.retrieval_policy.v1",
            "boost_fields": [{"metadata": "product_line", "weight": 2.0, "match": "contains"}],
            "query_expansion_fields": ["alias"],
            "rerank_features": ["support_tier"],
        }
        if ref == plugin_ref
        else {},
        raising=False,
    )
    records = [
        {
            "content": "boost field match",
            "score": 0.5,
            "title": "boost.md",
            "metadata": {"chunk_python_plugin": plugin_ref, "product_line": "Alpha Desk"},
        },
        {
            "content": "query expansion match",
            "score": 0.5,
            "title": "query.md",
            "metadata": {"chunk_python_plugin": plugin_ref, "alias": "priority escalation"},
        },
        {
            "content": "rerank feature match",
            "score": 0.5,
            "title": "rerank.md",
            "metadata": {"chunk_python_plugin": plugin_ref, "support_tier": "priority escalation"},
        },
    ]

    diagnostics = dify_api._records_retrieval_policy_diagnostics(
        records,
        query="Alpha Desk priority escalation path",
    )

    assert diagnostics == {
        "retrieval_policy_record_count": 3,
        "retrieval_policy_boosted_record_count": 3,
        "retrieval_policy_boost_field_record_count": 1,
        "retrieval_policy_query_expansion_record_count": 1,
        "retrieval_policy_rerank_feature_record_count": 1,
        "retrieval_policy_anchor_mismatch_record_count": 0,
        "retrieval_policy_plugin_refs": ["plugin:demo-service@1.0.0:chunk"],
    }


def test_dify_metadata_condition_rejects_fields_not_allowed_by_plugin_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    plugin_ref = "plugin:demo-service@1.0.0:chunk"

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            '{"city": {'
            f'"dataset_ids": ["{dataset_id}"],'
            f'"plugin_refs": ["{plugin_ref}"]'
            "}}"
        ),
        raising=False,
    )
    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: {
            "schema": "mimirq.retrieval_policy.v1",
            "filter_fields": ["category"],
        }
        if ref == plugin_ref
        else {},
        raising=False,
    )

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": "policy match",
                "relevance_score": 0.5,
                "document_name": "policy.md",
                "metadata": {"chunk_python_plugin": plugin_ref, "category": "contract"},
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "Alpha Desk escalation path",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
            "metadata_condition": {
                "logical_operator": "and",
                "conditions": [
                    {"name": "category", "comparison_operator": "is", "value": "contract"},
                    {"name": "private_note", "comparison_operator": "is", "value": "internal"},
                ],
            },
        },
    )

    assert res.status_code == 400
    assert res.json() == {
        "error_code": 400,
        "error_msg": "Dify metadata filter field is not allowed by plugin retrieval_policy: private_note",
    }


def test_dify_metadata_condition_allows_plugin_policy_filter_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    captured_filter: dict[str, object] = {}

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            '{"city": {'
            f'"dataset_ids": ["{dataset_id}"],'
            f'"plugin_refs": ["{plugin_ref}"]'
            "}}"
        ),
        raising=False,
    )
    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: {
            "schema": "mimirq.retrieval_policy.v1",
            "filter_fields": ["category"],
        }
        if ref == plugin_ref
        else {},
        raising=False,
    )

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        captured_filter.update(kwargs["metadata_filter"] or {})
        return [
            {
                "chunk_content": "policy match",
                "relevance_score": 0.5,
                "document_name": "policy.md",
                "metadata": {"chunk_python_plugin": plugin_ref, "category": "contract"},
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "Alpha Desk escalation path",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
            "metadata_condition": {
                "conditions": [
                    {"name": "category", "comparison_operator": "is", "value": "contract"},
                ],
            },
        },
    )

    assert res.status_code == 200, res.text
    assert captured_filter == {"category": {"$eq": "contract"}}


def test_dify_plugin_retrieval_policy_fallback_expands_candidate_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    observed_top_k: list[int] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX", 10, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MIN", 1, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MULTIPLIER", 1, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX", 20, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            '{"city": {'
            f'"dataset_ids": ["{dataset_id}"],'
            f'"plugin_refs": ["{plugin_ref}"]'
            "}}"
        ),
        raising=False,
    )
    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: {
            "schema": "mimirq.retrieval_policy.v1",
            "fallback": {"enabled": True, "expand_top_k_multiplier": 3},
        }
        if ref == plugin_ref
        else {},
        raising=False,
    )

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        observed_top_k.append(kwargs["top_k"])
        return [
            {
                "chunk_content": "policy fallback candidate",
                "relevance_score": 0.5,
                "document_name": "policy.md",
                "metadata": {"chunk_python_plugin": plugin_ref},
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "Alpha Desk escalation path",
            "retrieval_setting": {"top_k": 2, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert observed_top_k == [6]


def test_dify_retrieval_logs_policy_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON", f'{{"city": "{dataset_id}"}}', raising=False)
    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: {
            "schema": "mimirq.retrieval_policy.v1",
            "boost_fields": [{"metadata": "product_line", "weight": 2.0, "match": "contains"}],
        }
        if ref == plugin_ref
        else {},
        raising=False,
    )

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": "policy match",
                "relevance_score": 0.5,
                "document_name": "policy.md",
                "metadata": {"chunk_python_plugin": plugin_ref, "product_line": "Alpha Desk"},
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)
    caplog.set_level(logging.INFO, logger=dify_api.logger.name)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "Alpha Desk escalation path",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    finished = [
        record
        for record in caplog.records
        if getattr(record, "event", "") == "dify_external_retrieval" and getattr(record, "phase", "") == "finished"
    ]
    assert finished
    record = finished[-1]
    assert record.retrieval_policy_record_count == 1
    assert record.retrieval_policy_boosted_record_count == 1
    assert record.retrieval_policy_boost_field_record_count == 1
    assert record.retrieval_policy_query_expansion_record_count == 0
    assert record.retrieval_policy_rerank_feature_record_count == 0
    assert record.retrieval_policy_anchor_mismatch_record_count == 0
    assert record.retrieval_policy_plugin_refs == [plugin_ref]
    assert "policy_records=1" in record.getMessage()
    assert "policy_boosted_records=1" in record.getMessage()
    assert "policy_boost_field_records=1" in record.getMessage()
    assert "policy_query_expansion_records=0" in record.getMessage()
    assert "policy_rerank_feature_records=0" in record.getMessage()
    assert "policy_anchor_mismatch_records=0" in record.getMessage()


def test_dify_integration_does_not_expose_fast_chunk_helpers() -> None:
    import app.api.v1.integrations_dify as dify_api

    assert "_retrieve_fast_chunk_citations" not in dir(dify_api)
    assert "_fast_chunk_candidate_score" not in dir(dify_api)


def test_dify_retrieval_expands_dataset_mapping_by_query_terms(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    city_dataset = uuid.uuid4()
    region_dataset = uuid.uuid4()
    calls: list[list[uuid.UUID]] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            '{"city": {'
            f'"dataset_ids": ["{city_dataset}"],'
            '"query_routes": ['
            '{"terms": ["区域甲", "辖区甲"], '
            f'"dataset_ids": ["{region_dataset}"], '
            '"mode": "prepend"}'
            "]"
            "}}"
        ),
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        calls.append(kwargs["dataset_ids"])
        return [
            {
                "chunk_content": "区域甲服务卡补卡办理地点",
                "relevance_score": 0.91,
                "document_name": "区域甲事项列表.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(region_dataset),
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "区域甲服务卡补卡在哪里办理",
            "retrieval_setting": {"top_k": 2, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls == [[region_dataset, city_dataset]]
    assert res.json()["records"][0]["content"] == "区域甲服务卡补卡办理地点"


def test_dify_retrieval_expands_scope_when_primary_has_no_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    city_dataset = uuid.uuid4()
    region_dataset = uuid.uuid4()
    calls: list[list[uuid.UUID]] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            '{"city": {'
            f'"dataset_ids": ["{city_dataset}"],'
            '"query_routes": ['
            '{"terms": ["区域甲", "辖区甲"], '
            f'"dataset_ids": ["{region_dataset}"], '
            '"mode": "prepend"}'
            "]"
            "}}"
        ),
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_SCOPE_ENABLED", True, raising=False)

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        dataset_ids = kwargs["dataset_ids"]
        calls.append(dataset_ids)
        if dataset_ids == [region_dataset]:
            return []
        if dataset_ids == [region_dataset, city_dataset]:
            return [
                {
                    "chunk_content": "城市本级服务卡补卡兜底说明",
                    "relevance_score": 0.72,
                    "document_name": "城市本级事项列表.txt",
                    "chunk_id": str(uuid.uuid4()),
                    "dataset_id": str(city_dataset),
                }
            ]
        return [
            {
                "chunk_content": "城市本级服务卡补卡兜底说明",
                "relevance_score": 0.72,
                "document_name": "城市本级事项列表.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(city_dataset),
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "区域甲服务卡补卡在哪里办理",
            "retrieval_setting": {"top_k": 2, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls == [[region_dataset, city_dataset]]
    assert res.json()["records"][0]["content"] == "城市本级服务卡补卡兜底说明"


def test_dify_query_routes_are_recall_hints_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    base_dataset = uuid.uuid4()
    one_thing_dataset = uuid.uuid4()
    department_qa_dataset = uuid.uuid4()

    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            '{"city": {'
            f'"dataset_ids": ["{base_dataset}"],'
            '"query_routes": ['
            '{"terms": ["一件事"], '
            f'"dataset_ids": ["{one_thing_dataset}"], '
            '"mode": "replace"},'
            '{"terms": ["不动产"], '
            f'"dataset_ids": ["{department_qa_dataset}"], '
            '"mode": "replace"}'
            "]"
            "}}"
        ),
        raising=False,
    )

    assert dify_api._resolve_knowledge_dataset_ids("city", query="普通查询") == [
        base_dataset,
        one_thing_dataset,
        department_qa_dataset,
    ]
    assert dify_api._resolve_knowledge_dataset_ids("city", query="不动产登记交易中心地址") == [
        department_qa_dataset,
        base_dataset,
        one_thing_dataset,
    ]


def test_dify_unmatched_route_hints_are_primary_candidates_for_aggregate_knowledge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    base_dataset = uuid.uuid4()
    faq_dataset = uuid.uuid4()
    calls: list[list[uuid.UUID]] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            '{"city": {'
            f'"dataset_ids": ["{base_dataset}"],'
            '"query_routes": ['
            '{"terms": ["汽车置换", "补贴"], '
            f'"dataset_ids": ["{faq_dataset}"], '
            '"mode": "replace"}'
            "]"
            "}}"
        ),
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_SCOPE_ENABLED", True, raising=False)

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        dataset_ids = kwargs["dataset_ids"]
        calls.append(dataset_ids)
        if faq_dataset in dataset_ids:
            return [
                {
                    "chunk_content": "问题：资金使用有哪些要求？\n答案：资金应专款专用。",
                    "relevance_score": 0.91,
                    "document_name": "03城市常见问题/高频政策QA.txt",
                    "chunk_id": str(uuid.uuid4()),
                    "dataset_id": str(faq_dataset),
                    "metadata": {
                        "question": "资金使用有哪些要求？",
                        "knowledge_section": "03城市常见问题",
                    },
                }
            ]
        return [
            {
                "chunk_content": "记录名称：资金监管备案\n办理地点：城市服务中心",
                "relevance_score": 0.96,
                "document_name": "01业务记录知识/城市业务记录列表.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(base_dataset),
                "metadata": {"knowledge_section": "01业务记录知识"},
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "资金使用有哪些要求？",
            "retrieval_setting": {"top_k": 1, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls == [[base_dataset, faq_dataset]]
    records = res.json()["records"]
    assert records[0]["metadata"]["knowledge_section"] == "03城市常见问题"


def test_dify_matched_replace_route_uses_route_dataset_as_primary_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    base_dataset = uuid.uuid4()
    topic_dataset = uuid.uuid4()
    other_hint_dataset = uuid.uuid4()
    calls: list[list[uuid.UUID]] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_SCOPE_ENABLED", True, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            '{"city": {'
            f'"dataset_ids": ["{base_dataset}"],'
            '"query_routes": ['
            '{"terms": ["身份证", "补领"], '
            f'"dataset_ids": ["{topic_dataset}"], '
            '"mode": "replace"},'
            '{"terms": ["一件事"], '
            f'"dataset_ids": ["{other_hint_dataset}"], '
            '"mode": "replace"}'
            "]"
            "}}"
        ),
        raising=False,
    )

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        dataset_ids = kwargs["dataset_ids"]
        calls.append(dataset_ids)
        assert dataset_ids == [topic_dataset]
        return [
            {
                "chunk_content": "问题：居民身份证补领需要什么材料？\n答案：居民户口簿、有效身份证件之一。",
                "relevance_score": 0.91,
                "document_name": "03城市常见问题/身份证QA.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(topic_dataset),
                "metadata": {
                    "knowledge_section": "03城市常见问题",
                    "gov_knowledge_type": "qa",
                    "chunk_kind": "qa_pair",
                },
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "居民身份证补领需要什么材料",
            "retrieval_setting": {"top_k": 2, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls == [[topic_dataset]]
    assert res.json()["records"][0]["metadata"]["knowledge_section"] == "03城市常见问题"


def test_dify_compact_prefers_records_aligned_to_plugin_retrieval_policy_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    policy = {
        "schema": "mimirq.retrieval_policy.v1",
        "query_expansion_values": [
            {"metadata": "section_type", "value": "materials", "terms": ["需要什么材料", "需要哪些材料"]},
            {"metadata": "section_type", "value": "channels", "terms": ["办理入口", "办理渠道"]},
        ],
        "response_compaction": {
            "enabled": True,
            "min_top_score": 0.7,
            "relative_score_floor": 0.65,
            "min_records": 1,
        },
    }
    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: policy if ref == plugin_ref else {},
        raising=True,
    )
    broad_record = {
        "content": "问题：核发居民身份证（补领）\n答案：办理入口和基础说明。",
        "score": 0.9,
        "title": "03城市常见问题/身份证QA.txt",
        "metadata": {
            "question": "核发居民身份证（补领）",
            "knowledge_section": "03城市常见问题",
            "gov_knowledge_type": "qa",
            "chunk_kind": "qa_pair",
            "section_type": "channels",
            "plugin_ref": plugin_ref,
        },
    }
    material_record = {
        "content": "问题：省外和省内人员补办身份证的办理材料和办理时限分别是什么？\n答案：居民户口簿、有效身份证件之一。",
        "score": 0.76,
        "title": "03城市常见问题/身份证QA.txt",
        "metadata": {
            "question": "省外和省内人员补办身份证的办理材料和办理时限分别是什么？",
            "knowledge_section": "03城市常见问题",
            "gov_knowledge_type": "qa",
            "chunk_kind": "qa_pair",
            "section_type": "materials",
            "plugin_ref": plugin_ref,
        },
    }
    records = [broad_record, material_record]
    dify_api._sort_records_for_query(records, query="居民身份证补领需要什么材料", policy_plugin_refs=(plugin_ref,))

    compacted = dify_api._compact_records_for_response(
        records,
        query="居民身份证补领需要什么材料",
        top_k=5,
        policy_plugin_refs=(plugin_ref,),
    )

    assert compacted == [material_record]


def test_dify_dedupe_collapses_chunks_from_same_source_record(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    records = [
        {
            "content": "问题：汽车置换更新\n相似问法：以旧换新、购车补贴",
            "score": 0.75,
            "title": "03城市常见问题/高频应用.xlsx",
            "metadata": {
                "knowledge_section": "03城市常见问题",
                "source_record_id": "record-car-subsidy",
                "_evaluable_metadata": {
                    "question": "汽车置换更新",
                    "source_record_id": "record-car-subsidy",
                    "knowledge_section": "03城市常见问题",
                    "chunk_kind": "qa_pair",
                },
            },
        },
        {
            "content": "问题：汽车置换更新\n答案：在苏服办APP申请卖旧置换更新补贴或报废置换更新补贴。",
            "score": 0.76,
            "title": "03城市常见问题/高频应用.xlsx",
            "metadata": {
                "knowledge_section": "03城市常见问题",
                "source_record_id": "record-car-subsidy",
                "_evaluable_metadata": {
                    "question": "汽车置换更新",
                    "source_record_id": "record-car-subsidy",
                    "knowledge_section": "03城市常见问题",
                    "chunk_kind": "qa_pair",
                },
            },
        },
    ]

    deduped = dify_api._dedupe_records(records, query="汽车置换补贴怎么申请")

    assert len(deduped) == 1
    assert "苏服办APP" in deduped[0]["content"]


def test_dify_answer_bearing_qa_beats_anchor_only_metadata_match(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    plugin_ref = _DEMO_PLUGIN_REF
    policy = _demo_policy(
        boost_fields=[
            {"metadata": "question", "weight": 2.0, "match": "fuzzy_overlap"},
            {"metadata": "aliases", "weight": 2.0, "match": "fuzzy_overlap"},
        ],
        rerank_features=["question", "aliases"],
    )
    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: policy if ref == plugin_ref else {},
        raising=True,
    )
    anchor_only_record = {
        "content": "检索锚点：核发居民身份证（补领）\n问题：核发居民身份证（补领）\n相似问法：居民身份证补领需要什么材料",
        "score": 0.78,
        "title": "03城市常见问题/身份证QA.txt",
        "metadata": {
            "question": "核发居民身份证（补领）",
            "aliases": ["居民身份证补领需要什么材料"],
            "chunk_kind": "qa_pair",
        },
    }
    answer_record = {
        "content": "答案要点：问题：补办身份证的办理材料是什么？；答案：居民户口簿、有效身份证件之一。",
        "score": 0.75,
        "title": "03城市常见问题/身份证QA.txt",
        "metadata": {
            "question": "省外和省内人员补办身份证的办理材料和办理时限分别是什么？",
            "aliases": ["身份证补办"],
            "chunk_kind": "qa_pair",
        },
    }
    records = [anchor_only_record, answer_record]

    dify_api._sort_records_for_query(
        records,
        query="居民身份证补领需要什么材料",
        policy_plugin_refs=(plugin_ref,),
    )

    assert records[0] is answer_record


def test_dify_question_intent_anchor_beats_broad_alias_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    plugin_ref = _DEMO_PLUGIN_REF
    policy = _demo_policy(
        boost_fields=[
            {"metadata": "question", "weight": 2.0, "match": "fuzzy_overlap"},
            {"metadata": "aliases", "weight": 2.0, "match": "fuzzy_overlap"},
        ],
        rerank_features=["question", "aliases"],
    )
    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: policy if ref == plugin_ref else {},
        raising=True,
    )
    broad_answer = {
        "content": "问题：核发居民身份证（补领）\n答案：本省户籍人员凭户口簿、驾驶证、居住证、护照其中之一办理。",
        "score": 0.64,
        "title": "03城市常见问题/身份证QA.txt",
        "metadata": {
            "question": "核发居民身份证（补领）",
            "aliases": ["居民身份证补领需要什么材料"],
            "source_topic": "核发居民身份证知识",
            "chunk_kind": "qa_pair",
        },
    }
    material_answer = {
        "content": "问题：省外和省内人员补办身份证的办理材料和办理时限分别是什么？\n答案：居民户口簿、有效身份证件之一。",
        "score": 0.75,
        "title": "03城市常见问题/身份证QA.txt",
        "metadata": {
            "question": "省外和省内人员补办身份证的办理材料和办理时限分别是什么？",
            "aliases": ["身份证补办"],
            "source_topic": "核发居民身份证知识",
            "chunk_kind": "qa_pair",
        },
    }
    records = [broad_answer, material_answer]

    dify_api._sort_records_for_query(
        records,
        query="居民身份证补领需要什么材料",
        policy_plugin_refs=(plugin_ref,),
    )

    assert records[0] is material_answer


def test_dify_compaction_keeps_strong_question_anchor_context(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    policy = {
        "schema": "mimirq.retrieval_policy.v1",
        "response_compaction": {
            "enabled": True,
            "min_top_score": 0.7,
            "relative_score_floor": 0.65,
            "min_records": 1,
        },
    }
    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: policy if ref == plugin_ref else {},
        raising=True,
    )
    channel_answer = {
        "content": "问题：线上业务渠道\n答案：“常州住房公积金”微信公众号、我的常州APP、江苏政务服务网。",
        "score": 0.72,
        "title": "05部门常见问题/线上业务.xlsx",
        "metadata": {"question": "线上业务渠道", "chunk_kind": "qa_pair"},
    }
    related_answers = [
        {
            "content": "问题：线上业务签约\n答案：可通过微信平台办理签约。",
            "score": 0.68,
            "title": "05部门常见问题/线上业务.xlsx",
            "metadata": {"question": "线上业务签约", "chunk_kind": "qa_pair"},
        },
        {
            "content": "问题：线上业务解约\n答案：可通过微信平台办理解约。",
            "score": 0.6,
            "title": "05部门常见问题/线上业务.xlsx",
            "metadata": {"question": "线上业务解约", "chunk_kind": "qa_pair"},
        },
    ]
    records = [channel_answer, *related_answers]

    dify_api._sort_records_for_query(records, query="公积金线上业务渠道有哪些", policy_plugin_refs=(plugin_ref,))
    compacted = dify_api._compact_records_for_response(
        records,
        query="公积金线上业务渠道有哪些",
        top_k=5,
        policy_plugin_refs=(plugin_ref,),
    )

    assert compacted == [channel_answer]


def test_dify_query_routes_can_be_strict_scope_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    base_dataset = uuid.uuid4()
    route_dataset = uuid.uuid4()

    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            '{"city": {'
            '"strict_query_routes": true,'
            f'"dataset_ids": ["{base_dataset}"],'
            '"query_routes": ['
            '{"terms": ["区域甲"], '
            f'"dataset_ids": ["{route_dataset}"], '
            '"mode": "replace"}'
            "]"
            "}}"
        ),
        raising=False,
    )

    assert dify_api._resolve_knowledge_dataset_ids("city", query="普通查询") == [base_dataset]
    assert dify_api._resolve_knowledge_dataset_ids("city", query="区域甲服务卡补卡在哪里办理") == [route_dataset]


def test_dify_retrieval_prefers_full_chunk_content_over_short_citation_snippet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    full_content = (
        "区县：区域甲\n"
        "事项名称：服务卡补卡\n"
        "办理地点：区域甲政务服务中心\n"
        "办理材料：居民身份证件（必要）\n"
        "咨询方式：0519-12333"
    )

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"region-alpha": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": "区县：区域甲...",
                "relevance_score": 0.73,
                "document_name": "区域甲事项列表.txt",
                "document_id": str(document_id),
                "chunk_id": str(chunk_id),
                "dataset_id": str(dataset_id),
                "metadata": {"chunk_python_plugin": _DEMO_PLUGIN_REF},
            }
        ]

    def _fake_load_chunk_content_map(**_kwargs):  # noqa: ANN003, ANN202
        return {str(chunk_id): full_content}

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", _fake_load_chunk_content_map, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "region-alpha",
            "query": "区域甲服务卡补卡在哪里办理",
            "retrieval_setting": {"top_k": 1, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    content = res.json()["records"][0]["content"]
    assert content.startswith("答案要点：")
    assert "事项名称：服务卡补卡" in content
    assert "办理地点：区域甲政务服务中心" in content
    assert "咨询方式：0519-12333" in content
    assert content.endswith(full_content)


def test_dify_response_hints_allow_plugin_configured_query_overlap_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    response_hints = _demo_response_hints()
    response_hints["structured_labels"] = [
        *response_hints["structured_labels"],  # type: ignore[index]
        "相似问法",
    ]
    response_hints["groups"][1]["query_gate"] = {  # type: ignore[index]
        "content_labels": ["事项名称", "相似问法"],
        "metadata": ["service_name", "service_aliases"],
        "min_chars": 4,
        "min_common_chars": 3,
    }
    _patch_demo_policy(monkeypatch, dify_api, response_hints=response_hints)

    content = (
        "区县：区域甲\n"
        "事项名称：社会保障卡补卡\n"
        "相似问法：补办社保卡、社保卡丢失、医保卡挂失补办\n"
        "办理地点：区域甲政务服务中心\n"
        "收费情况：不收费"
    )

    hinted = dify_api._content_with_answer_hints(
        content,
        {"service_name": "社会保障卡补卡"},
        query="区域甲社保卡补卡在哪里办理",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert hinted.startswith("答案要点：")
    assert "事项名称：社会保障卡补卡" in hinted
    assert "办理地点：区域甲政务服务中心" in hinted
    assert "收费情况：不收费" in hinted


def test_dify_sort_uses_plugin_configured_question_anchor_bonus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        question_intent_terms=["在哪里", "办理"],
        question_anchor_bonus=0.9,
    )
    records = [
        {
            "content": "事项名称：服务卡补卡\n办理地点：区域甲政务服务中心\n收费情况：不收费",
            "score": 1.0,
            "title": "服务事项.txt",
            "metadata": {"service_name": "服务卡补卡"},
        },
        {
            "content": "问题：请问我可以在哪里补办服务卡？\n答案：请拨打0519-12333咨询区域甲为民服务中心",
            "score": 0.74,
            "title": "区域甲12345QA.txt",
            "metadata": {"question": "请问我可以在哪里补办服务卡？", "chunk_kind": "qa_pair"},
        },
    ]

    dify_api._sort_records_for_query(
        records,
        query="补办服务卡在哪里办理",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert records[0]["title"] == "区域甲12345QA.txt"


def test_dify_compaction_preserves_top_question_anchor_before_policy_alignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        query_expansion_fields=["service_name"],
        question_intent_terms=["在哪里", "办理"],
        question_anchor_bonus=0.9,
        response_compaction={
            "enabled": True,
            "min_top_score": 0.8,
            "relative_score_floor": 0.65,
            "min_records": 1,
        },
    )
    records = [
        {
            "content": "问题：请问我可以在哪里补办服务卡？\n答案：请拨打0519-12333咨询区域甲为民服务中心",
            "score": 0.74,
            "title": "区域甲12345QA.txt",
            "metadata": {"question": "请问我可以在哪里补办服务卡？", "chunk_kind": "qa_pair"},
        },
        {
            "content": "事项名称：服务卡补卡\n办理地点：区域甲政务服务中心\n收费情况：不收费",
            "score": 1.0,
            "title": "服务事项.txt",
            "metadata": {"service_name": "服务卡补卡"},
        },
    ]

    compacted = dify_api._compact_records_for_response(
        records,
        query="区域甲服务卡补卡在哪里办理",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert [record["title"] for record in compacted] == ["区域甲12345QA.txt"]


def test_dify_retrieval_uses_map_plugin_refs_for_content_hints_when_citation_lacks_plugin_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    full_content = (
        "区县：区域甲\n"
        "事项名称：服务卡补卡\n"
        "办理地点：区域甲政务服务中心\n"
        "收费情况：不收费\n"
        "咨询方式：0519-12333"
    )

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            '{"region-alpha": {'
            f'"dataset_ids": ["{dataset_id}"], '
            f'"plugin_refs": ["{_DEMO_PLUGIN_REF}"]'
            "}}"
        ),
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": "区县：区域甲...",
                "relevance_score": 0.73,
                "document_name": "区域甲事项列表.txt",
                "chunk_id": str(chunk_id),
                "dataset_id": str(dataset_id),
                "metadata": {"service_name": "服务卡补卡"},
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {str(chunk_id): full_content}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "region-alpha",
            "query": "区域甲服务卡补卡在哪里办理",
            "retrieval_setting": {"top_k": 1, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    content = res.json()["records"][0]["content"]
    assert content.startswith("答案要点：")
    assert "收费情况：不收费" in content
    assert "原始证据：" in content


def test_dify_structured_service_hints_are_plugin_declared(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    policy = {
        "schema": "mimirq.retrieval_policy.v1",
        "response_hints": {
            "answer_prefix": "答案要点",
            "source_prefix": "原始证据",
            "structured_labels": ["事项名称", "办理地点", "收费情况"],
            "groups": [
                {
                    "required_any_labels": ["事项名称", "办理地点"],
                    "hint_labels": ["事项名称", "办理地点", "收费情况"],
                    "question_from_query_label": "问题",
                    "answer_label": "答案",
                    "query_gate": {
                        "content_labels": ["事项名称"],
                        "metadata": ["service_name", "service_aliases"],
                        "min_chars": 4,
                    },
                }
            ],
        },
    }
    content = "事项名称：服务卡补卡\n办理地点：区域甲政务服务中心\n收费情况：不收费"

    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: policy if ref == plugin_ref else {},
        raising=True,
    )

    without_plugin = dify_api._content_with_answer_hints(
        content,
        {"service_name": "服务卡补卡"},
        query="服务卡补卡在哪里办理",
    )
    with_plugin = dify_api._content_with_answer_hints(
        content,
        {"service_name": "服务卡补卡", "chunk_python_plugin": plugin_ref},
        query="服务卡补卡在哪里办理",
    )

    assert without_plugin == content
    assert with_plugin.startswith("答案要点：")
    assert "办理地点：区域甲政务服务中心" in with_plugin
    assert with_plugin.endswith(content)


def test_dify_retrieval_prepends_structured_answer_hints_for_fee_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    full_content = (
        "区县：区域乙\n"
        "事项名称：服务卡补卡\n"
        "办理地点：城市锦绣路2号城市政务服务中心1号楼一楼C区2-9号窗口\n"
        "收费情况：不收费\n"
        "咨询方式：0519-12333，0519-85519290"
    )

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"region-beta": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": full_content,
                "relevance_score": 0.73,
                "document_name": "区域乙事项列表.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {"chunk_python_plugin": _DEMO_PLUGIN_REF},
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "region-beta",
            "query": "区域乙服务卡补卡在哪里办理",
            "retrieval_setting": {"top_k": 1, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    content = res.json()["records"][0]["content"]
    hint = content.split("\n\n原始证据：", 1)[0]
    assert "办理地点：城市锦绣路2号城市政务服务中心1号楼一楼C区2-9号窗口" in hint
    assert "收费情况：不收费" in hint
    assert "咨询方式：0519-12333，0519-85519290" in hint
    assert full_content in content


def test_dify_retrieval_prepends_qa_answer_hints_for_long_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    full_content = (
        "检索锚点：汽车置换更新；以旧换新；购车补贴；主题：城市高频应用知识\n"
        "问题：汽车置换更新\n"
        "答案：汽车置换更新可以在移动端APP进行2025年补贴申请，可以申请两种类型的补贴："
        "1.卖旧置换更新补贴；2.报废置换更新补贴。申请完成后可在我的申请查看进度。"
    )

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": full_content,
                "relevance_score": 0.73,
                "document_name": "城市高频应用知识.xlsx",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {"chunk_python_plugin": _DEMO_PLUGIN_REF},
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "汽车置换补贴怎么申请",
            "retrieval_setting": {"top_k": 1, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    content = res.json()["records"][0]["content"]
    first_line = content.splitlines()[0]
    assert first_line == "必答要点：回答申请/入口/类型类问题时必须保留这些选项名称：卖旧置换更新补贴、报废置换更新补贴"
    hint = content.split("\n\n原始证据：", 1)[0]
    assert "移动端APP" in hint
    assert "2025年补贴申请" in hint
    assert "卖旧置换更新补贴" in hint
    assert "报废置换更新补贴" in hint
    assert content.endswith(full_content)


def test_dify_retrieval_frontloads_enumerated_options_from_existing_answer_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    full_content = (
        "答案要点：答案：汽车置换更新可以在移动端APP进行2025年补贴申请，"
        "可以申请两种类型的补贴： 1.卖旧置换更新补贴（旧车卖出后置换新车，"
        "从此入口发起补贴申请） 2.报废置换更新补贴（旧车报废后置换新车，"
        "从此入口发起补贴申请）。\n\n原始证据：\n答案：同上"
    )

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": full_content,
                "relevance_score": 0.73,
                "document_name": "城市高频应用知识.xlsx",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {"chunk_python_plugin": _DEMO_PLUGIN_REF},
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "汽车置换补贴怎么申请",
            "retrieval_setting": {"top_k": 1, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    content = res.json()["records"][0]["content"]
    first_line = content.splitlines()[0]
    assert first_line == "必答要点：回答申请/入口/类型类问题时必须保留这些选项名称：卖旧置换更新补贴、报废置换更新补贴"
    assert content.endswith(full_content)


def test_dify_retrieval_frontloads_options_with_closing_parenthesis_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    full_content = "答案：服务支持两种入口：1）网页端入口；2）移动端入口。"

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": full_content,
                "relevance_score": 0.73,
                "document_name": "入口说明.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {"chunk_python_plugin": _DEMO_PLUGIN_REF},
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "有哪些入口",
            "retrieval_setting": {"top_k": 1, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    content = res.json()["records"][0]["content"]
    first_line = content.splitlines()[0]
    assert first_line == "必答要点：回答申请/入口/类型类问题时必须保留这些选项名称：网页端入口、移动端入口"
    assert content.endswith(full_content)


def test_dify_retrieval_frontloads_named_way_markers_from_real_qa_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    full_content = (
        "答案：证件查询。方式一，下载“苏证通”APP，可以查询身份证办证进度；"
        "方式二、微信关注“江苏公安微警务”公众号，在“服务大厅”中查询。"
    )

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": full_content,
                "relevance_score": 0.73,
                "document_name": "城市本级12345QA.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {"chunk_python_plugin": _DEMO_PLUGIN_REF},
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "如何查询身份证办理进度？",
            "retrieval_setting": {"top_k": 1, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    content = res.json()["records"][0]["content"]
    first_line = content.splitlines()[0]
    assert first_line == "必答要点：回答申请/入口/类型类问题时必须保留这些选项名称：下载“苏证通”APP、微信关注“江苏公安微警务”公众号"
    assert content.endswith(full_content)


def test_dify_retrieval_does_not_treat_numbered_process_steps_as_answer_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    full_content = (
        "答案：网上办理流程如下：1.登录江苏政务服务网；"
        "2.选择服务卡居民服务一件事；3.提交申请材料。"
    )

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": full_content,
                "relevance_score": 0.73,
                "document_name": "一件事操作指引.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {"chunk_python_plugin": _DEMO_PLUGIN_REF},
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "服务卡居民服务一件事网上办理怎么操作",
            "retrieval_setting": {"top_k": 1, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    content = res.json()["records"][0]["content"]
    assert not content.startswith("必答要点：")
    assert content.startswith("答案要点：答案：")
    assert content.endswith(full_content)


def test_dify_retrieval_does_not_frontload_enumerated_options_for_non_option_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    full_content = (
        "答案：汽车置换更新可以申请两种类型的补贴："
        "1.卖旧置换更新补贴；2.报废置换更新补贴。"
    )

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": full_content,
                "relevance_score": 0.73,
                "document_name": "城市高频应用知识.xlsx",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {"chunk_python_plugin": _DEMO_PLUGIN_REF},
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "汽车置换补贴多久到账",
            "retrieval_setting": {"top_k": 1, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    content = res.json()["records"][0]["content"]
    assert not content.startswith("必答要点：")
    assert content.startswith("答案要点：答案：")
    assert content.endswith(full_content)


def test_dify_retrieval_does_not_prepend_service_hints_for_weak_service_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    full_content = (
        "事项名称：服务卡密码修改与重置\n"
        "办理地点：城市政务服务中心\n"
        "收费情况：不收费\n"
        "咨询方式：0519-12333"
    )

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": full_content,
                "relevance_score": 0.73,
                "document_name": "城市事项列表.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {"service_name": "服务卡密码修改与重置", "chunk_python_plugin": _DEMO_PLUGIN_REF},
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "企业员工密码输入错误5次怎么办",
            "retrieval_setting": {"top_k": 1, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert res.json()["records"][0]["content"] == full_content


def test_dify_retrieval_uses_plugin_retrieval_intents_for_tie_breaking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": "入口说明正文",
                "relevance_score": 0.73,
                "document_name": "一件事操作指引.txt",
                "chunk_id": str(uuid.uuid4()),
                "metadata": {
                    "section_type": "operation_url",
                    "retrieval_intents": ["在线入口", "操作手册入口"],
                },
            },
            {
                "chunk_content": "步骤说明正文",
                "relevance_score": 0.73,
                "document_name": "一件事操作指引.txt",
                "chunk_id": str(uuid.uuid4()),
                "metadata": {
                    "_evaluable_metadata": {
                        "section_type": "operation_steps",
                        "retrieval_intents": ["网上办理怎么操作", "申报步骤"],
                    }
                },
            },
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "服务卡居民服务一件事网上办理怎么操作",
            "retrieval_setting": {"top_k": 2, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    records = res.json()["records"]
    assert records[0]["content"] == "步骤说明正文"
    assert records[0]["metadata"]["_evaluable_metadata"]["section_type"] == "operation_steps"
    assert records[1]["content"] == "入口说明正文"


def test_dify_retrieval_prefers_metadata_question_anchor_for_tie_breaking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": "一件事：教育入学。章节：申请材料。户口簿、合法固定住所证件。",
                "relevance_score": 0.73,
                "document_name": "02联办流程指南/联办流程指南.txt",
                "chunk_id": str(uuid.uuid4()),
                "metadata": {
                    "chunk_kind": "one_thing_materials",
                    "section_type": "materials",
                    "case_title": "教育入学“一件事”",
                },
            },
            {
                "chunk_content": "问题：小学入学需要哪些材料？\n答案：凭户口簿、合法固定住所证件，到所在学区小学办理报名手续。",
                "relevance_score": 0.73,
                "document_name": "04专题常见问答/2026年城市义务教育学校招生入学常见问题.txt",
                "chunk_id": str(uuid.uuid4()),
                "metadata": {
                    "_evaluable_metadata": {
                        "question": "小学入学需要哪些材料？",
                        "aliases": ["上小学要准备什么材料", "小学报名需要带什么"],
                        "chunk_kind": "qa_pair",
                        "knowledge_section": "04专题常见问答",
                    }
                },
            },
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "小学入学需要哪些材料",
            "retrieval_setting": {"top_k": 2, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    records = res.json()["records"]
    assert records[0]["metadata"]["_evaluable_metadata"]["question"] == "小学入学需要哪些材料？"
    assert records[1]["metadata"]["chunk_kind"] == "one_thing_materials"


def test_dify_retrieval_prefers_regional_qa_question_anchor_over_service_item_tie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"region-beta": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": "记录名称：企业社会保险登记\n办理地点：城市服务中心窗口",
                "relevance_score": 0.73,
                "document_name": "01业务记录知识/区域乙业务记录列表.txt",
                "chunk_id": str(uuid.uuid4()),
                "metadata": {
                    "district": "区域乙",
                    "service_name": "企业社会保险登记",
                    "chunk_kind": "service_item",
                    "knowledge_section": "01业务记录知识",
                },
            },
            {
                "chunk_content": "问题：请问可以在哪里办理企业社会保险登记？\n答案：可到城市区域乙政务服务中心办理。",
                "relevance_score": 0.73,
                "document_name": "06各区常见问题/区域乙12345QA.txt",
                "chunk_id": str(uuid.uuid4()),
                "metadata": {
                    "district": "区域乙",
                    "_evaluable_metadata": {
                        "question": "请问可以在哪里办理企业社会保险登记？",
                        "chunk_kind": "qa_pair",
                        "knowledge_section": "06各区常见问题",
                    },
                },
            },
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "region-beta",
            "query": "区域乙在哪里办理企业社会保险登记",
            "retrieval_setting": {"top_k": 2, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    records = res.json()["records"]
    assert records[0]["metadata"]["_evaluable_metadata"]["question"] == "请问可以在哪里办理企业社会保险登记？"
    assert records[1]["metadata"]["service_name"] == "企业社会保险登记"


def test_dify_retrieval_uses_plugin_policy_value_intents_without_metadata_intents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    plugin_ref = "plugin:demo-service@1.0.0:chunk"

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: {
            "schema": "mimirq.retrieval_policy.v1",
            "query_expansion_values": [
                {"metadata": "section_type", "value": "entry", "terms": ["portal entry"]},
                {"metadata": "section_type", "value": "steps", "terms": ["renewal steps"]},
            ],
        }
        if ref == plugin_ref
        else {},
        raising=False,
    )

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": "Portal entry explanation",
                "relevance_score": 0.73,
                "document_name": "alpha-guide.md",
                "chunk_id": str(uuid.uuid4()),
                "metadata": {"chunk_python_plugin": plugin_ref, "section_type": "entry"},
            },
            {
                "chunk_content": "Renewal steps explanation",
                "relevance_score": 0.73,
                "document_name": "alpha-guide.md",
                "chunk_id": str(uuid.uuid4()),
                "metadata": {"chunk_python_plugin": plugin_ref, "section_type": "steps"},
            },
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "Alpha Desk renewal steps",
            "retrieval_setting": {"top_k": 2, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    records = res.json()["records"]
    assert "Renewal steps explanation" in records[0]["content"]
    assert "Portal entry explanation" in records[1]["content"]


def test_dify_retrieval_plugin_policy_value_intent_can_beat_small_score_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    plugin_ref = "plugin:demo-service@1.0.0:chunk"

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: {
            "schema": "mimirq.retrieval_policy.v1",
            "query_expansion_values": [
                {"metadata": "section_type", "value": "entry", "terms": ["portal entry"]},
                {"metadata": "section_type", "value": "steps", "terms": ["renewal steps"]},
            ],
        }
        if ref == plugin_ref
        else {},
        raising=False,
    )

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": "Portal entry explanation",
                "relevance_score": 0.81,
                "document_name": "alpha-guide.md",
                "chunk_id": str(uuid.uuid4()),
                "metadata": {"chunk_python_plugin": plugin_ref, "section_type": "entry"},
            },
            {
                "chunk_content": "Renewal steps explanation",
                "relevance_score": 0.77,
                "document_name": "alpha-guide.md",
                "chunk_id": str(uuid.uuid4()),
                "metadata": {"chunk_python_plugin": plugin_ref, "section_type": "steps"},
            },
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "Alpha Desk renewal steps",
            "retrieval_setting": {"top_k": 2, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    records = res.json()["records"]
    assert records[0]["content"] == "Renewal steps explanation"
    assert records[0]["metadata"]["section_type"] == "steps"
    assert records[1]["content"] == "Portal entry explanation"


def test_dify_retrieval_ignores_content_search_anchor_without_metadata_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": "检索锚点：服务卡居民服务一件事；章节意图：在线入口、操作手册入口\n入口说明正文",
                "relevance_score": 0.73,
                "document_name": "一件事操作指引.txt",
                "chunk_id": str(uuid.uuid4()),
                "metadata": {},
            },
            {
                "chunk_content": "检索锚点：服务卡居民服务一件事；章节意图：申报流程、网上办理怎么操作\n步骤说明正文",
                "relevance_score": 0.73,
                "document_name": "一件事操作指引.txt",
                "chunk_id": str(uuid.uuid4()),
                "metadata": {},
            },
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "服务卡居民服务一件事网上办理怎么操作",
            "retrieval_setting": {"top_k": 2, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    records = res.json()["records"]
    assert "入口说明正文" in records[0]["content"]
    assert "步骤说明正文" in records[1]["content"]


def test_dify_retrieval_does_not_boost_generic_anchor_terms_over_specific_hits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": "检索锚点：临时身份证怎么办理，在哪办理，需要什么材料\n临时身份证材料说明",
                "relevance_score": 0.72,
                "document_name": "身份证问答.txt",
                "chunk_id": str(uuid.uuid4()),
            },
            {
                "chunk_content": "检索锚点：省外和省内人员补办身份证的办理材料和办理时限分别是什么？；身份证补办\n居民身份证补领材料说明",
                "relevance_score": 0.73,
                "document_name": "身份证问答.txt",
                "chunk_id": str(uuid.uuid4()),
            },
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "居民身份证补领需要什么材料",
            "retrieval_setting": {"top_k": 2, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    records = res.json()["records"]
    assert "居民身份证补领材料说明" in records[0]["content"]
    assert "临时身份证材料说明" in records[1]["content"]


def test_dify_retrieval_rejects_missing_or_wrong_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", "expected-token", raising=False)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    payload = {
        "knowledge_id": str(uuid.uuid4()),
        "query": "test",
        "retrieval_setting": {"top_k": 1, "score_threshold": 0.0},
    }
    missing = client.post("/api/v1/integrations/dify/retrieval", json=payload)
    wrong = client.post("/api/v1/integrations/dify/retrieval", headers=_auth("wrong-token"), json=payload)

    assert missing.status_code == 401
    assert missing.json() == {"error_code": 1001, "error_msg": "Invalid Dify Authorization header"}
    assert wrong.status_code == 401
    assert wrong.json() == {"error_code": 1002, "error_msg": "Invalid Dify API key"}


def test_dify_metadata_condition_is_converted_to_mimirq_filter() -> None:
    from app.api.v1.integrations_dify import _metadata_condition_to_filter
    from app.rag.core.filters import match_metadata_filter

    metadata_filter = _metadata_condition_to_filter(
        {
            "logical_operator": "or",
            "conditions": [
                {"name": "category", "comparison_operator": "is", "value": "contract"},
                {"name": "tags", "comparison_operator": "contains", "value": "pricing"},
                {"name": "page", "comparison_operator": "≥", "value": 3},
            ],
        }
    )

    assert metadata_filter == {
        "$or": [
            {"category": {"$eq": "contract"}},
            {"tags": {"$contains": "pricing"}},
            {"page": {"$gte": 3}},
        ]
    }
    assert match_metadata_filter({"category": "contract"}, metadata_filter)
    assert match_metadata_filter({"tags": ["sales-pricing"]}, metadata_filter)
    assert match_metadata_filter({"page": 4}, metadata_filter)
    assert not match_metadata_filter({"category": "faq", "tags": ["ops"], "page": 2}, metadata_filter)


def test_dify_record_conversion_keeps_metadata_object_and_clamps_score() -> None:
    from app.api.v1.integrations_dify import _citation_to_dify_record

    record = _citation_to_dify_record(
        {
            "content": "fallback content",
            "relevance_score": 1.7,
            "document_name": "",
            "document_id": "doc-1",
            "chunk_id": "chunk-1",
            "page_number": 9,
            "metadata": None,
        },
        dataset_id=uuid.UUID("00000000-0000-0000-0000-000000000123"),
    )

    assert record["content"] == "fallback content"
    assert record["score"] == 1.0
    assert record["title"] == "doc-1"
    assert record["metadata"] == {
        "dataset_id": "00000000-0000-0000-0000-000000000123",
        "document_id": "doc-1",
        "chunk_id": "chunk-1",
        "page_number": 9,
    }


def test_dify_record_conversion_keeps_kg_diagnostics_metadata() -> None:
    from app.api.v1.integrations_dify import _citation_to_dify_record

    record = _citation_to_dify_record(
        {
            "content": "kg enriched content",
            "relevance_score": 0.8,
            "document_name": "kg.txt",
            "document_id": "doc-1",
            "chunk_id": "chunk-1",
            "retrieval_role": "main",
            "kg_pagerank": 0.094,
            "kg_shared_events": 2,
            "kg_path_length": 1,
            "kg_evidence_anchored": True,
        },
        dataset_id=uuid.UUID("00000000-0000-0000-0000-000000000123"),
    )

    assert record["metadata"]["retrieval_role"] == "main"
    assert record["metadata"]["kg_pagerank"] == 0.094
    assert record["metadata"]["kg_shared_events"] == 2
    assert record["metadata"]["kg_path_length"] == 1
    assert record["metadata"]["kg_evidence_anchored"] is True
