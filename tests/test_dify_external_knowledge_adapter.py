
import asyncio
import json
import logging
import threading
import time
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.database import get_db


class _DummyDB:
    pass


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


class _FakeRedis:
    def __init__(self) -> None:
        self._values: dict[str, bytes | str] = {}
        self._expires_at: dict[str, float] = {}

    def _purge_expired(self, key: str) -> None:
        expires_at = self._expires_at.get(key)
        if expires_at is not None and expires_at <= time.monotonic():
            self._values.pop(key, None)
            self._expires_at.pop(key, None)

    def get(self, key: str):  # noqa: ANN201
        self._purge_expired(key)
        return self._values.get(key)

    def set(self, key: str, value: bytes | str, *, ex: int | None = None, nx: bool = False) -> bool:
        self._purge_expired(key)
        if nx and key in self._values:
            return False
        self._values[key] = value
        if ex is not None:
            self._expires_at[key] = time.monotonic() + max(1, int(ex))
        else:
            self._expires_at.pop(key, None)
        return True

    def eval(self, _script: str, _numkeys: int, key: str, value: str) -> int:
        self._purge_expired(key)
        current = self._values.get(key)
        if isinstance(current, bytes):
            current = current.decode("utf-8", "ignore")
        if current != value:
            return 0
        self._values.pop(key, None)
        self._expires_at.pop(key, None)
        return 1

    def ttl_remaining(self, key: str) -> int | None:
        self._purge_expired(key)
        expires_at = self._expires_at.get(key)
        if expires_at is None:
            return None
        return max(0, int(expires_at - time.monotonic()))


def _patch_fake_dify_redis(monkeypatch: pytest.MonkeyPatch, dify_api, redis: _FakeRedis) -> None:  # noqa: ANN001
    async def _get_json(key: str):  # noqa: ANN202
        raw = redis.get(key)
        if not raw:
            return None
        text = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else str(raw)
        return json.loads(text)

    async def _set_json(key: str, payload, *, ttl_sec: int, max_value_bytes: int = 0):  # noqa: ANN001, ANN202
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if max_value_bytes > 0 and len(raw) > max_value_bytes:
            return False
        return bool(redis.set(key, raw, ex=ttl_sec))

    async def _acquire_lease(key: str, *, value: str, ttl_sec: int):  # noqa: ANN202
        return bool(redis.set(key, value, ex=ttl_sec, nx=True))

    async def _release(key: str, *, value: str):  # noqa: ANN202
        redis.eval("", 1, key, value)

    monkeypatch.setattr(dify_api, "get_best_effort_json_cache_value", _get_json, raising=True)
    monkeypatch.setattr(dify_api, "set_best_effort_json_cache_value", _set_json, raising=True)
    monkeypatch.setattr(dify_api, "try_acquire_best_effort_redis_lease", _acquire_lease, raising=True)
    monkeypatch.setattr(dify_api, "release_best_effort_redis_lease", _release, raising=True)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


_DEMO_PLUGIN_REF = "plugin:demo-service@1.0.0:chunk"


def test_dify_citation_record_preserves_rerank_metadata() -> None:
    import app.api.v1.integrations_dify as dify_api

    record = dify_api._citation_to_dify_record(
        {
            "content": "公积金业务办理进度",
            "title": "线上业务.xlsx",
            "score": 0.72,
            "hit_type": "keyword",
            "rerank_score": 0.93,
            "rerank_score_final": 0.95,
            "reranker_provider": "openai",
            "rerank_elapsed_sec": 0.12,
            "rerank_model_used": "bge-reranker-large",
        },
        dataset_id=uuid.uuid4(),
        query="公积金业务办理进度",
    )

    metadata = record["metadata"]
    assert metadata["hit_type"] == "keyword"
    assert metadata["rerank_score"] == pytest.approx(0.93)
    assert metadata["rerank_score_final"] == pytest.approx(0.95)
    assert metadata["reranker_provider"] == "openai"
    assert metadata["rerank_elapsed_sec"] == pytest.approx(0.12)
    assert metadata["rerank_model_used"] == "bge-reranker-large"


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


def _demo_service_anchor_noise_terms() -> list[str]:
    return [
        "咨询电话是多少",
        "联系电话是多少",
        "咨询电话",
        "联系电话",
        "电话号码",
        "电话是多少",
        "收费吗",
        "是否收费",
        "需要收费吗",
        "收费标准是什么",
        "收费标准",
        "什么时候可以办",
        "什么时候办理",
        "什么时候能办",
        "什么时候办",
        "办理入口在哪里",
        "入口在哪里",
        "在哪里进入办理",
        "进入办理",
        "在哪里办理",
        "在哪办理",
        "哪里办理",
        "涉及哪些事项",
        "包含哪些事项",
        "有哪些事项",
        "如何办理",
        "怎么办理",
        "怎么申请",
        "如何申请",
        "需要什么材料",
        "需要哪些材料",
        "需要什么资料",
        "需要哪些资料",
        "要什么材料",
        "要哪些材料",
        "办理材料",
        "申请材料",
        "所需材料",
        "可以办理吗",
        "可以办吗",
        "可以办理",
        "可以办",
        "办理",
        "多少",
        "是什么",
    ]


def _demo_service_anchor_priority_terms() -> list[str]:
    return [
        "咨询电话是多少",
        "联系电话是多少",
        "咨询电话",
        "联系电话",
        "电话号码",
        "电话是多少",
        "收费吗",
        "是否收费",
        "需要收费吗",
        "什么时候可以办",
        "什么时候办理",
        "什么时候能办",
        "什么时候办",
        "办理入口在哪里",
        "入口在哪里",
        "在哪里进入办理",
        "进入办理",
        "在哪里办理",
        "在哪办理",
        "哪里办理",
    ]


def _demo_fast_response_field_rules() -> list[dict[str, object]]:
    return [
        {"label": "行使层级", "markers": ["行使层级", "层级"]},
        {"label": "办理地点", "markers": ["办理地点", "地点", "哪里办理"]},
        {"label": "办理材料", "markers": ["办理材料", "申请材料", "材料"]},
        {"label": "法定办结时限", "markers": ["法定办结时限", "法定时限", "办结时限", "多久"]},
        {"label": "承诺办结时限", "markers": ["承诺办结时限", "承诺时限", "办结时限", "多久"]},
        {"label": "收费情况", "markers": ["收费", "费用"]},
        {"label": "涉及事项", "markers": ["涉及事项", "涉及哪些事项"]},
        {"label": "申请材料", "markers": ["申请材料", "材料"]},
        {"label": "办理入口", "markers": ["办理渠道", "办理入口"]},
        {"label": "答案", "markers": ["答案", "怎么", "如何"]},
    ]


def _demo_policy(**overrides: object) -> dict[str, object]:
    policy: dict[str, object] = {
        "schema": "mimirq.retrieval_policy.v1",
        "question_intent_terms": [
            "材料",
            "证件",
            "地点",
            "在哪里",
            "哪里办理",
            "办理地点",
            "渠道",
            "入口",
            "方式",
            "流程",
            "步骤",
            "操作",
            "进度",
            "查询",
            "费用",
            "收费",
            "电话",
            "咨询",
            "条件",
            "时限",
        ],
        "service_anchor_noise_terms": _demo_service_anchor_noise_terms(),
        "service_anchor_priority_terms": _demo_service_anchor_priority_terms(),
        "service_anchor_entity_terms": ["许可", "审批", "备案", "登记", "申报", "申领", "核准", "审查", "证", "配发"],
        "service_anchor_leading_noise_terms": ["麻烦帮我查一下", "麻烦查一下", "帮我查一下", "查询", "查一下"],
        "service_anchor_cutoff_terms": [
            "是不是能办",
            "是否能办",
            "这个事项",
            "帮我直接说清楚",
            "行使层级",
            "受理条件",
            "办理形式",
            "办理地点",
            "法定办结时限",
            "承诺办结时限",
            "办理材料",
            "最好",
        ],
        "question_anchor_generic_subject_terms": ["事项", "材料", "申请材料", "办理材料", "办理入口", "办理流程", "流程"],
        "fast_response_always_labels": ["区县", "事项名称", "问题", "一件事"],
        "fast_response_field_rules": _demo_fast_response_field_rules(),
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


def test_dify_warmup_knowledge_ids_default_to_map_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_KNOWLEDGE_IDS", "", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_MAX_KNOWLEDGE_IDS", 2, raising=False)

    ids = dify_api._resolve_dify_warmup_knowledge_ids({"city": "dataset-a", "district": "dataset-b", "faq": "dataset-c"})

    assert ids == ("city", "district")


@pytest.mark.asyncio
async def test_dify_warmup_runs_internal_retrieval_for_configured_knowledge_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    tenant_id = uuid.uuid4()
    city_dataset_id = uuid.uuid4()
    faq_dataset_id = uuid.uuid4()
    retrieval_calls: list[dict[str, object]] = []

    class _Session:
        closed = False

        def close(self) -> None:
            self.closed = True

    session = _Session()

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        retrieval_calls.append(dict(kwargs))
        return []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID", str(tenant_id), raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_KNOWLEDGE_IDS", "city,faq", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_QUERY", "warmup probe", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TOP_K", 1, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{city_dataset_id}", "faq": "{faq_dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)

    result = await dify_api.warmup_dify_external_knowledge(db_factory=lambda: session)

    assert result["attempted"] == 2
    assert result["completed"] == 2
    assert result["failed"] == 0
    assert session.closed is True
    assert [call["dataset_ids"] for call in retrieval_calls] == [[city_dataset_id], [faq_dataset_id]]
    assert {call["query"] for call in retrieval_calls} == {"warmup probe"}
    assert {call["top_k"] for call in retrieval_calls} == {1}
    assert {call["enable_reranker"] for call in retrieval_calls} == {False}
    assert {call["enable_kg_query_expansion"] for call in retrieval_calls} == {False}
    assert {call["enable_kg_chunk_injection"] for call in retrieval_calls} == {False}
    assert {call["enable_kg_chunk_boost"] for call in retrieval_calls} == {False}


@pytest.mark.asyncio
async def test_dify_delayed_warmup_stays_on_startup_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    startup_loop = asyncio.get_running_loop()
    observed_loops: list[asyncio.AbstractEventLoop] = []

    async def fake_warmup() -> dict[str, object]:
        observed_loops.append(asyncio.get_running_loop())
        return {"enabled": True}

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_START_DELAY_SEC", 0.0)
    monkeypatch.setattr(dify_api, "warmup_dify_external_knowledge", fake_warmup)

    assert await dify_api._delayed_warmup_dify_external_knowledge() == {"enabled": True}
    assert observed_loops == [startup_loop]


def test_dify_warmup_scheduler_is_fire_and_forget(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    scheduled = []

    def _fake_create_task(coro):  # noqa: ANN001, ANN202
        scheduled.append(coro)
        coro.close()
        return object()

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_START_DELAY_SEC", 1.0, raising=False)

    task = dify_api.start_dify_external_knowledge_warmup(create_task=_fake_create_task)

    assert task is not None
    assert scheduled
    assert scheduled[0].cr_code.co_name == "_delayed_warmup_dify_external_knowledge"


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
        headers={**_auth(token), "X-Forwarded-For": "192.0.2.251, 127.0.0.1"},
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
    assert record.client_ip_hash == dify_api._diagnostic_value_hash("192.0.2.251")
    assert record.knowledge_id_hash == dify_api._diagnostic_value_hash("city")
    assert not hasattr(record, "client_ip")
    assert not hasattr(record, "knowledge_id")
    assert not hasattr(record, "query_preview")
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
    assert "client_ip_hash=" in message
    assert "knowledge_id_hash=" in message
    assert "192.0.2.251" not in message
    assert "knowledge_id=city" not in message
    assert "如何查询身份证办理进度" not in message
    assert "records=1" in message


@pytest.mark.asyncio
async def test_dify_direct_retrieval_uses_configured_reranker_and_overfetch_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api
    import app.api.v1.rag as rag_api

    captured: dict[str, object] = {}

    monkeypatch.setattr(dify_api.settings, "ENABLE_RERANKER", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "RERANKER_PROVIDER", "openai", raising=False)
    monkeypatch.setattr(dify_api.settings, "RERANKER_TOP_N", 20, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RERANKER_ENABLED", True, raising=False)
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
    assert rag_config.enable_reranker is True
    assert rag_config.reranker_provider == "openai"
    assert rag_config.reranker_top_n == 20
    assert rag_config.lexical_db_hybrid_fallback_only is False
    assert rag_config.lexical_db_hybrid_metadata_exact_fallback_enabled is False
    assert rag_config.metadata_exact_db_fallback_enabled is False
    assert rag_config.retrieval_overfetch_multiplier == 1
    assert rag_config.retrieval_overfetch_max_k == 20
    assert rag_config.enable_kg_query_expansion is True
    assert rag_config.enable_kg_chunk_injection is True
    assert rag_config.kg_chunk_injection_max_chunks == 3
    assert rag_config.enable_kg_chunk_boost is True
    assert rag_config.kg_chunk_boost_weight == pytest.approx(0.25)
    assert rag_config.kg_chunk_boost_max_promoted == 2


@pytest.mark.asyncio
async def test_dify_direct_retrieval_can_enable_metadata_exact_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api
    import app.api.v1.rag as rag_api

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_LEXICAL_METADATA_EXACT_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_EXACT_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )

    async def _fake_retrieve_evidence(**kwargs):  # noqa: ANN003, ANN202
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
        query="需要精确字段兜底的问题",
        top_k=5,
        score_threshold=0.0,
    )

    rag_config = captured["rag_config"]
    assert rag_config.lexical_db_hybrid_metadata_exact_fallback_enabled is True
    assert rag_config.metadata_exact_db_fallback_enabled is True


@pytest.mark.asyncio
async def test_dify_direct_retrieval_can_defer_internal_reranker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api
    import app.api.v1.rag as rag_api

    captured: dict[str, object] = {}

    monkeypatch.setattr(dify_api.settings, "ENABLE_RERANKER", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "RERANKER_PROVIDER", "openai", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RERANKER_ENABLED", True, raising=False)

    async def _fake_retrieve_evidence(**kwargs):  # noqa: ANN003, ANN202
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
        query="compound recall branch",
        top_k=5,
        score_threshold=0.0,
        enable_reranker=False,
    )

    rag_config = captured["rag_config"]
    assert rag_config.enable_reranker is False
    assert rag_config.reranker_provider == "none"


def test_dify_metadata_anchor_fallback_rows_promote_dataset_scoped_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        query_expansion_fields=["service_name", "question", "aliases"],
        question_intent_terms=["电话", "咨询", "查询"],
        question_anchor_bonus=0.9,
    )
    target_dataset_id = uuid.uuid4()
    other_dataset_id = uuid.uuid4()
    target_chunk_id = uuid.uuid4()
    other_chunk_id = uuid.uuid4()

    records = [
        {
            "content": "事项名称：重名查询\n咨询方式：0519-00000000",
            "score": 0.68,
            "title": "wrong.txt",
            "metadata": {"dataset_id": str(target_dataset_id), "service_name": "重名查询"},
        }
    ]
    rows = [
        {
            "chunk_id": target_chunk_id,
            "document_id": uuid.uuid4(),
            "dataset_id": target_dataset_id,
            "chunk_index": 7,
            "page_number": None,
            "filename": "target.txt",
            "content": "事项名称：学区划分查询\n咨询方式：0519-88888888",
            "metadata": {
                "service_name": "学区划分查询",
                "service_aliases": ["天宁区学区划分查询"],
                "source_record_id": "expected-record",
                "chunk_python_plugin": _DEMO_PLUGIN_REF,
            },
        },
        {
            "chunk_id": other_chunk_id,
            "document_id": uuid.uuid4(),
            "dataset_id": other_dataset_id,
            "chunk_index": 1,
            "page_number": None,
            "filename": "other.txt",
            "content": "事项名称：学区划分查询\n咨询方式：0519-99999999",
            "metadata": {
                "service_name": "学区划分查询",
                "source_record_id": "wrong-dataset-record",
                "chunk_python_plugin": _DEMO_PLUGIN_REF,
            },
        },
    ]

    fallback_records = dify_api._metadata_anchor_fallback_records_from_rows(
        rows,
        dataset_ids=[target_dataset_id],
        query="天宁区学区划分查询咨询电话是多少",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=records,
    )

    assert len(fallback_records) == 1
    assert fallback_records[0]["metadata"]["source_record_id"] == "expected-record"
    assert fallback_records[0]["metadata"]["dataset_id"] == str(target_dataset_id)
    assert fallback_records[0]["metadata"]["dify_metadata_anchor_fallback"] is True
    assert fallback_records[0]["score"] > records[0]["score"]


def test_dify_metadata_anchor_fallback_rows_skip_when_question_anchor_already_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        question_intent_terms=["影响", "诉权"],
        question_anchor_bonus=0.9,
    )
    dataset_id = uuid.uuid4()
    existing_records = [
        {
            "content": "问题：网上申请调解后，是否影响法定诉权？\n答案：不影响。",
            "score": 0.91,
            "title": "qa.txt",
            "metadata": {
                "dataset_id": str(dataset_id),
                "question": "网上申请调解后，是否影响法定诉权？",
                "chunk_kind": "qa_pair",
                "chunk_python_plugin": _DEMO_PLUGIN_REF,
            },
        }
    ]

    fallback_records = dify_api._metadata_anchor_fallback_records_from_rows(
        [
            {
                "chunk_id": uuid.uuid4(),
                "document_id": uuid.uuid4(),
                "dataset_id": dataset_id,
                "chunk_index": 2,
                "page_number": None,
                "filename": "qa.txt",
                "content": "问题：网上申请调解后，是否影响法定诉权？\n答案：不影响。",
                "metadata": {
                    "question": "网上申请调解后，是否影响法定诉权？",
                    "chunk_kind": "qa_pair",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                },
            }
        ],
        dataset_ids=[dataset_id],
        query="网上申请调解后，是否影响法定诉权？",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=existing_records,
    )

    assert fallback_records == []


def test_dify_question_anchor_strength_tolerates_minor_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)

    record = {
        "content": "问题：网上申请调解后，是否影响法定诉权？\n答案：不影响。",
        "score": 0.7,
        "title": "qa.txt",
        "metadata": {
            "question": "网上申请调解后，是否影响法定诉权？",
            "chunk_kind": "qa_pair",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }

    strength = dify_api._record_question_anchor_strength(
        record,
        query="网上申请调解是否影响法定诉权",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert strength >= 0.8


def test_dify_metadata_anchor_fallback_rows_promote_near_question_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api, question_anchor_bonus=0.9)
    dataset_id = uuid.uuid4()

    fallback_records = dify_api._metadata_anchor_fallback_records_from_rows(
        [
            {
                "chunk_id": uuid.uuid4(),
                "document_id": uuid.uuid4(),
                "dataset_id": dataset_id,
                "chunk_index": 2,
                "page_number": None,
                "filename": "qa.txt",
                "content": "问题：网上申请调解后，是否影响法定诉权？\n答案：不影响。",
                "metadata": {
                    "question": "网上申请调解后，是否影响法定诉权？",
                    "chunk_kind": "qa_pair",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                    "source_record_id": "qa-expected",
                },
            }
        ],
        dataset_ids=[dataset_id],
        query="网上申请调解是否影响法定诉权",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[],
    )

    assert len(fallback_records) == 1
    assert fallback_records[0]["metadata"]["source_record_id"] == "qa-expected"
    assert fallback_records[0]["score"] >= 0.86


def test_dify_metadata_anchor_fallback_rows_drop_anchor_only_qa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api, question_anchor_bonus=0.9)
    dataset_id = uuid.uuid4()

    fallback_records = dify_api._metadata_anchor_fallback_records_from_rows(
        [
            {
                "chunk_id": uuid.uuid4(),
                "document_id": uuid.uuid4(),
                "dataset_id": dataset_id,
                "chunk_index": 2,
                "page_number": None,
                "filename": "qa-anchor.txt",
                "content": "检索锚点：Alpha Desk；问题：Alpha Desk",
                "metadata": {
                    "question": "Alpha Desk",
                    "chunk_kind": "qa_pair",
                    "gov_knowledge_type": "qa",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                    "source_record_id": "anchor-only",
                },
            }
        ],
        dataset_ids=[dataset_id],
        query="我要办理“Alpha Desk”，需要哪些材料？同时告诉我在哪里办理、是否收费。",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[],
    )

    assert fallback_records == []


def test_dify_metadata_anchor_fallback_composes_exact_anchor_slots_before_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        anchor_binding={
            "enabled": True,
            "anchor_fields": ["case_title"],
            "slot_fields": ["section_type"],
        },
        query_expansion_values=[
            {"metadata": "section_type", "value": "related_services", "terms": ["涉及事项"]},
            {"metadata": "section_type", "value": "materials", "terms": ["材料"]},
            {"metadata": "section_type", "value": "operation_entry", "terms": ["办理入口"]},
        ],
        mixed_intent_subject_terms=["涉及事项", "材料", "办理入口"],
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_MAX_RECORDS",
        2,
        raising=False,
    )
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()

    def row(section_type: str, index: int) -> dict[str, object]:
        label = {
            "related_services": "涉及事项",
            "materials": "申请材料",
            "operation_entry": "系统入口",
        }[section_type]
        return {
            "chunk_id": uuid.uuid4(),
            "document_id": document_id,
            "dataset_id": dataset_id,
            "chunk_index": index,
            "page_number": None,
            "filename": "alpha.txt",
            "content": f"一件事：Alpha Package\n章节：{label}\n{label}正文。",
            "metadata": {
                "case_title": "Alpha Package",
                "section_type": section_type,
                "section_label": label,
                "source_record_id": "alpha",
                "chunk_python_plugin": _DEMO_PLUGIN_REF,
            },
        }

    fallback_records = dify_api._metadata_anchor_fallback_records_from_rows(
        [
            row("operation_entry", 1),
            row("related_services", 2),
            row("materials", 99),
        ],
        dataset_ids=[dataset_id],
        query="我要办“Alpha Package”，涉及事项、材料和办理入口",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[],
    )

    assert len(fallback_records) == 1
    assert fallback_records[0]["metadata"]["dify_composite_exact_anchor_slots"] is True
    assert set(fallback_records[0]["metadata"]["dify_composite_section_types"]) == {
        "related_services",
        "materials",
        "operation_entry",
    }
    assert "申请材料正文" in fallback_records[0]["content"]


def test_dify_metadata_anchor_fallback_composes_unquoted_exact_anchor_slots_before_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        anchor_binding={
            "enabled": True,
            "anchor_fields": ["case_title"],
            "slot_fields": ["section_type"],
        },
        query_expansion_values=[
            {"metadata": "section_type", "value": "related_services", "terms": ["涉及事项"]},
            {"metadata": "section_type", "value": "materials", "terms": ["申请材料"]},
            {"metadata": "section_type", "value": "channels", "terms": ["办理渠道"]},
        ],
        mixed_intent_subject_terms=["涉及事项", "申请材料", "办理渠道"],
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_MAX_RECORDS",
        2,
        raising=False,
    )
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()

    def row(section_type: str, index: int) -> dict[str, object]:
        label = {
            "related_services": "涉及事项",
            "materials": "申请材料",
            "channels": "办理渠道",
        }[section_type]
        return {
            "chunk_id": uuid.uuid4(),
            "document_id": document_id,
            "dataset_id": dataset_id,
            "chunk_index": index,
            "page_number": None,
            "filename": "one-thing.txt",
            "content": f"一件事：Alpha Package\n章节：{label}\n{label}正文。",
            "metadata": {
                "case_title": "Alpha Package",
                "section_type": section_type,
                "section_label": label,
                "source_record_id": "alpha",
                "chunk_python_plugin": _DEMO_PLUGIN_REF,
            },
        }

    fallback_records = dify_api._metadata_anchor_fallback_records_from_rows(
        [
            row("related_services", 1),
            row("channels", 2),
            row("materials", 99),
        ],
        dataset_ids=[dataset_id],
        query="Alpha Package是不是能办？涉及事项、申请材料、办理渠道，最好给我依据。",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[],
    )

    assert len(fallback_records) == 1
    assert fallback_records[0]["metadata"]["dify_composite_exact_anchor_slots"] is True
    assert fallback_records[0]["metadata"]["dify_composite_section_types"] == [
        "related_services",
        "materials",
        "channels",
    ]
    assert "章节：申请材料" in fallback_records[0]["content"]


def test_dify_exact_anchor_full_answer_does_not_skip_on_one_thing_partial_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        anchor_binding={
            "enabled": True,
            "anchor_fields": ["case_title"],
            "slot_fields": ["section_type"],
        },
        query_expansion_values=[
            {"metadata": "section_type", "value": "related_services", "terms": ["涉及事项"]},
            {"metadata": "section_type", "value": "materials", "terms": ["申请材料"]},
            {"metadata": "section_type", "value": "channels", "terms": ["办理渠道"]},
        ],
        mixed_intent_subject_terms=["涉及事项", "申请材料", "办理渠道"],
    )
    record = {
        "content": (
            "答案要点：一件事：Alpha Package；涉及事项：事项A；"
            "申请材料：材料B；办理渠道：线上办理"
        ),
        "score": 0.91,
        "title": "alpha-process.txt",
        "metadata": {
            "case_title": "Alpha Package",
            "section_type": "process",
            "chunk_kind": "one_thing_process",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }

    assert not dify_api._records_have_exact_anchor_full_answer(
        [record],
        query="Alpha Package是不是能办？涉及事项、申请材料、办理渠道，最好给我依据。",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )


def test_dify_question_bonus_does_not_promote_generic_one_thing_qa_over_specific_case_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        anchor_binding={
            "enabled": True,
            "anchor_fields": ["case_title"],
            "slot_fields": ["section_type"],
        },
        query_expansion_values=[
            {"metadata": "section_type", "value": "related_services", "terms": ["涉及事项"]},
            {"metadata": "section_type", "value": "materials", "terms": ["申请材料"]},
            {"metadata": "section_type", "value": "channels", "terms": ["办理渠道"]},
        ],
        mixed_intent_subject_terms=["涉及事项", "申请材料", "办理渠道"],
    )
    generic_qa = {
        "content": "答案要点：答案：企业开办一件事材料和流程。",
        "score": 0.6,
        "title": "qa.txt",
        "metadata": {
            "question": "公积金企业开办“一件事”涉及的办理事项，材料、流程有些？",
            "chunk_kind": "qa_pair",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }
    exact_section = {
        "content": "答案要点：一件事：残疾人服务“一件事”；申请材料：申请表。",
        "score": 0.72,
        "title": "one-thing.txt",
        "metadata": {
            "case_title": "残疾人服务“一件事”",
            "section_type": "materials",
            "chunk_kind": "one_thing_materials",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }
    query = "残疾人服务“一件事”是不是能办？我这边比较急，涉及事项、申请材料、办理渠道，最好给我依据。"

    assert dify_api._record_question_intent_bonus(
        generic_qa,
        query=query,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    ) == 0.0
    assert dify_api._record_rank_score(
        exact_section,
        query=query,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    ) > dify_api._record_rank_score(
        generic_qa,
        query=query,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )


def test_dify_response_compaction_keeps_single_exact_anchor_answer_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        anchor_binding={
            "enabled": True,
            "anchor_fields": ["service_name"],
            "slot_fields": [],
        },
    )
    records = [
        {
            "content": "事项名称：Alpha Check\n办理地点：A窗口\n收费情况：不收费\n办理材料：申请表",
            "score": 0.83,
            "title": "alpha.txt",
            "metadata": {"service_name": "Alpha Check", "chunk_python_plugin": _DEMO_PLUGIN_REF},
        },
        {
            "content": "事项名称：Beta Check\n办理地点：B窗口\n收费情况：不收费",
            "score": 0.82,
            "title": "beta.txt",
            "metadata": {"service_name": "Beta Check", "chunk_python_plugin": _DEMO_PLUGIN_REF},
        },
    ]

    compacted = dify_api._compact_records_for_response(
        records,
        query="Alpha Check 材料 地点 收不收费",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert [record["title"] for record in compacted] == ["alpha.txt"]


def test_dify_metadata_anchor_fallback_prefers_region_anchored_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api, question_anchor_bonus=0.9)
    dataset_id = uuid.uuid4()
    question = "2025年7月1日至2026年6月30日期间，常州市女职工生育一次性营养补助费的计发标准是多少？"

    fallback_records = dify_api._metadata_anchor_fallback_records_from_rows(
        [
            {
                "chunk_id": uuid.uuid4(),
                "document_id": uuid.uuid4(),
                "dataset_id": dataset_id,
                "chunk_index": 1,
                "page_number": None,
                "filename": "department.xlsx",
                "content": f"问题：{question}\n答案：2705元。",
                "metadata": {
                    "question": question,
                    "source_record_id": "department-record",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                },
            },
            {
                "chunk_id": uuid.uuid4(),
                "document_id": uuid.uuid4(),
                "dataset_id": dataset_id,
                "chunk_index": 2,
                "page_number": None,
                "filename": "city-12345.txt",
                "content": f"问题：{question}\n答案：2705元。",
                "metadata": {
                    "district": "常州市本级",
                    "question": question,
                    "source_record_id": "city-record",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                },
            },
        ],
        dataset_ids=[dataset_id],
        query=question,
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[],
    )

    assert [record["metadata"]["source_record_id"] for record in fallback_records] == [
        "city-record",
        "department-record",
    ]


def test_dify_metadata_anchor_fallback_rows_promote_near_service_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    dataset_id = uuid.uuid4()

    fallback_records = dify_api._metadata_anchor_fallback_records_from_rows(
        [
            {
                "chunk_id": uuid.uuid4(),
                "document_id": uuid.uuid4(),
                "dataset_id": dataset_id,
                "chunk_index": 1,
                "page_number": None,
                "filename": "service.txt",
                "content": "事项名称：学区划分查询\n咨询方式：0519-69660631",
                "metadata": {
                    "district": "天宁区",
                    "service_name": "学区划分查询",
                    "source_record_id": "service-expected",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                },
            }
        ],
        dataset_ids=[dataset_id],
        query="天宁区学区查询咨询电话是多少",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[],
    )

    assert len(fallback_records) == 1
    assert fallback_records[0]["metadata"]["source_record_id"] == "service-expected"
    assert fallback_records[0]["score"] >= 0.72


def test_dify_metadata_anchor_db_fallback_prefers_service_anchor_before_broad_question_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        anchor_fields=[
            {
                "metadata": "city",
                "role": "administrative_area",
                "aliases": {"常州市": ["常州市", "常州"]},
            }
        ],
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    service_row = {
        "chunk_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "dataset_id": dataset_id,
        "chunk_index": 1,
        "page_number": None,
        "filename": "service.txt",
        "content": "事项名称：重要工业产品生产许可（食品相关产品）名称变更\n咨询方式：0519-85588357、0519-85588359",
        "metadata": {
            "district": "常州市",
            "service_name": "重要工业产品生产许可（食品相关产品）名称变更",
            "source_record_id": "service-expected",
            "knowledge_section": "01政务服务事项知识",
            "gov_knowledge_type": "service_item",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }
    qa_row = {
        "chunk_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "dataset_id": dataset_id,
        "chunk_index": 2,
        "page_number": None,
        "filename": "qa.txt",
        "content": "问题：目前生产哪些产品需要领取工业产品生产许可证？\n答案：部分工业产品需要许可证。",
        "metadata": {
            "district": "常州市本级",
            "question": "目前生产哪些产品需要领取工业产品生产许可证？",
            "source_record_id": "qa-wrong",
            "knowledge_section": "03常州市常见问题",
            "gov_knowledge_type": "qa",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }
    service_query_pattern_counts: list[int] = []

    def _condition_values(condition):  # noqa: ANN001, ANN202
        values: list[str] = []

        def walk(node):  # noqa: ANN001, ANN202
            value = getattr(node, "value", None)
            if isinstance(value, str):
                values.append(value)
            elif isinstance(value, dict):
                for key, raw_items in value.items():
                    values.append(str(key))
                    items = raw_items if isinstance(raw_items, list | tuple | set) else [raw_items]
                    values.extend(str(item) for item in items)
            for attr in ("left", "right"):
                child = getattr(node, attr, None)
                if child is not None:
                    walk(child)
            clauses = getattr(node, "clauses", None)
            if clauses is not None:
                for child in clauses:
                    walk(child)

        walk(condition)
        return values

    class _FakeQuery:
        def __init__(self) -> None:
            self._condition = None

        def join(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def filter(self, *_conditions):  # noqa: ANN002, ANN202
            self._condition = _conditions[-1] if _conditions else None
            return self

        def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def limit(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def all(self):  # noqa: ANN202
            values = _condition_values(self._condition)
            fields = set(values)
            patterns = [value for value in values if value.startswith("%")]
            if "service_name" in fields:
                service_query_pattern_counts.append(len(patterns))
                if any(value == "重要工业产品生产许可（食品相关产品）名称变更" for value in values):
                    return [service_row]
                if len(patterns) == 1 and any("工业产品" in pattern for pattern in patterns):
                    return [service_row]
                return []
            if fields.intersection({"retrieval_intents", "query_intents", "intent_terms"}) and any(
                "工业产品" in value for value in values
            ):
                return [qa_row]
            if (
                "question" in fields
                and any("工业产品生产" in pattern for pattern in patterns)
                and not all("常州市重要" in pattern for pattern in patterns)
            ):
                return [qa_row]
            return []

    class _FakeDB:
        def execute(self, _statement):  # noqa: ANN001, ANN202
            return None

        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return _FakeQuery()

        def rollback(self) -> None:
            return None

    fallback_records = dify_api._metadata_anchor_db_fallback_records(
        db=_FakeDB(),
        tenant_id=tenant_id,
        dataset_ids=[dataset_id],
        query="常州市重要工业产品生产许可（食品相关产品）名称变更：办理地点、办理材料？",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[],
    )

    assert len(fallback_records) == 1
    assert fallback_records[0]["metadata"]["source_record_id"] == "service-expected"
    assert service_query_pattern_counts[0] == 0


def test_dify_metadata_anchor_db_fallback_checks_exact_service_name_first_for_plain_service_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    service_row = {
        "chunk_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "dataset_id": dataset_id,
        "chunk_index": 1,
        "page_number": None,
        "filename": "service.txt",
        "content": "事项名称：保健食品广告审查\n行使层级：市级\n办件类型：承诺件",
        "metadata": {
            "district": "常州市",
            "service_name": "保健食品广告审查",
            "source_record_id": "service-expected",
            "knowledge_section": "01政务服务事项知识",
            "gov_knowledge_type": "service_item",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }
    seen_values_by_query: list[list[str]] = []

    def _condition_values(condition):  # noqa: ANN001, ANN202
        values: list[str] = []

        def walk(node):  # noqa: ANN001, ANN202
            value = getattr(node, "value", None)
            if isinstance(value, str):
                values.append(value)
            elif isinstance(value, dict):
                for key, raw_items in value.items():
                    values.append(str(key))
                    items = raw_items if isinstance(raw_items, list | tuple | set) else [raw_items]
                    values.extend(str(item) for item in items)
            for attr in ("left", "right"):
                child = getattr(node, attr, None)
                if child is not None:
                    walk(child)
            clauses = getattr(node, "clauses", None)
            if clauses is not None:
                for child in clauses:
                    walk(child)

        walk(condition)
        return values

    class _FakeQuery:
        def __init__(self) -> None:
            self._condition = None

        def join(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def filter(self, *_conditions):  # noqa: ANN002, ANN202
            self._condition = _conditions[-1] if _conditions else None
            return self

        def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def limit(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def all(self):  # noqa: ANN202
            values = _condition_values(self._condition)
            seen_values_by_query.append(values)
            if values.count("service_name") == 1 and values.count("保健食品广告审查") == 1:
                return [service_row]
            return []

    class _FakeDB:
        def execute(self, _statement):  # noqa: ANN001, ANN202
            return None

        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return _FakeQuery()

        def rollback(self) -> None:
            return None

    fallback_records = dify_api._metadata_anchor_db_fallback_records(
        db=_FakeDB(),
        tenant_id=tenant_id,
        dataset_ids=[dataset_id],
        query="保健食品广告审查",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[],
    )

    assert len(fallback_records) == 1
    assert fallback_records[0]["metadata"]["source_record_id"] == "service-expected"
    assert seen_values_by_query
    first_values = seen_values_by_query[0]
    assert first_values.count("service_name") == 1
    assert "case_title" not in first_values
    assert "service_aliases" not in first_values
    assert "district" not in first_values
    assert not any(value.startswith("%") for value in first_values)


def test_dify_metadata_anchor_db_fallback_prefers_qa_for_slot_question_before_service_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        query_expansion_values=[
            {"metadata": "section_type", "value": "channels", "terms": ["在哪里办理", "哪里办理"]},
        ],
        question_anchor_bonus=0.9,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    service_row = {
        "chunk_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "dataset_id": dataset_id,
        "chunk_index": 1,
        "page_number": None,
        "filename": "service.txt",
        "content": "事项名称：企业社会保险登记\n办理地点：市政务服务中心一楼A区",
        "metadata": {
            "district": "区域甲",
            "service_name": "企业社会保险登记",
            "source_record_id": "service-wrong",
            "knowledge_section": "01政务服务事项知识",
            "gov_knowledge_type": "service_item",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }
    qa_row = {
        "chunk_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "dataset_id": dataset_id,
        "chunk_index": 2,
        "page_number": None,
        "filename": "qa.txt",
        "content": "问题：请问可以在哪里办理企业社会保险登记？\n答案：可以在区域甲政务服务中心一楼大厅C区办理。",
        "metadata": {
            "district": "区域甲",
            "question": "请问可以在哪里办理企业社会保险登记？",
            "source_record_id": "qa-expected",
            "knowledge_section": "06各区常见问题",
            "gov_knowledge_type": "qa",
            "chunk_kind": "qa_pair",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }

    def _condition_values(condition):  # noqa: ANN001, ANN202
        values: list[str] = []

        def walk(node):  # noqa: ANN001, ANN202
            value = getattr(node, "value", None)
            if isinstance(value, str):
                values.append(value)
            elif isinstance(value, dict):
                for key, raw_items in value.items():
                    values.append(str(key))
                    items = raw_items if isinstance(raw_items, list | tuple | set) else [raw_items]
                    values.extend(str(item) for item in items)
            for attr in ("left", "right"):
                child = getattr(node, attr, None)
                if child is not None:
                    walk(child)
            clauses = getattr(node, "clauses", None)
            if clauses is not None:
                for child in clauses:
                    walk(child)

        walk(condition)
        return values

    class _FakeQuery:
        def __init__(self) -> None:
            self._condition = None

        def join(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def filter(self, *_conditions):  # noqa: ANN002, ANN202
            self._condition = _conditions[-1] if _conditions else None
            return self

        def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def limit(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def all(self):  # noqa: ANN202
            values = _condition_values(self._condition)
            fields = set(values)
            patterns = [value for value in values if value.startswith("%")]
            if "question" in fields and any("企业社会保险登记" in pattern for pattern in patterns):
                return [qa_row]
            if "service_name" in fields and any("企业社会保险登记" in pattern for pattern in patterns):
                return [service_row]
            return []

    class _FakeDB:
        def execute(self, _statement):  # noqa: ANN001, ANN202
            return None

        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return _FakeQuery()

        def rollback(self) -> None:
            return None

    fallback_records = dify_api._metadata_anchor_db_fallback_records(
        db=_FakeDB(),
        tenant_id=tenant_id,
        dataset_ids=[dataset_id],
        query="麻烦查一下区域甲在哪里办理企业社会保险登记，区域甲政务服务中心一楼大厅C区、东方东路168号。",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[],
    )

    assert len(fallback_records) == 1
    assert fallback_records[0]["metadata"]["source_record_id"] == "qa-expected"


def test_dify_metadata_anchor_db_fallback_continues_alias_scan_for_slot_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        question_anchor_bonus=0.9,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    broad_row = {
        "chunk_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "dataset_id": dataset_id,
        "chunk_index": 1,
        "page_number": None,
        "filename": "id-card.txt",
        "content": "问题：核发居民身份证（补领）\n答案：本省户籍人员凭户口簿、驾驶证、居住证、护照其中之一办理。",
        "metadata": {
            "question": "核发居民身份证（补领）",
            "aliases": ["居民身份证补领需要什么材料"],
            "source_record_id": "broad-id-card",
            "knowledge_section": "03常州市常见问题",
            "gov_knowledge_type": "qa",
            "chunk_kind": "qa_pair",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }
    material_row = {
        "chunk_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "dataset_id": dataset_id,
        "chunk_index": 2,
        "page_number": None,
        "filename": "id-card.txt",
        "content": (
            "问题：省外和省内人员补办身份证的办理材料和办理时限分别是什么？\n"
            "答案：居民户口簿、有效身份证件之一；省外户籍居民补领还需合法稳定就业、就学、居住的其中一种证明材料。"
        ),
        "metadata": {
            "question": "省外和省内人员补办身份证的办理材料和办理时限分别是什么？",
            "aliases": ["身份证补办"],
            "source_record_id": "material-id-card",
            "knowledge_section": "03常州市常见问题",
            "gov_knowledge_type": "qa",
            "chunk_kind": "qa_pair",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }

    def _condition_values(condition):  # noqa: ANN001, ANN202
        values: list[str] = []

        def walk(node):  # noqa: ANN001, ANN202
            value = getattr(node, "value", None)
            if isinstance(value, str):
                values.append(value)
            elif isinstance(value, dict):
                for key, raw_items in value.items():
                    values.append(str(key))
                    items = raw_items if isinstance(raw_items, list | tuple | set) else [raw_items]
                    values.extend(str(item) for item in items)
            for attr in ("left", "right"):
                child = getattr(node, attr, None)
                if child is not None:
                    walk(child)
            clauses = getattr(node, "clauses", None)
            if clauses is not None:
                for child in clauses:
                    walk(child)

        walk(condition)
        return values

    class _FakeQuery:
        def __init__(self) -> None:
            self._condition = None

        def join(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def filter(self, *_conditions):  # noqa: ANN002, ANN202
            self._condition = _conditions[-1] if _conditions else None
            return self

        def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def limit(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def all(self):  # noqa: ANN202
            values = _condition_values(self._condition)
            fields = set(values)
            patterns = [value for value in values if value.startswith("%")]
            if "aliases" in fields and any("居民身份证补领需要什么材料" in value for value in values):
                return [broad_row]
            if any("身份证补" in pattern for pattern in patterns):
                return [material_row]
            return []

    class _FakeDB:
        def execute(self, _statement):  # noqa: ANN001, ANN202
            return None

        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return _FakeQuery()

        def rollback(self) -> None:
            return None

    fallback_records = dify_api._metadata_anchor_db_fallback_records(
        db=_FakeDB(),
        tenant_id=tenant_id,
        dataset_ids=[dataset_id],
        query="居民身份证补领需要什么材料",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[],
    )

    assert fallback_records[0]["metadata"]["source_record_id"] == "material-id-card"


def test_dify_metadata_anchor_db_fallback_sets_statement_timeout_and_rolls_back_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_STATEMENT_TIMEOUT_MS",
        1234,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _FailingQuery:
        def join(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def limit(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def all(self):  # noqa: ANN202
            raise RuntimeError("canceling statement due to statement timeout")

    class _FakeDB:
        def __init__(self) -> None:
            self.executed: list[str] = []
            self.rollback_count = 0

        def execute(self, statement):  # noqa: ANN001, ANN202
            self.executed.append(str(statement))

        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return _FailingQuery()

        def rollback(self) -> None:
            self.rollback_count += 1

    db = _FakeDB()

    fallback_records = dify_api._metadata_anchor_db_fallback_records(
        db=db,
        tenant_id=tenant_id,
        dataset_ids=[dataset_id],
        query="常州市工伤保险待遇恢复在哪里办理",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[],
    )

    assert fallback_records == []
    assert any("statement_timeout" in statement and "1234" in statement for statement in db.executed)
    assert db.rollback_count == 1


def test_dify_metadata_anchor_worker_owns_and_closes_its_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    class _WorkerSession:
        closed = False

        def close(self) -> None:
            self.closed = True

    worker_session = _WorkerSession()
    observed_sessions: list[object] = []

    monkeypatch.setattr(dify_api, "SessionLocal", lambda: worker_session, raising=True)
    monkeypatch.setattr(
        dify_api,
        "_metadata_anchor_db_fallback_records",
        lambda **kwargs: observed_sessions.append(kwargs["db"]) or [],
        raising=True,
    )

    result = dify_api._metadata_anchor_db_fallback_records_with_managed_session(
        tenant_id=uuid.uuid4(),
        dataset_ids=[],
        query="Alpha Desk",
        top_k=1,
    )

    assert result == []
    assert observed_sessions == [worker_session]
    assert worker_session.closed is True


def test_dify_metadata_anchor_db_fallback_caps_each_statement_to_remaining_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _SlowEmptyQuery:
        def join(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def limit(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def all(self):  # noqa: ANN202
            time.sleep(0.03)
            return []

    class _FakeDB:
        def __init__(self) -> None:
            self.executed: list[str] = []
            self.rollback_count = 0

        def execute(self, statement):  # noqa: ANN001, ANN202
            self.executed.append(str(statement))

        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return _SlowEmptyQuery()

        def rollback(self) -> None:
            self.rollback_count += 1

    db = _FakeDB()
    fallback_records = dify_api._metadata_anchor_db_fallback_records(
        db=db,
        tenant_id=tenant_id,
        dataset_ids=[dataset_id],
        query="常州市工伤保险待遇恢复在哪里办理",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[],
        statement_timeout_ms_override=80,
        max_elapsed_ms=90,
    )
    statement_timeouts = [
        int(statement.rsplit("=", 1)[1].strip())
        for statement in db.executed
        if "statement_timeout" in statement
    ]

    assert fallback_records == []
    assert len(statement_timeouts) >= 2
    assert statement_timeouts[0] <= 80
    assert statement_timeouts[-1] < statement_timeouts[0]
    assert db.rollback_count >= 1


def test_dify_retrieval_uses_rag_before_question_anchor_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls = {"rag": 0, "metadata_anchor": 0}

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUPPLEMENT_ENABLED",
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
    _patch_demo_policy(monkeypatch, dify_api, question_anchor_bonus=0.9)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        calls["rag"] += 1
        return [
            {
                "chunk_content": "问题：网上申请调解后，是否影响法定诉权？\n答案：不影响。",
                "relevance_score": 0.91,
                "document_name": "qa-rag.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {
                    "dataset_id": str(dataset_id),
                    "question": "网上申请调解后，是否影响法定诉权？",
                    "chunk_kind": "qa_pair",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                },
            }
        ]

    def _fake_metadata_anchor_db_fallback_records(**kwargs):  # noqa: ANN003, ANN202
        calls["metadata_anchor"] += 1
        raise AssertionError("strong RAG question anchor should not need metadata fallback")

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)
    monkeypatch.setattr(
        dify_api,
        "_metadata_anchor_db_fallback_records",
        _fake_metadata_anchor_db_fallback_records,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "网上申请调解是否影响法定诉权",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls == {"rag": 1, "metadata_anchor": 0}
    body = res.json()
    assert body["records"][0]["title"] == "qa-rag.txt"
    assert "不影响" in body["records"][0]["content"]


def test_dify_retrieval_uses_question_anchor_preflight_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls = {"rag": 0, "metadata_anchor": 0}

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    _patch_demo_policy(monkeypatch, dify_api, question_anchor_bonus=0.9)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        calls["rag"] += 1
        raise AssertionError("strong question metadata preflight should skip RAG")

    def _fake_metadata_anchor_db_fallback_records(**kwargs):  # noqa: ANN003, ANN202
        calls["metadata_anchor"] += 1
        assert kwargs["existing_records"] == []
        return [
            {
                "content": "问题：网上申请调解后，是否影响法定诉权？\n答案：不影响。",
                "score": 0.97,
                "title": "qa-preflight.txt",
                "metadata": {
                    "dataset_id": str(dataset_id),
                    "question": "网上申请调解后，是否影响法定诉权？",
                    "chunk_kind": "qa_pair",
                    "source_record_id": "qa-preflight",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                    "dify_metadata_anchor_fallback": True,
                },
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(
        dify_api,
        "_metadata_anchor_db_fallback_records",
        _fake_metadata_anchor_db_fallback_records,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "网上申请调解是否影响法定诉权",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls == {"rag": 0, "metadata_anchor": 1}
    body = res.json()
    assert body["records"][0]["metadata"]["source_record_id"] == "qa-preflight"
    assert "不影响" in body["records"][0]["content"]


def test_dify_preflight_records_still_use_final_reranker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api
    from app.rag.reranker.types import RerankResult

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls = {"rag": 0, "metadata_anchor": 0, "rerank": 0}

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(dify_api.settings, "ENABLE_RERANKER", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RERANKER_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "RERANKER_PROVIDER", "unit", raising=False)
    monkeypatch.setattr(dify_api.settings, "RERANKER_TOP_N", 2, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    _patch_demo_policy(monkeypatch, dify_api, question_anchor_bonus=0.9)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        calls["rag"] += 1
        raise AssertionError("metadata preflight should still skip RAG")

    def _fake_metadata_anchor_db_fallback_records(**_kwargs):  # noqa: ANN003, ANN202
        calls["metadata_anchor"] += 1
        return [
            {
                "content": "问题：网上申请调解后，是否影响法定诉权？\n答案：请联系窗口咨询。",
                "score": 0.99,
                "title": "broad.txt",
                "metadata": {
                    "dataset_id": str(dataset_id),
                    "question": "网上申请调解后，是否影响法定诉权？",
                    "chunk_kind": "qa_pair",
                    "source_record_id": "broad",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                    "dify_metadata_anchor_fallback": True,
                },
            },
            {
                "content": "问题：网上申请调解后，是否影响法定诉权？\n答案：不影响法定诉权。",
                "score": 0.72,
                "title": "exact.txt",
                "metadata": {
                    "dataset_id": str(dataset_id),
                    "question": "网上申请调解后，是否影响法定诉权？",
                    "chunk_kind": "qa_pair",
                    "source_record_id": "exact",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                    "dify_metadata_anchor_fallback": True,
                },
            },
        ]

    class _FakeReranker:
        def rerank(self, query, candidates, **_kwargs):  # noqa: ANN001, ANN202, ARG002
            calls["rerank"] += 1
            ordered_ids = [
                candidate.id for candidate in candidates if "不影响法定诉权" in candidate.text
            ] + [candidate.id for candidate in candidates if "不影响法定诉权" not in candidate.text]
            return RerankResult(
                ordered_ids=ordered_ids,
                score_map={ordered_ids[0]: 0.98, ordered_ids[1]: 0.12},
                provider="unit",
                model_used="unit-reranker",
                elapsed_sec=0.01,
            )

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(
        dify_api,
        "_metadata_anchor_db_fallback_records",
        _fake_metadata_anchor_db_fallback_records,
        raising=True,
    )
    monkeypatch.setattr(dify_api, "get_reranker", lambda _provider: _FakeReranker(), raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "网上申请调解是否影响法定诉权",
            "retrieval_setting": {"top_k": 2, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls == {"rag": 0, "metadata_anchor": 1, "rerank": 1}
    top = res.json()["records"][0]
    assert top["metadata"]["source_record_id"] == "exact"
    assert top["metadata"]["dify_final_rerank"] is True
    assert top["metadata"]["reranker_provider"] == "unit"
    assert top["score"] == pytest.approx(0.98)


@pytest.mark.asyncio
async def test_dify_final_rerank_cannot_override_exact_question_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api
    from app.rag.reranker.types import RerankResult

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        question_intent_terms=["材料"],
        question_anchor_bonus=0.9,
    )
    monkeypatch.setattr(dify_api.settings, "ENABLE_RERANKER", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RERANKER_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "RERANKER_PROVIDER", "unit", raising=False)

    correct = {
        "content": "问题：核发居民身份证（补领）\n答案：居民户口簿、有效身份证件之一。",
        "score": 0.99,
        "title": "id-card.txt",
        "metadata": {
            "question": "核发居民身份证（补领）",
            "primary_alias": "居民身份证补领需要什么材料",
            "aliases": ["居民身份证补领需要什么材料"],
            "chunk_kind": "qa_pair",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }
    wrong = {
        "content": "问题：核发居民身份证（首次申领）\n答案：居民户口簿。",
        "score": 0.99,
        "title": "id-card.txt",
        "metadata": {
            "question": "核发居民身份证（首次申领）",
            "chunk_kind": "qa_pair",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }

    class _FakeReranker:
        def rerank(self, _query, candidates, **_kwargs):  # noqa: ANN001, ANN202
            wrong_id = next(candidate.id for candidate in candidates if "首次申领" in candidate.text)
            correct_id = next(candidate.id for candidate in candidates if "补领" in candidate.text)
            return RerankResult(
                ordered_ids=[wrong_id, correct_id],
                score_map={wrong_id: 0.72, correct_id: 0.70},
                provider="unit",
                model_used="unit-reranker",
                elapsed_sec=0.01,
            )

    monkeypatch.setattr(dify_api, "get_reranker", lambda _provider: _FakeReranker(), raising=True)

    reranked = await dify_api._final_rerank_records_for_query(
        [correct, wrong],
        query="居民身份证补领需要什么材料",
        top_k=2,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert reranked[0]["metadata"]["question"] == "核发居民身份证（补领）"
    assert reranked[0]["metadata"]["dify_final_rerank"] is True


def test_dify_mixed_intent_caps_internal_candidates_without_disabling_retrieval_reranker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls: list[dict[str, object]] = []
    _patch_demo_policy(monkeypatch, dify_api)

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUPPLEMENT_ENABLED",
        False,
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "ENABLE_RERANKER", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RERANKER_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MIN", 20, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MULTIPLIER", 4, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX", 50, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        calls.append(dict(kwargs))
        return [
            {
                "chunk_content": "答案：Alpha。",
                "relevance_score": 0.8,
                "document_name": "alpha.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {"dataset_id": str(dataset_id)},
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
            "query": "Alpha在哪里？另外Beta怎么处理？",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls
    assert calls[0]["top_k"] == 5
    assert calls[0]["requested_top_k"] == 5
    assert calls[0]["enable_reranker"] is True


def test_dify_retrieval_uses_plugin_question_intent_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls = {"rag": 0, "metadata_anchor": 0}

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": {{"dataset_ids": ["{dataset_id}"], "plugin_refs": ["{_DEMO_PLUGIN_REF}"]}}}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    _patch_demo_policy(monkeypatch, dify_api, question_anchor_bonus=0.9)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        calls["rag"] += 1
        raise AssertionError("plugin question intent metadata preflight should skip RAG")

    def _fake_metadata_anchor_db_fallback_records(**kwargs):  # noqa: ANN003, ANN202
        calls["metadata_anchor"] += 1
        assert kwargs["existing_records"] == []
        assert kwargs["policy_plugin_refs"] == (_DEMO_PLUGIN_REF,)
        return [
            {
                "content": "问题：租房提取条件\n答案：连续足额缴存住房公积金满3个月。",
                "score": 0.97,
                "title": "提取类.xlsx",
                "metadata": {
                    "dataset_id": str(dataset_id),
                    "question": "租房提取条件",
                    "chunk_kind": "qa_pair",
                    "source_record_id": "rent-withdrawal-condition",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                    "dify_metadata_anchor_fallback": True,
                },
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(
        dify_api,
        "_metadata_anchor_db_fallback_records",
        _fake_metadata_anchor_db_fallback_records,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "租房提取条件",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls == {"rag": 0, "metadata_anchor": 1}
    body = res.json()
    assert body["records"][0]["metadata"]["source_record_id"] == "rent-withdrawal-condition"
    assert "连续足额缴存住房公积金满3个月" in body["records"][0]["content"]


def test_dify_retrieval_uses_short_query_question_anchor_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls = {"rag": 0, "metadata_anchor": 0}

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": {{"dataset_ids": ["{dataset_id}"], "plugin_refs": ["{_DEMO_PLUGIN_REF}"]}}}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    _patch_demo_policy(monkeypatch, dify_api, question_anchor_bonus=0.9)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        calls["rag"] += 1
        raise AssertionError("short query question metadata preflight should skip RAG")

    def _fake_metadata_anchor_db_fallback_records(**kwargs):  # noqa: ANN003, ANN202
        calls["metadata_anchor"] += 1
        assert kwargs["existing_records"] == []
        return [
            {
                "content": "问题：单位降比（缓缴）公积金\n答案：可按政策申请单位降比或缓缴。",
                "score": 0.97,
                "title": "缴存类.xlsx",
                "metadata": {
                    "dataset_id": str(dataset_id),
                    "question": "单位降比（缓缴）公积金",
                    "chunk_kind": "qa_pair",
                    "source_record_id": "housing-fund-ratio",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                    "dify_metadata_anchor_fallback": True,
                },
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(
        dify_api,
        "_metadata_anchor_db_fallback_records",
        _fake_metadata_anchor_db_fallback_records,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "单位降比（缓缴）公积金",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls == {"rag": 0, "metadata_anchor": 1}
    body = res.json()
    assert body["records"][0]["metadata"]["source_record_id"] == "housing-fund-ratio"


def test_dify_retrieval_supplements_question_anchor_when_rag_only_has_service_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls = {"rag": 0, "metadata_anchor": 0}

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED",
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
    _patch_demo_policy(monkeypatch, dify_api, question_anchor_bonus=0.9)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        calls["rag"] += 1
        return [
            {
                "chunk_content": "事项名称：劳动人事争议调解申请\n办理地点：服务中心窗口。",
                "relevance_score": 0.91,
                "document_name": "service-rag.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {
                    "dataset_id": str(dataset_id),
                    "service_name": "劳动人事争议调解申请",
                    "chunk_kind": "service_item_full",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                },
            }
        ]

    def _fake_metadata_anchor_db_fallback_records(**kwargs):  # noqa: ANN003, ANN202
        calls["metadata_anchor"] += 1
        return [
            {
                "content": "问题：网上申请调解后，是否影响法定诉权？\n答案：不影响。",
                "score": 0.97,
                "title": "qa.txt",
                "metadata": {
                    "dataset_id": str(dataset_id),
                    "question": "网上申请调解后，是否影响法定诉权？",
                    "chunk_kind": "qa_pair",
                    "source_record_id": "qa-expected",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                    "dify_metadata_anchor_fallback": True,
                },
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)
    monkeypatch.setattr(
        dify_api,
        "_metadata_anchor_db_fallback_records",
        _fake_metadata_anchor_db_fallback_records,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "网上申请调解是否影响法定诉权",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls == {"rag": 1, "metadata_anchor": 1}
    body = res.json()
    assert body["records"][0]["metadata"]["source_record_id"] == "qa-expected"
    assert "不影响" in body["records"][0]["content"]


def test_dify_retrieval_uses_service_anchor_preflight_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls = {"rag": 0, "metadata_anchor": 0}

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": {{"dataset_ids": ["{dataset_id}"], "plugin_refs": ["{_DEMO_PLUGIN_REF}"]}}}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    _patch_demo_policy(monkeypatch, dify_api)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        calls["rag"] += 1
        raise AssertionError("confident service metadata preflight should skip RAG")

    def _fake_metadata_anchor_db_fallback_records(**kwargs):  # noqa: ANN003, ANN202
        calls["metadata_anchor"] += 1
        return [
            {
                "content": "答案要点：咨询方式：0519-69660631\n\n原始证据：\n事项名称：学区划分查询",
                "score": 0.78,
                "title": "service.txt",
                "metadata": {
                    "dataset_id": str(dataset_id),
                    "district": "天宁区",
                    "service_name": "学区划分查询",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                    "dify_metadata_anchor_fallback": True,
                },
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)
    monkeypatch.setattr(
        dify_api,
        "_metadata_anchor_db_fallback_records",
        _fake_metadata_anchor_db_fallback_records,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "天宁区学区查询咨询电话是多少",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls == {"rag": 0, "metadata_anchor": 1}
    body = res.json()
    assert body["records"][0]["title"] == "service.txt"
    assert "0519-69660631" in body["records"][0]["content"]


def test_dify_preflight_anchor_content_uses_metadata_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls = {"rag": 0, "metadata_anchor": 0}

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": {{"dataset_ids": ["{dataset_id}"], "plugin_refs": ["{_DEMO_PLUGIN_REF}"]}}}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    response_hints = _demo_response_hints()
    response_hints["structured_labels"] = [  # type: ignore[index]
        *response_hints["structured_labels"],  # type: ignore[index]
        "检索锚点",
        "相似问法",
    ]
    _patch_demo_policy(monkeypatch, dify_api, question_anchor_bonus=1.15, response_hints=response_hints)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        calls["rag"] += 1
        raise AssertionError("answerful metadata preflight should skip RAG")

    def _fake_metadata_anchor_db_fallback_records(**kwargs):  # noqa: ANN003, ANN202
        calls["metadata_anchor"] += 1
        assert kwargs["existing_records"] == []
        metadata = {
            "dataset_id": str(dataset_id),
            "question": "核发居民身份证（换领）",
            "answer": (
                "事项名称：核发居民身份证（换领）；办理材料：居民身份证；"
                "办理地点：常州政务服务中心公安窗口；收费情况：收费20元"
            ),
            "chunk_kind": "qa_pair",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
            "dify_metadata_anchor_fallback": True,
        }
        content = dify_api._content_with_answer_hints(
            "检索锚点：核发居民身份证（换领）；常州市换身份证\n"
            "相似问法：身份证到期、换领身份证、身份证换证流程",
            metadata,
            query=kwargs["query"],
            policy_plugin_refs=kwargs["policy_plugin_refs"],
        )
        return [
            {
                "content": content,
                "score": 0.9,
                "title": "身份证知识.txt",
                "metadata": metadata,
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)
    monkeypatch.setattr(
        dify_api,
        "_metadata_anchor_db_fallback_records",
        _fake_metadata_anchor_db_fallback_records,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "我要办理“核发居民身份证（换领）”，需要哪些材料？同时告诉我在哪里办理、是否收费。",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls == {"rag": 0, "metadata_anchor": 1}
    content = res.json()["records"][0]["content"]
    assert "办理材料：居民身份证" in content
    assert "办理地点：常州政务服务中心公安窗口" in content
    assert "收费情况：收费20元" in content


def test_dify_mixed_quoted_preflight_requires_exact_slot_composite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls = {"rag": 0, "metadata_anchor": 0}

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": {{"dataset_ids": ["{dataset_id}"], "plugin_refs": ["{_DEMO_PLUGIN_REF}"]}}}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    _patch_demo_policy(
        monkeypatch,
        dify_api,
        anchor_binding={
            "enabled": True,
            "anchor_fields": ["case_title"],
            "slot_fields": ["section_type"],
        },
        metadata_anchor_preflight_block_terms=[],
        query_expansion_values=[
            {"metadata": "section_type", "value": "related_services", "terms": ["涉及哪些事项"]},
            {"metadata": "section_type", "value": "materials", "terms": ["主要材料"]},
            {"metadata": "section_type", "value": "channels", "terms": ["办理渠道", "联系电话"]},
        ],
    )

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        calls["rag"] += 1
        return [
            {
                "chunk_content": (
                    "答案要点：一件事：Alpha Package；涉及事项：事项 A；"
                    "申请材料：申请表；办理渠道：线上申请，线下窗口咨询。"
                ),
                "relevance_score": 0.91,
                "document_name": "one-thing-guide.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {
                    "dataset_id": str(dataset_id),
                    "case_title": "Alpha Package",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                },
            }
        ]

    def _fake_metadata_anchor_db_fallback_records(**_kwargs):  # noqa: ANN003, ANN202
        calls["metadata_anchor"] += 1
        return [
            {
                "content": (
                    "答案要点：事项名称：Alpha Package Service；办理材料：身份证；办理地点：政务中心\n\n"
                    "原始证据：事项名称：Alpha Package Service"
                ),
                "score": 0.96,
                "title": "service-item.txt",
                "metadata": {
                    "dataset_id": str(dataset_id),
                    "service_name": "Alpha Package Service",
                    "chunk_kind": "service_item_full",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                    "dify_metadata_anchor_fallback": True,
                },
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)
    monkeypatch.setattr(
        dify_api,
        "_metadata_anchor_db_fallback_records",
        _fake_metadata_anchor_db_fallback_records,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "我想办理“Alpha Package”，请同时说明涉及哪些事项、主要材料，以及办理渠道或联系电话。",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls["rag"] >= 1
    content = res.json()["records"][0]["content"]
    assert "涉及事项：事项 A" in content
    assert "申请材料：申请表" in content
    assert "办理渠道：线上申请" in content


def test_dify_retrieval_skips_preflight_for_plugin_slot_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls = {"rag": 0, "metadata_preflight": 0, "metadata_supplement": 0}

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": {{"dataset_ids": ["{dataset_id}"], "plugin_refs": ["{_DEMO_PLUGIN_REF}"]}}}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    _patch_demo_policy(
        monkeypatch,
        dify_api,
        query_expansion_values=[
            {"metadata": "section_type", "value": "channels", "terms": ["service channel"]},
        ],
    )

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        calls["rag"] += 1
        return [
            {
                "chunk_content": "Case: Alpha Desk\nSection: service channel\nUse the Alpha portal.",
                "relevance_score": 0.86,
                "document_name": "alpha-guide.md",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {
                    "dataset_id": str(dataset_id),
                    "case_title": "Alpha Desk",
                    "section_type": "channels",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                },
            }
        ]

    def _fake_metadata_anchor_db_fallback_records(**kwargs):  # noqa: ANN003, ANN202
        if kwargs.get("existing_records"):
            calls["metadata_supplement"] += 1
        else:
            calls["metadata_preflight"] += 1
        return []

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)
    monkeypatch.setattr(
        dify_api,
        "_metadata_anchor_db_fallback_records",
        _fake_metadata_anchor_db_fallback_records,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "Alpha Desk service channel",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls["rag"] == 1
    assert calls["metadata_preflight"] == 0
    assert res.json()["records"][0]["metadata"]["section_type"] == "channels"


@pytest.mark.asyncio
async def test_dify_retrieval_singleflight_then_cache_reuses_identical_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls = {"rag": 0}
    request_sessions = []
    retrieval_started = asyncio.Event()
    release_retrieval = asyncio.Event()

    class _TrackingDB:
        def __init__(self) -> None:
            self.rollback_count = 0

        def rollback(self) -> None:
            self.rollback_count += 1

    def _override_tracking_db():  # noqa: ANN202
        session = _TrackingDB()
        request_sessions.append(session)
        yield session

    dify_api._clear_dify_response_cache()
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_TTL_SEC", 60, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_MAX_ENTRIES", 32, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_SINGLEFLIGHT_ENABLED", True, raising=False)
    monkeypatch.setattr(
        dify_api,
        "_resolve_dify_response_cache_corpus_token",
        lambda **_kwargs: "corpus-v1",
        raising=True,
    )
    _patch_demo_policy(monkeypatch, dify_api)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        calls["rag"] += 1
        retrieval_started.set()
        await release_retrieval.wait()
        return [
            {
                "chunk_content": "事项名称：学区划分查询\n咨询方式：0519-69660631",
                "relevance_score": 0.91,
                "document_name": "service-rag.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {
                    "dataset_id": str(dataset_id),
                    "district": "天宁区",
                    "service_name": "学区划分查询",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                },
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_tracking_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    payload = {
        "knowledge_id": "city",
        "query": "天宁区学区查询咨询电话是多少",
        "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first_task = asyncio.create_task(
            client.post("/api/v1/integrations/dify/retrieval", headers=_auth(token), json=payload)
        )
        await retrieval_started.wait()
        second_task = asyncio.create_task(
            client.post("/api/v1/integrations/dify/retrieval", headers=_auth(token), json=payload)
        )
        await asyncio.sleep(0.05)
        release_retrieval.set()
        try:
            first, second = await asyncio.gather(first_task, second_task)
            cached = await client.post(
                "/api/v1/integrations/dify/retrieval",
                headers=_auth(token),
                json=payload,
            )
        finally:
            dify_api._clear_dify_response_cache()

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert cached.status_code == 200, cached.text
    assert calls["rag"] == 1
    assert len(request_sessions) == 3
    assert all(session.rollback_count >= 1 for session in request_sessions)
    assert second.json() == first.json()
    assert cached.json() == first.json()


@pytest.mark.asyncio
async def test_dify_distributed_singleflight_and_redis_cache_reuse_across_instances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls = {"rag": 0}
    retrieval_started = asyncio.Event()
    release_retrieval = asyncio.Event()
    fake_redis = _FakeRedis()

    _patch_fake_dify_redis(monkeypatch, dify_api, fake_redis)
    dify_api._clear_dify_response_cache()
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_TTL_SEC", 30, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_MAX_ENTRIES", 32, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_SINGLEFLIGHT_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TIMEOUT_SEC", 75.0, raising=False)
    monkeypatch.setattr(
        dify_api,
        "_resolve_dify_response_cache_corpus_token",
        lambda **_kwargs: "corpus-v1",
        raising=True,
    )
    monkeypatch.setattr(
        dify_api,
        "_acquire_or_wait_for_inflight_response",
        lambda _key: asyncio.sleep(0, result=(True, None)),
        raising=True,
    )
    monkeypatch.setattr(dify_api, "resolve_inflight_response", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(dify_api, "reject_inflight_response", lambda *_args, **_kwargs: None, raising=True)
    _patch_demo_policy(monkeypatch, dify_api)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        calls["rag"] += 1
        retrieval_started.set()
        await release_retrieval.wait()
        return [
            {
                "chunk_content": "事项名称：学区划分查询\n咨询方式：0519-69660631",
                "relevance_score": 0.91,
                "document_name": "service-rag.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {"dataset_id": str(dataset_id), "service_name": "学区划分查询"},
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    payload = {
        "knowledge_id": "city",
        "query": "天宁区学区查询咨询电话是多少",
        "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        leader = asyncio.create_task(
            client.post("/api/v1/integrations/dify/retrieval", headers=_auth(token), json=payload)
        )
        await retrieval_started.wait()
        lease_keys = [key for key in fake_redis._values if key.endswith(":lease")]
        assert len(lease_keys) == 1
        assert (fake_redis.ttl_remaining(lease_keys[0]) or 0) >= 60
        follower = asyncio.create_task(
            client.post("/api/v1/integrations/dify/retrieval", headers=_auth(token), json=payload)
        )
        await asyncio.sleep(0.05)
        release_retrieval.set()
        first, second = await asyncio.gather(leader, follower)
        dify_api._clear_dify_response_cache()
        cached = await client.post(
            "/api/v1/integrations/dify/retrieval",
            headers=_auth(token),
            json=payload,
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert cached.status_code == 200, cached.text
    assert calls["rag"] == 1
    assert second.json() == first.json()
    assert cached.json() == first.json()


@pytest.mark.asyncio
async def test_dify_singleflight_follower_takes_over_after_leader_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api
    import app.services.chat_response_cache as cache_mod

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls = 0
    first_started = threading.Event()
    second_started = threading.Event()
    release_retrieval = threading.Event()
    calls_lock = threading.Lock()

    dify_api._clear_dify_response_cache()
    cache_mod.clear_inflight_chat_responses()
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_SINGLEFLIGHT_ENABLED", True, raising=False)
    monkeypatch.setattr(
        dify_api,
        "_resolve_dify_response_cache_corpus_token",
        lambda **_kwargs: "corpus-v1",
        raising=True,
    )
    _patch_demo_policy(monkeypatch, dify_api)

    def _blocking_retrieve_dataset_citations() -> list[dict[str, object]]:
        nonlocal calls
        with calls_lock:
            calls += 1
            call_number = calls
        first_started.set()
        if call_number == 2:
            second_started.set()
        if not release_retrieval.wait(timeout=5):
            raise TimeoutError("test retrieval was not released")
        return [
            {
                "chunk_content": "事项名称：学区划分查询\n咨询方式：0519-69660631",
                "relevance_score": 0.91,
                "document_name": "service-rag.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {"dataset_id": str(dataset_id), "service_name": "学区划分查询"},
            }
        ]

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return await asyncio.to_thread(_blocking_retrieve_dataset_citations)

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)
    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    payload = {
        "knowledge_id": "city",
        "query": "学区划分查询咨询电话是多少",
        "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        leader = asyncio.create_task(
            client.post("/api/v1/integrations/dify/retrieval", headers=_auth(token), json=payload)
        )
        assert await asyncio.to_thread(first_started.wait, 1)
        follower = asyncio.create_task(
            client.post("/api/v1/integrations/dify/retrieval", headers=_auth(token), json=payload)
        )
        await asyncio.sleep(0.05)
        leader.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(leader, timeout=0.5)
            assert await asyncio.to_thread(second_started.wait, 1)
            release_retrieval.set()
            response = await asyncio.wait_for(follower, timeout=2)
        finally:
            release_retrieval.set()
            cache_mod.clear_inflight_chat_responses()
            dify_api._clear_dify_response_cache()

    assert response.status_code == 200, response.text
    assert calls == 2


@pytest.mark.asyncio
async def test_dify_distributed_singleflight_releases_lease_after_leader_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls = 0
    first_started = threading.Event()
    second_started = threading.Event()
    release_retrieval = threading.Event()
    calls_lock = threading.Lock()
    fake_redis = _FakeRedis()

    _patch_fake_dify_redis(monkeypatch, dify_api, fake_redis)
    dify_api._clear_dify_response_cache()
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_TTL_SEC", 30, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_MAX_ENTRIES", 32, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_SINGLEFLIGHT_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TIMEOUT_SEC", 75.0, raising=False)
    monkeypatch.setattr(
        dify_api,
        "_resolve_dify_response_cache_corpus_token",
        lambda **_kwargs: "corpus-v1",
        raising=True,
    )
    monkeypatch.setattr(
        dify_api,
        "_acquire_or_wait_for_inflight_response",
        lambda _key: asyncio.sleep(0, result=(True, None)),
        raising=True,
    )
    monkeypatch.setattr(dify_api, "resolve_inflight_response", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(dify_api, "reject_inflight_response", lambda *_args, **_kwargs: None, raising=True)
    _patch_demo_policy(monkeypatch, dify_api)

    def _blocking_retrieve_dataset_citations() -> list[dict[str, object]]:
        nonlocal calls
        with calls_lock:
            calls += 1
            call_number = calls
        first_started.set()
        if call_number == 2:
            second_started.set()
        if not release_retrieval.wait(timeout=5):
            raise TimeoutError("test retrieval was not released")
        return [
            {
                "chunk_content": "事项名称：学区划分查询\n咨询方式：0519-69660631",
                "relevance_score": 0.91,
                "document_name": "service-rag.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {"dataset_id": str(dataset_id), "service_name": "学区划分查询"},
            }
        ]

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return await asyncio.to_thread(_blocking_retrieve_dataset_citations)

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    payload = {
        "knowledge_id": "city",
        "query": "学区划分查询咨询电话是多少",
        "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        leader = asyncio.create_task(
            client.post("/api/v1/integrations/dify/retrieval", headers=_auth(token), json=payload)
        )
        assert await asyncio.to_thread(first_started.wait, 1)
        follower = asyncio.create_task(
            client.post("/api/v1/integrations/dify/retrieval", headers=_auth(token), json=payload)
        )
        await asyncio.sleep(0.05)
        leader.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(leader, timeout=0.5)
            assert await asyncio.to_thread(second_started.wait, 1)
            release_retrieval.set()
            response = await asyncio.wait_for(follower, timeout=2)
        finally:
            release_retrieval.set()

    assert response.status_code == 200, response.text
    assert calls == 2


@pytest.mark.asyncio
async def test_dify_uncacheable_request_cancellation_is_not_delayed_by_blocking_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    retrieval_started = threading.Event()
    release_retrieval = threading.Event()

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_SINGLEFLIGHT_ENABLED", True, raising=False)
    monkeypatch.setattr(
        dify_api,
        "_resolve_dify_response_cache_corpus_token",
        lambda **_kwargs: None,
        raising=True,
    )
    _patch_demo_policy(monkeypatch, dify_api)

    def _blocking_retrieve_dataset_citations() -> list[dict[str, object]]:
        retrieval_started.set()
        if not release_retrieval.wait(timeout=5):
            raise TimeoutError("test retrieval was not released")
        return []

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return await asyncio.to_thread(_blocking_retrieve_dataset_citations)

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    payload = {
        "knowledge_id": "city",
        "query": "学区划分查询咨询电话是多少",
        "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        request_task = asyncio.create_task(
            client.post("/api/v1/integrations/dify/retrieval", headers=_auth(token), json=payload)
        )
        assert await asyncio.to_thread(retrieval_started.wait, 1)
        request_task.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(request_task, timeout=0.5)
        finally:
            release_retrieval.set()


def test_dify_quality_metadata_anchor_calls_share_request_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    fallback_budgets: list[int | None] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_TOTAL_BUDGET_MS",
        1500,
        raising=False,
    )
    _patch_demo_policy(monkeypatch, dify_api, question_anchor_bonus=0.9)

    def _fake_metadata_anchor_db_fallback_records(**kwargs):  # noqa: ANN003, ANN202
        fallback_budgets.append(kwargs.get("max_elapsed_ms"))
        time.sleep(0.05)
        return []

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return []

    monkeypatch.setattr(
        dify_api,
        "_metadata_anchor_db_fallback_records",
        _fake_metadata_anchor_db_fallback_records,
        raising=True,
    )
    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)
    response = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "网上申请调解是否影响法定诉权",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert response.status_code == 200, response.text
    assert 0 < int(fallback_budgets[0] or 0) <= 1500
    assert len(fallback_budgets) == 2
    assert 0 < int(fallback_budgets[1] or 0) < int(fallback_budgets[0] or 0)


@pytest.mark.asyncio
async def test_dify_metadata_anchor_budget_includes_offload_queue_wait(
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
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_TOTAL_BUDGET_MS",
        25,
        raising=False,
    )
    _patch_demo_policy(monkeypatch, dify_api)

    async def _blocked_offload(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        await asyncio.sleep(10)
        return []

    async def _empty_retrieval(**_kwargs):  # noqa: ANN003, ANN202
        return []

    monkeypatch.setattr(dify_api, "run_blocking_retrieval_call", _blocked_offload, raising=True)
    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _empty_retrieval, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await asyncio.wait_for(
            client.post(
                "/api/v1/integrations/dify/retrieval",
                headers=_auth(token),
                json={
                    "knowledge_id": "city",
                    "query": "generic service application requirements",
                    "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
                },
            ),
            timeout=0.5,
        )

    assert response.status_code == 200, response.text


def test_dify_kg_on_demand_skips_kg_for_confident_rag_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    kg_flags_seen: list[bool] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": {{"dataset_ids": ["{dataset_id}"], "plugin_refs": ["{_DEMO_PLUGIN_REF}"]}}}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_ON_DEMAND_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_QUERY_EXPANSION_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_ENABLED", True, raising=False)
    _patch_demo_policy(monkeypatch, dify_api)

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        kg_flags_seen.append(bool(kwargs["enable_kg_query_expansion"] or kwargs["enable_kg_chunk_injection"]))
        return [
            {
                "chunk_content": "事项名称：学区划分查询\n咨询方式：0519-69660631",
                "relevance_score": 0.91,
                "document_name": "service-rag.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {
                    "dataset_id": str(dataset_id),
                    "district": "天宁区",
                    "service_name": "学区划分查询",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
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
            "query": "天宁区学区查询咨询电话是多少",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert kg_flags_seen == [False]


def test_dify_kg_on_demand_runs_kg_for_low_confidence_rag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    kg_flags_seen: list[bool] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": {{"dataset_ids": ["{dataset_id}"], "plugin_refs": ["{_DEMO_PLUGIN_REF}"]}}}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_ON_DEMAND_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_QUERY_EXPANSION_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_ENABLED", True, raising=False)
    _patch_demo_policy(monkeypatch, dify_api)

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        kg_enabled = bool(kwargs["enable_kg_query_expansion"] or kwargs["enable_kg_chunk_injection"])
        kg_flags_seen.append(kg_enabled)
        if not kg_enabled:
            return [
                {
                    "chunk_content": "泛化记录：没有明确问题锚点",
                    "relevance_score": 0.4,
                    "document_name": "generic.txt",
                    "chunk_id": str(uuid.uuid4()),
                    "dataset_id": str(dataset_id),
                    "metadata": {
                        "dataset_id": str(dataset_id),
                        "service_name": "网上申请调解",
                        "chunk_python_plugin": _DEMO_PLUGIN_REF,
                    },
                }
            ]
        return [
            {
                "chunk_content": "问题：网上申请调解后，是否影响法定诉权？\n答案：不影响。",
                "relevance_score": 0.91,
                "document_name": "qa-kg.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {
                    "dataset_id": str(dataset_id),
                    "question": "网上申请调解后，是否影响法定诉权？",
                    "chunk_kind": "qa_pair",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                },
            }
        ]

    async def _fake_kg_on_demand_records(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "content": "问题：网上申请调解后，是否影响法定诉权？\n答案：不影响。",
                "score": 0.91,
                "title": "qa-kg.txt",
                "metadata": {
                    "dataset_id": str(dataset_id),
                    "question": "网上申请调解后，是否影响法定诉权？",
                    "chunk_kind": "qa_pair",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                    "kg_on_demand": True,
                },
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_dify_kg_on_demand_records", _fake_kg_on_demand_records, raising=True)
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
            "query": "网上申请调解是否影响法定诉权",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert kg_flags_seen == [False]
    assert res.json()["records"][0]["title"] == "qa-kg.txt"


def test_dify_kg_on_demand_skips_second_rag_when_kg_probe_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    kg_flags_seen: list[bool] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON", f'{{"city": "{dataset_id}"}}', raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_ON_DEMAND_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_ON_DEMAND_PROBE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_QUERY_EXPANSION_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_ENABLED", True, raising=False)
    _patch_demo_policy(monkeypatch, dify_api)

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        kg_flags_seen.append(bool(kwargs["enable_kg_query_expansion"] or kwargs["enable_kg_chunk_injection"]))
        return [
            {
                "chunk_content": "泛化记录：没有明确问题锚点",
                "relevance_score": 0.4,
                "document_name": "generic.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {
                    "dataset_id": str(dataset_id),
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                },
            }
        ]

    async def _fake_kg_on_demand_records(**_kwargs):  # noqa: ANN003, ANN202
        return []

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_dify_kg_on_demand_records", _fake_kg_on_demand_records, raising=True)
    monkeypatch.setattr(dify_api, "_metadata_anchor_db_fallback_records", lambda **_kwargs: [], raising=True)
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
            "query": "网上申请调解是否影响法定诉权",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert kg_flags_seen == [False]


def test_dify_kg_on_demand_service_intent_can_skip_on_primary_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_RECORDS", 1, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_TOP_SCORE", 0.45, raising=False)

    assert dify_api._records_can_skip_kg_on_demand(
        [
            {
                "content": "事项名称：船舶烟囱标志登记\n收费情况：不收费",
                "score": 0.91,
                "metadata": {"chunk_python_plugin": _DEMO_PLUGIN_REF},
            }
        ],
        query="经开区船舶烟囱标志登记收费吗",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )


def test_dify_metadata_anchor_supplement_uses_inherited_route_scope_for_aggregate_knowledge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    north_service_dataset = uuid.uuid4()
    north_qa_dataset = uuid.uuid4()
    south_service_dataset = uuid.uuid4()
    south_qa_dataset = uuid.uuid4()
    city_base_dataset = uuid.uuid4()
    calls = {"rag": 0, "metadata_anchor": 0}
    seen_rag_dataset_ids: list[list[uuid.UUID]] = []
    seen_fallback_dataset_ids: list[list[uuid.UUID]] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            '{"aggregate": {'
            f'"dataset_ids": ["{north_service_dataset}", "{north_qa_dataset}", '
            f'"{south_service_dataset}", "{south_qa_dataset}"]'
            "},"
            '"city": {'
            f'"dataset_ids": ["{city_base_dataset}"],'
            '"query_routes": ['
            '{"terms": ["北区", "north district"], '
            f'"dataset_ids": ["{north_service_dataset}", "{north_qa_dataset}"], '
            '"mode": "replace"}'
            "]"
            "}}"
        ),
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_SCOPE_ENABLED", True, raising=False)
    _patch_demo_policy(monkeypatch, dify_api)

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        calls["rag"] += 1
        dataset_ids = list(kwargs["dataset_ids"])
        seen_rag_dataset_ids.append(dataset_ids)
        return [
            {
                "chunk_content": "泛化记录：北区服务咨询",
                "relevance_score": 0.5,
                "document_name": "generic.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_ids[0]),
                "metadata": {"dataset_id": str(dataset_ids[0])},
            }
        ]

    def _fake_metadata_anchor_db_fallback_records(**kwargs):  # noqa: ANN003, ANN202
        calls["metadata_anchor"] += 1
        dataset_ids = list(kwargs["dataset_ids"])
        seen_fallback_dataset_ids.append(dataset_ids)
        if dataset_ids[:2] != [north_service_dataset, north_qa_dataset]:
            return []
        return [
            {
                "content": "答案要点：咨询方式：0519-12345678\n\n原始证据：\n事项名称：学区划分查询",
                "score": 0.78,
                "title": "north-service.txt",
                "metadata": {
                    "dataset_id": str(north_service_dataset),
                    "district": "北区",
                    "service_name": "学区划分查询",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                    "dify_metadata_anchor_fallback": True,
                },
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)
    monkeypatch.setattr(
        dify_api,
        "_metadata_anchor_db_fallback_records",
        _fake_metadata_anchor_db_fallback_records,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "aggregate",
            "query": "北区学区查询咨询电话是多少",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls == {"rag": 1, "metadata_anchor": 1}
    assert seen_rag_dataset_ids == [
        [north_service_dataset, north_qa_dataset, south_service_dataset, south_qa_dataset]
    ]
    assert seen_fallback_dataset_ids == [
        [north_service_dataset, north_qa_dataset, south_service_dataset, south_qa_dataset]
    ]
    body = res.json()
    assert body["records"][0]["title"] == "north-service.txt"
    assert "0519-12345678" in body["records"][0]["content"]


def test_dify_metadata_anchor_expands_to_sibling_policy_datasets_for_specific_service_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    city_dataset = uuid.uuid4()
    district_dataset = uuid.uuid4()
    calls = {"rag": 0, "metadata_anchor": 0}
    seen_fallback_dataset_ids: list[list[uuid.UUID]] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_SCOPE_ENABLED", True, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_EXTEND_SIBLING_POLICY_SCOPE_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUPPLEMENT_ENABLED",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            '{"city": {'
            f'"dataset_ids": ["{city_dataset}"], '
            f'"plugin_refs": ["{_DEMO_PLUGIN_REF}"], '
            '"query_routes": ['
            '{"terms": ["区县甲"], '
            f'"dataset_ids": ["{district_dataset}"], '
            '"mode": "replace"}'
            "]"
            "},"
            '"district": {'
            f'"dataset_ids": ["{district_dataset}"], '
            f'"plugin_refs": ["{_DEMO_PLUGIN_REF}"]'
            "}}"
        ),
        raising=False,
    )
    _patch_demo_policy(monkeypatch, dify_api)

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        calls["rag"] += 1
        dataset_ids = list(kwargs["dataset_ids"])
        assert dataset_ids == [city_dataset]
        return [
            {
                "chunk_content": "事项名称：建筑业企业资质的核准（注销）\n承诺办结时限：1个工作日",
                "relevance_score": 0.72,
                "document_name": "city-service.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(city_dataset),
                "metadata": {
                    "dataset_id": str(city_dataset),
                    "service_name": "建筑业企业资质的核准（注销）",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                },
            }
        ]

    def _fake_metadata_anchor_db_fallback_records(**kwargs):  # noqa: ANN003, ANN202
        calls["metadata_anchor"] += 1
        dataset_ids = list(kwargs["dataset_ids"])
        seen_fallback_dataset_ids.append(dataset_ids)
        if district_dataset not in dataset_ids:
            return []
        return [
            {
                "content": "答案要点：事项名称：城市建筑垃圾处置核准\n\n原始证据：\n区县：天宁区\n事项名称：城市建筑垃圾处置核准",
                "score": 0.99,
                "title": "district-service.txt",
                "metadata": {
                    "dataset_id": str(district_dataset),
                    "district": "天宁区",
                    "service_name": "城市建筑垃圾处置核准",
                    "chunk_kind": "service_item_full",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                    "dify_metadata_anchor_fallback": True,
                },
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)
    monkeypatch.setattr(
        dify_api,
        "_metadata_anchor_db_fallback_records",
        _fake_metadata_anchor_db_fallback_records,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "城市建筑垃圾处置核准这个事项，帮我直接说清楚：行使层级、受理条件、承诺办结时限。",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls["rag"] >= 1
    assert calls["metadata_anchor"] >= 1
    assert [city_dataset, district_dataset] in seen_fallback_dataset_ids
    assert res.json()["records"][0]["metadata"]["service_name"] == "城市建筑垃圾处置核准"


def test_dify_mixed_preflight_uses_sibling_policy_scope_for_specific_service_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    city_dataset = uuid.uuid4()
    district_dataset = uuid.uuid4()
    query = "城市建筑垃圾处置核准这个事项，帮我直接说清楚：行使层级、办理材料。"
    fallback_calls: list[tuple[str, list[uuid.UUID]]] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_SCOPE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUPPLEMENT_ENABLED", True, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_EXTEND_SIBLING_POLICY_SCOPE_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            '{"city": {'
            f'"dataset_ids": ["{city_dataset}"], '
            f'"plugin_refs": ["{_DEMO_PLUGIN_REF}"], '
            '"query_routes": ['
            '{"terms": ["区县甲"], '
            f'"dataset_ids": ["{district_dataset}"], '
            '"mode": "replace"}'
            "]"
            "},"
            '"district": {'
            f'"dataset_ids": ["{district_dataset}"], '
            f'"plugin_refs": ["{_DEMO_PLUGIN_REF}"]'
            "}}"
        ),
        raising=False,
    )
    _patch_demo_policy(
        monkeypatch,
        dify_api,
        mixed_intent_leading_noise_terms=["帮我直接说清楚"],
        mixed_intent_subject_terms=["这个事项", "行使层级", "办理材料"],
        service_anchor_noise_terms=["这个事项", "帮我直接说清楚", "行使层级", "办理材料"],
        service_anchor_priority_terms=["行使层级", "办理材料"],
        service_anchor_entity_terms=["核准"],
        service_anchor_cutoff_terms=["这个事项", "帮我直接说清楚", "行使层级", "办理材料"],
        query_expansion_values=[
            {"metadata": "service_fields", "value": "行使层级", "terms": ["行使层级"]},
            {"metadata": "section_type", "value": "materials", "terms": ["办理材料"]},
        ],
    )

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        dataset_ids = list(kwargs["dataset_ids"])
        return [
            {
                "chunk_content": "事项名称：城市测量标志管护\n行使层级：市级",
                "relevance_score": 0.72,
                "document_name": "city-service.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_ids[0]),
                "metadata": {
                    "dataset_id": str(dataset_ids[0]),
                    "service_name": "城市测量标志管护",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                },
            }
        ]

    def _fake_metadata_anchor_db_fallback_records(**kwargs):  # noqa: ANN003, ANN202
        dataset_ids = list(kwargs["dataset_ids"])
        fallback_calls.append((str(kwargs["query"]), dataset_ids))
        if str(kwargs["query"]) == query:
            return []
        if district_dataset not in dataset_ids:
            return []
        return [
            {
                "content": "答案要点：事项名称：城市建筑垃圾处置核准\n行使层级：区级\n办理材料：申请表",
                "score": 0.99,
                "title": "district-service.txt",
                "metadata": {
                    "dataset_id": str(district_dataset),
                    "service_name": "城市建筑垃圾处置核准",
                    "chunk_kind": "service_item_full",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                    "dify_metadata_anchor_fallback": True,
                },
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)
    monkeypatch.setattr(
        dify_api,
        "_metadata_anchor_db_fallback_records",
        _fake_metadata_anchor_db_fallback_records,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": query,
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    subquery_calls = [(seen_query, ids) for seen_query, ids in fallback_calls if seen_query != query]
    assert subquery_calls
    assert all([city_dataset, district_dataset] == ids for _seen_query, ids in subquery_calls)
    assert res.json()["records"][0]["metadata"]["service_name"] == "城市建筑垃圾处置核准"


def test_dify_metadata_anchor_sibling_scope_is_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    city_dataset = uuid.uuid4()
    district_dataset = uuid.uuid4()
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_EXTEND_SIBLING_POLICY_SCOPE_ENABLED",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            '{"city": {'
            f'"dataset_ids": ["{city_dataset}"], '
            f'"plugin_refs": ["{_DEMO_PLUGIN_REF}"], '
            '"query_routes": ['
            '{"terms": ["区县甲"], '
            f'"dataset_ids": ["{district_dataset}"], '
            '"mode": "replace"}'
            "]"
            "},"
            '"district": {'
            f'"dataset_ids": ["{district_dataset}"], '
            f'"plugin_refs": ["{_DEMO_PLUGIN_REF}"]'
            "}}"
        ),
        raising=False,
    )

    resolved = dify_api._metadata_anchor_dataset_ids_for_query(
        knowledge_id="city",
        base_dataset_ids=[city_dataset],
        query="机关事业单位参保注销：行使层级、办理地点、监督投诉方式。",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert resolved == [city_dataset]


def test_dify_aggregate_routes_merge_explicit_and_inherited_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    north_service_dataset = uuid.uuid4()
    north_qa_dataset = uuid.uuid4()
    south_service_dataset = uuid.uuid4()
    city_service_dataset = uuid.uuid4()

    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            '{"aggregate": {'
            f'"dataset_ids": ["{north_service_dataset}", "{north_qa_dataset}", '
            f'"{south_service_dataset}", "{city_service_dataset}"],'
            '"query_routes": ['
            '{"terms": ["城市本级"], '
            f'"dataset_ids": ["{city_service_dataset}"], '
            '"mode": "replace"}'
            "],"
            '"inherit_query_routes_from": ["city"]'
            "},"
            '"city": {'
            f'"dataset_ids": ["{city_service_dataset}"],'
            '"query_routes": ['
            '{"terms": ["北区"], '
            f'"dataset_ids": ["{north_service_dataset}", "{north_qa_dataset}"], '
            '"mode": "replace"}'
            "]"
            "}}"
        ),
        raising=False,
    )

    inherited_scope = dify_api._resolve_knowledge_dataset_scope("aggregate", query="北区学区查询咨询电话")
    explicit_scope = dify_api._resolve_knowledge_dataset_scope("aggregate", query="城市本级工伤保险待遇恢复")

    assert list(inherited_scope.primary_dataset_ids) == [
        north_service_dataset,
        north_qa_dataset,
        south_service_dataset,
        city_service_dataset,
    ]
    assert list(explicit_scope.primary_dataset_ids) == [
        city_service_dataset,
        north_service_dataset,
        north_qa_dataset,
        south_service_dataset,
    ]


def test_dify_mapping_does_not_inherit_routes_without_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    first_dataset = uuid.uuid4()
    second_dataset = uuid.uuid4()
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            "{"
            '"source": {'
            f'"dataset_ids": ["{first_dataset}"],'
            '"query_routes": [{"terms": ["private route"], '
            f'"dataset_ids": ["{second_dataset}"], "mode": "replace"}}]'
            "},"
            '"target": {'
            f'"dataset_ids": ["{first_dataset}", "{second_dataset}"]'
            "}"
            "}"
        ),
        raising=False,
    )

    scope = dify_api._resolve_knowledge_dataset_scope("target", query="private route")

    assert list(scope.primary_dataset_ids) == [first_dataset, second_dataset]
    assert scope.matched_terms == ()


def test_dify_mapping_can_inherit_shared_subject_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    district_service_dataset = uuid.uuid4()
    district_qa_dataset = uuid.uuid4()
    city_faq_dataset = uuid.uuid4()

    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            "{"
            '"city-service": {'
            f'"dataset_ids": ["{city_faq_dataset}"],'
            '"query_routes": ['
            '{"terms": ["汽车置换", "置换补贴"], '
            f'"dataset_ids": ["{city_faq_dataset}"], '
            '"mode": "replace"}'
            "]"
            "},"
            '"district-service": {'
            f'"dataset_ids": ["{district_service_dataset}", "{district_qa_dataset}"],'
            '"inherit_query_routes_from": ["city-service"]'
            "}"
            "}"
        ),
        raising=False,
    )

    scope = dify_api._resolve_knowledge_dataset_scope("district-service", query="区域甲置换补贴到账时间")

    assert list(scope.primary_dataset_ids) == [
        city_faq_dataset,
        district_service_dataset,
        district_qa_dataset,
    ]
    assert scope.matched_terms == ("置换补贴",)


def test_dify_mapping_applies_strict_scope_to_inherited_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    base_dataset = uuid.uuid4()
    route_dataset = uuid.uuid4()
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            "{"
            '"route-source": {'
            f'"dataset_ids": ["{route_dataset}"],'
            '"query_routes": [{"terms": ["region alpha"], '
            f'"dataset_ids": ["{route_dataset}"], "mode": "replace"}}]'
            "},"
            '"target": {'
            f'"dataset_ids": ["{base_dataset}"],'
            '"strict_query_routes": true,'
            '"inherit_query_routes_from": ["route-source"]'
            "}"
            "}"
        ),
        raising=False,
    )

    scope = dify_api._resolve_knowledge_dataset_scope("target", query="region alpha service")

    assert scope.strict_scope is True
    assert list(scope.dataset_ids) == [route_dataset]
    assert list(scope.primary_dataset_ids) == [route_dataset]


def test_dify_inherited_query_routes_follow_declared_source_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    first_dataset = uuid.uuid4()
    second_dataset = uuid.uuid4()
    base_dataset = uuid.uuid4()
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            "{"
            '"second": {'
            f'"dataset_ids": ["{second_dataset}"],'
            f'"query_routes": [{{"terms": ["shared"], "dataset_ids": ["{second_dataset}"], "mode": "replace"}}]'
            "},"
            '"first": {'
            f'"dataset_ids": ["{first_dataset}"],'
            f'"query_routes": [{{"terms": ["shared"], "dataset_ids": ["{first_dataset}"], "mode": "replace"}}]'
            "},"
            '"target": {'
            f'"dataset_ids": ["{base_dataset}"],'
            '"strict_query_routes": true,'
            '"inherit_query_routes_from": ["first", "second"]'
            "}"
            "}"
        ),
        raising=False,
    )

    scope = dify_api._resolve_knowledge_dataset_scope("target", query="shared service")

    assert list(scope.dataset_ids) == [second_dataset]


def test_dify_local_query_route_overrides_inherited_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    inherited_dataset = uuid.uuid4()
    local_dataset = uuid.uuid4()
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            "{"
            '"source": {'
            f'"dataset_ids": ["{inherited_dataset}"],'
            f'"query_routes": [{{"terms": ["shared"], "dataset_ids": ["{inherited_dataset}"], "mode": "replace"}}]'
            "},"
            '"target": {'
            f'"dataset_ids": ["{local_dataset}"],'
            '"strict_query_routes": true,'
            '"inherit_query_routes_from": ["source"],'
            f'"query_routes": [{{"terms": ["shared"], "dataset_ids": ["{local_dataset}"], "mode": "replace"}}]'
            "}"
            "}"
        ),
        raising=False,
    )

    scope = dify_api._resolve_knowledge_dataset_scope("target", query="shared service")

    assert list(scope.dataset_ids) == [local_dataset]


def test_dify_metadata_anchor_fallback_query_terms_prioritize_specific_phrases() -> None:
    import app.api.v1.integrations_dify as dify_api

    terms = dify_api._metadata_anchor_fallback_query_terms("天宁区学区划分查询咨询电话是多少")

    assert terms[0] == "天宁区学区划分查询咨询电话是多少"
    assert "学区划分查询" in terms[:10]


def test_dify_metadata_anchor_fallback_query_terms_keep_short_service_names_early() -> None:
    import app.api.v1.integrations_dify as dify_api

    terms = dify_api._metadata_anchor_fallback_query_terms("常州市职业介绍什么时候可以办")

    assert "职业介绍" in terms[:10]


def test_dify_metadata_anchor_service_terms_only_remove_declared_area_and_question_noise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        anchor_fields=[
            {
                "metadata": "administrative_area",
                "role": "administrative_area",
                "aliases": {
                    "常州市": ["常州市", "常州"],
                    "经开区": ["经开区", "经开"],
                    "天宁区": ["天宁区", "天宁"],
                },
            }
        ],
    )

    without_policy_terms = dify_api._metadata_anchor_service_name_query_terms(
        "经开区用水变更需要什么材料",
    )
    district_terms = dify_api._metadata_anchor_service_name_query_terms(
        "天宁区学区查询咨询电话是多少",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )
    city_terms = dify_api._metadata_anchor_service_name_query_terms(
        "常州市工伤保险待遇恢复在哪里办理",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )
    material_terms = dify_api._metadata_anchor_service_name_query_terms(
        "经开区用水变更需要什么材料",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )
    fee_terms = dify_api._metadata_anchor_service_name_query_terms(
        "经开区拖拉机和联合收割机驾驶证违法记分收费吗",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )
    entry_terms = dify_api._metadata_anchor_service_name_query_terms(
        "餐饮店设立“一件事”办理入口在哪里",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert without_policy_terms[0] == "经开区用水变更需要什么材料"
    assert district_terms[:2] == ["天宁区学区查询", "学区查询"]
    assert "咨询电话" not in "".join(district_terms[:4])
    assert city_terms[:2] == ["常州市工伤保险待遇恢复", "工伤保险待遇恢复"]
    assert "在哪里办理" not in "".join(city_terms[:4])
    assert material_terms[:2] == ["经开区用水变更", "用水变更"]
    assert "需要什么材料" not in "".join(material_terms[:4])
    assert fee_terms[:2] == [
        "经开区拖拉机和联合收割机驾驶证违法记分",
        "拖拉机和联合收割机驾驶证违法记分",
    ]
    assert "收费吗" not in "".join(fee_terms[:4])
    assert entry_terms[0] == "餐饮店设立“一件事”"
    assert "入口在哪里" not in "".join(entry_terms[:4])


def test_dify_metadata_anchor_service_terms_strip_generic_item_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)

    terms = dify_api._metadata_anchor_service_name_query_terms(
        "城市建筑垃圾处置核准这个事项，帮我直接说清楚：行使层级、受理条件、承诺办结时限。",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert terms[0] == "城市建筑垃圾处置核准"
    assert "这个事项" not in "".join(terms[:4])


def test_dify_query_treats_approval_verification_as_service_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)

    assert dify_api._query_has_specific_service_anchor_candidate(
        "城市建筑垃圾处置核准这个事项，帮我直接说清楚：行使层级、受理条件、承诺办结时限。",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )


def test_dify_metadata_anchor_service_terms_keep_literal_title_before_plugin_rewrites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        service_anchor_query_rewrites=[
            {
                "when_terms": ["服务卡", "补卡"],
                "terms": ["服务卡（首次、延期）", "服务卡补卡"],
            }
        ],
    )

    terms = dify_api._metadata_anchor_service_name_query_terms(
        "服务卡补卡这个事项，帮我直接说清楚：办理地点、收费情况。",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert terms[0] == "服务卡补卡"
    assert terms[1] == "服务卡（首次、延期）"


def test_dify_metadata_anchor_service_terms_preserve_quoted_title_punctuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)

    terms = dify_api._metadata_anchor_service_name_query_terms(
        "请核对“Alpha 服务（市级权限）新申请”：办理地点、收费情况。",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert terms[0] == "Alpha 服务（市级权限）新申请"
    assert terms[1] == "alpha服务市级权限新申请"


def test_dify_metadata_anchor_service_terms_do_not_strip_long_title_as_admin_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        anchor_fields=[
            {
                "metadata": "district",
                "aliases": {"区域甲": ["区域甲", "甲区"]},
            }
        ],
    )

    terms = dify_api._metadata_anchor_service_name_query_terms(
        "砍伐城市树木、迁移古树名木审批新申请是不是能办？",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert terms[0] == "砍伐城市树木、迁移古树名木审批新申请"


def test_dify_metadata_anchor_service_terms_only_use_explicit_cutoffs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        service_anchor_cutoff_terms=["在线办理地址", "咨询方式"],
        fast_response_field_rules=[
            {"label": "在线办理地址", "markers": ["在线办理地址"]},
            {"label": "咨询方式", "markers": ["咨询方式"]},
        ],
    )

    terms = dify_api._metadata_anchor_service_name_query_terms(
        "对持证居民一次性奖励扶助：在线办理地址、咨询方式？",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert terms[0] == "对持证居民一次性奖励扶助"


def test_dify_response_labels_do_not_become_service_title_cutoffs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        service_anchor_cutoff_terms=[],
        fast_response_field_rules=[{"label": "联系方式", "markers": ["联系电话"]}],
    )

    assert dify_api._service_anchor_cutoff_terms_for_policy_refs((_DEMO_PLUGIN_REF,)) == ()


def test_dify_non_admin_anchor_alias_does_not_strip_service_title_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        anchor_fields=[
            {
                "metadata": "product_line",
                "aliases": {"旗舰专区": ["旗舰专区"]},
            }
        ],
    )

    terms = dify_api._metadata_anchor_service_name_query_terms(
        "旗舰专区售后服务是不是能办？",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert terms[0] == "旗舰专区售后服务"


def test_dify_declared_admin_anchor_alias_strips_long_area_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        anchor_fields=[
            {
                "metadata": "region",
                "role": "administrative_area",
                "aliases": {"区域甲新区": ["区域甲新区"]},
            }
        ],
    )

    terms = dify_api._metadata_anchor_service_name_query_terms(
        "区域甲新区售后服务是不是能办？",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert terms[:2] == ["区域甲新区售后服务", "售后服务"]


def test_dify_declared_admin_alias_does_not_destroy_a_service_title_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        anchor_fields=[
            {
                "metadata": "district",
                "role": "administrative_area",
                "aliases": {"常州市": ["常州市", "常州"]},
            }
        ],
    )

    service_terms = dify_api._metadata_anchor_service_name_query_terms(
        "常州市民卡怎么办理？",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )
    title_terms = dify_api._metadata_anchor_title_query_terms(
        "常州市民卡怎么办理？",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert service_terms[0] == "常州市民卡"
    assert title_terms[0] == "常州市民卡"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("开发区服务怎么办？", "开发区服务怎么办"),
        ("示范县产品怎么申请？", "示范县产品"),
        ("服务区收费怎么查？", "服务区收费怎么查"),
    ],
)
def test_dify_does_not_guess_undeclared_administrative_areas(
    monkeypatch: pytest.MonkeyPatch,
    query: str,
    expected: str,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api, anchor_fields=[])

    cleaned = dify_api._strip_service_anchor_query_noise(
        query,
        noise_terms=tuple(_demo_service_anchor_noise_terms()),
    )

    assert cleaned == expected


def test_dify_metadata_anchor_service_terms_prioritize_quoted_service_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)

    terms = dify_api._metadata_anchor_service_name_query_terms(
        "办理「困难残疾人生活补贴和重度残疾人护理补贴资格认定申请」前，归哪个层级办理、属于什么办件类型、法定多久办结分别是什么？",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert terms[0] == "困难残疾人生活补贴和重度残疾人护理补贴资格认定申请"
    assert "办理" not in terms[0]
    assert "归哪个层级" not in terms[0]


def test_dify_compaction_keeps_mixed_intent_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        response_compaction={
            "enabled": True,
            "min_top_score": 0.8,
            "relative_score_floor": 0.65,
            "min_records": 1,
        },
    )
    records = [
        {"content": "企业社会保险登记地点", "score": 0.99, "title": "社保登记.txt", "metadata": {}},
        {"content": "住宅专项维修资金交存标准", "score": 0.42, "title": "维修资金.txt", "metadata": {}},
        {"content": "补充说明", "score": 0.38, "title": "补充.txt", "metadata": {}},
    ]

    compacted = dify_api._compact_records_for_response(
        records,
        query="经开区企业社会保险登记在哪里办？另外住宅专项维修资金的交存标准是多少？",
        top_k=3,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert [record["title"] for record in compacted] == ["社保登记.txt", "维修资金.txt", "补充.txt"]


def test_dify_mixed_intent_retrieval_queries_do_not_use_platform_business_terms_without_policy() -> None:
    import app.api.v1.integrations_dify as dify_api

    queries = dify_api._mixed_intent_retrieval_queries(
        "我想同时了解身份证补领需要什么材料，另外怎么查询办理进度？",
        policy_plugin_refs=(),
    )

    assert queries == ("了解身份证补领需要什么材料", "怎么查询办理进度")


def test_dify_mixed_intent_retrieval_queries_carry_subject_from_plugin_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        mixed_intent_leading_noise_terms=["我想", "了解"],
        mixed_intent_subject_terms=["需要什么材料", "怎么查询"],
    )

    queries = dify_api._mixed_intent_retrieval_queries(
        "我想同时了解身份证补领需要什么材料，另外怎么查询办理进度？",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert queries == (
        "身份证补领需要什么材料",
        "身份证补领怎么查询办理进度",
    )


def test_dify_mixed_intent_retrieval_queries_split_list_parts_with_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        question_intent_terms=["在哪里", "多长时间", "收费", "注意"],
    )

    queries = dify_api._mixed_intent_retrieval_queries(
        "关于Alpha卡，请合并回答：在哪里办理、需要多长时间、是否收费或需要注意什么？",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert queries == (
        "Alpha卡在哪里办理",
        "Alpha卡需要多长时间",
        "Alpha卡是否收费",
        "Alpha卡需要注意什么",
    )


def test_dify_mixed_intent_retrieval_queries_expand_multi_value_policy_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        query_expansion_values=[
            {"metadata": "section_type", "values": ["related_services", "process"], "terms": ["涉及事项"]},
            {"metadata": "section_type", "value": "process", "terms": ["办理须知", "办理流程"]},
            {"metadata": "section_type", "value": "materials", "terms": ["主要材料"]},
            {"metadata": "section_type", "value": "channels", "terms": ["办理渠道"]},
        ],
        mixed_intent_leading_noise_terms=["我想办理"],
        mixed_intent_subject_terms=["涉及事项", "主要材料", "办理渠道"],
    )

    queries = dify_api._mixed_intent_retrieval_queries(
        "我想办理“Alpha Package”，请同时说明涉及事项、主要材料，以及办理渠道。",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert queries == (
        "“Alpha Package”涉及事项",
        "“Alpha Package”办理须知",
        "“Alpha Package”主要材料",
        "“Alpha Package”办理渠道",
    )


def test_dify_mixed_intent_retrieval_queries_split_chinese_list_conjunctions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        query_expansion_values=[
            {"metadata": "section_type", "values": ["related_services", "process"], "terms": ["涉及事项"]},
            {"metadata": "section_type", "value": "process", "terms": ["办理须知"]},
            {"metadata": "section_type", "value": "materials", "terms": ["材料", "申请材料"]},
            {"metadata": "section_type", "value": "channels", "terms": ["办理入口", "办理渠道"]},
            {"metadata": "section_type", "value": "contacts", "terms": ["电话", "联系方式"]},
        ],
        mixed_intent_leading_noise_terms=["我想办", "先帮我看下"],
        mixed_intent_subject_terms=["涉及事项", "材料", "办理入口", "电话"],
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_MAX_SUBQUERIES", 5, raising=False)

    query = "我想办“Alpha Package”，先帮我看下涉及事项、材料和办理入口/电话。"

    assert dify_api._query_has_mixed_intent(query)
    assert dify_api._mixed_intent_retrieval_queries(
        query,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    ) == (
        "“Alpha Package”涉及事项",
        "“Alpha Package”办理须知",
        "“Alpha Package”材料",
        "“Alpha Package”办理入口",
        "“Alpha Package”电话",
    )


def test_dify_mixed_intent_retrieval_queries_keep_corner_quoted_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        query_expansion_values=[
            {"metadata": "section_type", "values": ["related_services", "process"], "terms": ["涉及事项"]},
            {"metadata": "section_type", "value": "process", "terms": ["办理须知"]},
            {"metadata": "section_type", "value": "materials", "terms": ["材料"]},
            {"metadata": "section_type", "value": "channels", "terms": ["办理入口"]},
        ],
        mixed_intent_subject_terms=["涉及事项", "材料", "办理入口"],
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_MAX_SUBQUERIES", 4, raising=False)

    query = "「开办餐饮店“一件事”」如果要办，先帮我看下涉及事项、材料和办理入口/电话。"

    assert dify_api._query_has_quoted_anchor_candidate(query)
    assert dify_api._mixed_intent_retrieval_queries(
        query,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    ) == (
        "「开办餐饮店“一件事”」涉及事项",
        "「开办餐饮店“一件事”」办理须知",
        "「开办餐饮店“一件事”」材料",
        "「开办餐饮店“一件事”」办理入口",
    )


def test_dify_mixed_intent_retrieval_queries_infer_unquoted_compact_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        query_expansion_values=[
            {"metadata": "section_type", "values": ["related_services", "process"], "terms": ["涉及事项"]},
            {"metadata": "section_type", "value": "process", "terms": ["办理须知"]},
            {"metadata": "section_type", "value": "materials", "terms": ["材料"]},
            {"metadata": "section_type", "value": "operation_entry", "terms": ["入口", "办理入口"]},
            {"metadata": "section_type", "value": "channels", "terms": ["电话"]},
        ],
        mixed_intent_subject_terms=["涉及事项", "材料", "入口", "电话"],
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_MAX_SUBQUERIES", 5, raising=False)

    query = "开餐饮店一件事材料入口电话还有涉及事项"

    assert dify_api._query_has_mixed_intent_for_policy(query, policy_plugin_refs=(_DEMO_PLUGIN_REF,))
    assert dify_api._mixed_intent_retrieval_queries(
        query,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    ) == (
        "开餐饮店一件事涉及事项",
        "开餐饮店一件事办理须知",
        "开餐饮店一件事材料",
        "开餐饮店一件事入口",
        "开餐饮店一件事电话",
    )


def test_dify_mixed_intent_retrieval_queries_infer_reversed_unquoted_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        query_expansion_values=[
            {"metadata": "section_type", "values": ["related_services", "process"], "terms": ["涉及事项"]},
            {"metadata": "section_type", "value": "process", "terms": ["办理须知"]},
            {"metadata": "section_type", "value": "materials", "terms": ["材料"]},
            {"metadata": "section_type", "value": "operation_entry", "terms": ["入口", "办理入口"]},
            {"metadata": "section_type", "value": "channels", "terms": ["电话"]},
        ],
        mixed_intent_subject_terms=["涉及事项", "材料", "入口", "电话"],
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_MAX_SUBQUERIES", 5, raising=False)

    query = "材料、入口、电话、涉及事项，开办运输企业一件事"

    assert dify_api._mixed_intent_retrieval_queries(
        query,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    ) == (
        "涉及事项",
        "开办运输企业一件事涉及事项",
        "开办运输企业一件事办理须知",
        "开办运输企业一件事材料",
        "开办运输企业一件事入口",
    )


def test_dify_compound_answer_prompt_is_mixed_intent_for_preflight_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    query = "关于Alpha Desk，请合并回答：在哪里办理、需要多长时间、是否收费？"

    assert dify_api._query_has_mixed_intent(query)
    assert not dify_api._query_allows_metadata_anchor_preflight(
        query,
        query_prefers_question_anchor=True,
        query_prefers_service_anchor=True,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )


def test_dify_quoted_service_mixed_intent_allows_metadata_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    query = "我要办理“Alpha Desk”，需要哪些材料？同时告诉我在哪里办理、是否收费。"

    assert dify_api._query_has_mixed_intent(query)
    assert dify_api._query_allows_metadata_anchor_preflight(
        query,
        query_prefers_question_anchor=True,
        query_prefers_service_anchor=True,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )


def test_dify_quoted_service_anchor_prefers_service_lookup_before_broad_question_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    query = "我要办理“Alpha Desk”，需要哪些材料？同时告诉我在哪里办理、是否收费。"

    assert not dify_api._metadata_anchor_should_query_question_first(
        query,
        query_prefers_question_anchor=True,
        query_prefers_service_anchor=True,
        prefer_question_anchor_first=False,
    )
    assert dify_api._metadata_anchor_should_query_question_first(
        "Alpha Desk 需要多长时间",
        query_prefers_question_anchor=True,
        query_prefers_service_anchor=False,
        prefer_question_anchor_first=True,
    )


def test_dify_quoted_anchor_match_rejects_slot_only_qa() -> None:
    import app.api.v1.integrations_dify as dify_api

    query = "我要办理“补发《药品经营许可证》”，需要哪些材料？同时告诉我在哪里办理、是否收费。"
    slot_only_record = {
        "content": "答案要点：答案：补发公共场所卫生许可证应提交申请表。",
        "title": "qa.txt",
        "metadata": {
            "question": "公共场所卫生许可补发需要提交哪些材料？",
            "chunk_kind": "qa_pair",
        },
    }
    exact_qa_record = {
        "content": "答案要点：答案：补发《药品经营许可证》材料说明。",
        "title": "qa.txt",
        "metadata": {
            "question": "补发《药品经营许可证》",
            "chunk_kind": "qa_pair",
        },
    }
    exact_service_record = {
        "content": "事项名称：补发《药品经营许可证》\n办理地点：政务中心。",
        "title": "service.txt",
        "metadata": {"service_name": "补发《药品经营许可证》"},
    }

    assert not dify_api._record_matches_quoted_query_anchor(slot_only_record, query=query)
    assert dify_api._record_matches_quoted_query_anchor(exact_qa_record, query=query)
    assert dify_api._record_matches_quoted_query_anchor(exact_service_record, query=query)


def test_dify_plugin_block_term_disables_metadata_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api, metadata_anchor_preflight_block_terms=["Package"])
    query = "我想办理“Alpha Package”，请同时说明涉及哪些事项、主要材料、办理渠道和联系电话。"

    assert dify_api._query_has_mixed_intent(query)
    assert not dify_api._query_allows_metadata_anchor_preflight(
        query,
        query_prefers_question_anchor=True,
        query_prefers_service_anchor=True,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )


def test_dify_mixed_intent_exact_service_anchor_filters_slot_noise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        anchor_binding={"enabled": True, "anchor_fields": ["service_name"], "slot_fields": ["section_type"]},
        query_expansion_values=[
            {"metadata": "section_type", "value": "materials", "terms": ["需要哪些材料"]},
            {"metadata": "section_type", "value": "channels", "terms": ["在哪里办理"]},
        ],
    )
    records = [
        {
            "content": (
                "答案要点：事项名称：Alpha Desk；办理材料：营业执照；办理地点：政务中心；收费情况：不收费\n\n"
                "原始证据：事项名称：Alpha Desk\n办理材料：营业执照\n办理地点：政务中心\n收费情况：不收费"
            ),
            "score": 0.91,
            "title": "alpha-service.txt",
            "metadata": {"service_name": "Alpha Desk", "chunk_python_plugin": _DEMO_PLUGIN_REF},
        },
        {
            "content": "答案要点：答案：不收费。\n\n原始证据：问题：Beta Desk 是否收费\n答案：不收费。",
            "score": 0.72,
            "title": "beta-fee.txt",
            "metadata": {"question": "Beta Desk 是否收费", "chunk_python_plugin": _DEMO_PLUGIN_REF},
        },
        {
            "content": "答案要点：申请材料：Gamma 表\n\n原始证据：一件事：Gamma Package\n章节：申请材料",
            "score": 0.7,
            "title": "gamma-materials.txt",
            "metadata": {
                "case_title": "Gamma Package",
                "section_type": "materials",
                "chunk_python_plugin": _DEMO_PLUGIN_REF,
            },
        },
    ]

    compacted = dify_api._compact_records_for_response(
        records,
        query="我要办理“Alpha Desk”，需要哪些材料？同时告诉我在哪里办理、是否收费。",
        top_k=3,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert [record["title"] for record in compacted] == ["alpha-service.txt"]


def test_dify_mixed_intent_unquoted_anchor_keeps_supplemental_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        query_expansion_values=[
            {"metadata": "section_type", "value": "channels", "terms": ["在哪里办理"]},
            {"metadata": "section_type", "value": "processing_time", "terms": ["需要多长时间"]},
            {"metadata": "section_type", "value": "fees", "terms": ["是否收费"]},
        ],
    )
    records = [
        {
            "content": "答案要点：事项名称：Alpha Desk；办理地点：政务中心；收费情况：不收费",
            "score": 0.95,
            "title": "alpha-service.txt",
            "metadata": {"service_name": "Alpha Desk", "chunk_python_plugin": _DEMO_PLUGIN_REF},
        },
        {
            "content": "答案要点：问题：Alpha Desk 需要多长时间；答案：即时办结。",
            "score": 0.91,
            "title": "alpha-time.txt",
            "metadata": {"question": "Alpha Desk 需要多长时间", "chunk_python_plugin": _DEMO_PLUGIN_REF},
        },
        {
            "content": "答案要点：问题：Alpha Desk 在哪里办理；答案：街道服务中心。",
            "score": 0.9,
            "title": "alpha-place.txt",
            "metadata": {"question": "Alpha Desk 在哪里办理", "chunk_python_plugin": _DEMO_PLUGIN_REF},
        },
    ]

    compacted = dify_api._compact_records_for_response(
        records,
        query="关于Alpha Desk，请合并回答：在哪里办理、需要多长时间、是否收费？",
        top_k=3,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert [record["title"] for record in compacted] == [
        "alpha-service.txt",
        "alpha-time.txt",
        "alpha-place.txt",
    ]


def test_dify_mixed_intent_subquery_strong_question_anchor_beats_generic_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        question_anchor_bonus=1.15,
        question_intent_terms=["在哪里", "多长时间", "收费", "注意"],
    )
    query = "关于失业登记，请合并回答：在哪里办理、需要多长时间、是否收费或需要注意什么？"
    exact_time = {
        "content": "答案要点：答案：即时办结",
        "score": 0.99,
        "title": "exact-time.txt",
        "metadata": {
            "question": "请问办理失业登记需要多长时间",
            "chunk_kind": "qa_pair",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
            "dify_mixed_intent_subquery": "失业登记需要多长时间",
        },
    }
    generic_time = {
        "content": "答案要点：答案：30 个工作日",
        "score": 0.52,
        "title": "generic-time.txt",
        "metadata": {
            "question": "请问办理人员参保登记需要多长时间",
            "chunk_kind": "qa_pair",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }

    assert dify_api._record_rank_score(
        exact_time,
        query=query,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    ) > dify_api._record_rank_score(
        generic_time,
        query=query,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )


def test_dify_mixed_intent_exact_anchor_synthesizes_plugin_slot_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        anchor_binding={
            "enabled": True,
            "anchor_fields": ["case_title"],
            "slot_fields": ["section_type"],
        },
        query_expansion_values=[
            {"metadata": "section_type", "value": "related_services", "terms": ["涉及哪些事项"]},
            {"metadata": "section_type", "value": "materials", "terms": ["主要材料"]},
            {"metadata": "section_type", "value": "channels", "terms": ["办理渠道"]},
        ],
    )
    records = [
        {
            "content": "原始证据：一件事：Alpha Package\n章节：系统入口\n进入系统办理。",
            "score": 0.99,
            "title": "alpha-entry.txt",
            "metadata": {
                "case_title": "Alpha Package",
                "section_type": "operation_entry",
                "chunk_python_plugin": _DEMO_PLUGIN_REF,
                "chunk_id": str(uuid.uuid4()),
            },
        },
        {
            "content": "原始证据：一件事：Alpha Package\n章节：办理渠道\n线上申请，线下窗口咨询。",
            "score": 0.95,
            "title": "alpha-channels.txt",
            "metadata": {
                "case_title": "Alpha Package",
                "section_type": "channels",
                "chunk_python_plugin": _DEMO_PLUGIN_REF,
                "chunk_id": str(uuid.uuid4()),
            },
        },
        {
            "content": "原始证据：一件事：Alpha Package\n章节：申请材料\n主要材料：申请表。",
            "score": 0.94,
            "title": "alpha-materials.txt",
            "metadata": {
                "case_title": "Alpha Package",
                "section_type": "materials",
                "chunk_python_plugin": _DEMO_PLUGIN_REF,
                "chunk_id": str(uuid.uuid4()),
            },
        },
        {
            "content": "原始证据：一件事：Alpha Package\n章节：涉及事项\n事项 A、事项 B。",
            "score": 0.93,
            "title": "alpha-related.txt",
            "metadata": {
                "case_title": "Alpha Package",
                "section_type": "related_services",
                "chunk_python_plugin": _DEMO_PLUGIN_REF,
                "chunk_id": str(uuid.uuid4()),
            },
        },
    ]

    compacted = dify_api._compact_records_for_response(
        records,
        query="我想办理“Alpha Package”，请同时说明涉及哪些事项、主要材料，以及办理渠道。",
        top_k=3,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert len(compacted) == 1
    assert compacted[0]["metadata"]["section_type"] == "composite"
    assert compacted[0]["metadata"]["dify_composite_section_types"] == [
        "related_services",
        "materials",
        "channels",
    ]
    assert "章节：涉及事项" in compacted[0]["content"]
    assert "章节：申请材料" in compacted[0]["content"]
    assert "章节：办理渠道" in compacted[0]["content"]
    assert "合并章节原文" in compacted[0]["content"]
    assert "事项 A、事项 B。\n申请材料\n主要材料：申请表。" in compacted[0]["content"]


def test_dify_mixed_intent_exact_anchor_orders_split_section_siblings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    source_record_id = "alpha-package"
    _patch_demo_policy(
        monkeypatch,
        dify_api,
        anchor_binding={
            "enabled": True,
            "anchor_fields": ["case_title"],
            "slot_fields": ["section_type"],
        },
        query_expansion_values=[
            {"metadata": "section_type", "values": ["related_services", "process"], "terms": ["涉及事项"]},
            {"metadata": "section_type", "value": "materials", "terms": ["主要材料"]},
            {"metadata": "section_type", "value": "channels", "terms": ["办理渠道"]},
        ],
    )
    records = [
        {
            "content": "原始证据：一件事：Alpha Package\n章节：办理须知\n2. Beta 条件说明。",
            "score": 0.99,
            "title": "alpha-process-2.txt",
            "metadata": {
                "case_title": "Alpha Package",
                "section_type": "process",
                "source_record_id": source_record_id,
                "source_chunk_index": 2,
                "chunk_python_plugin": _DEMO_PLUGIN_REF,
            },
        },
        {
            "content": "原始证据：一件事：Alpha Package\n章节：涉及事项\n事项 A、事项 B。",
            "score": 0.96,
            "title": "alpha-related.txt",
            "metadata": {
                "case_title": "Alpha Package",
                "section_type": "related_services",
                "source_record_id": source_record_id,
                "source_chunk_index": 1,
                "chunk_python_plugin": _DEMO_PLUGIN_REF,
            },
        },
        {
            "content": "原始证据：一件事：Alpha Package\n章节：办理须知\n1. Alpha 条件说明。",
            "score": 0.7,
            "title": "alpha-process-1.txt",
            "metadata": {
                "case_title": "Alpha Package",
                "section_type": "process",
                "source_record_id": source_record_id,
                "source_chunk_index": 1,
                "chunk_python_plugin": _DEMO_PLUGIN_REF,
            },
        },
        {
            "content": "原始证据：一件事：Alpha Package\n章节：申请材料\n主要材料：申请表。",
            "score": 0.95,
            "title": "alpha-materials.txt",
            "metadata": {
                "case_title": "Alpha Package",
                "section_type": "materials",
                "source_record_id": source_record_id,
                "chunk_python_plugin": _DEMO_PLUGIN_REF,
            },
        },
        {
            "content": "原始证据：一件事：Alpha Package\n章节：办理渠道\n线上申请。",
            "score": 0.94,
            "title": "alpha-channels.txt",
            "metadata": {
                "case_title": "Alpha Package",
                "section_type": "channels",
                "source_record_id": source_record_id,
                "chunk_python_plugin": _DEMO_PLUGIN_REF,
            },
        },
    ]

    compacted = dify_api._compact_records_for_response(
        records,
        query="我想办理“Alpha Package”，请同时说明涉及事项、主要材料和办理渠道。",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert len(compacted) == 1
    content = compacted[0]["content"]
    assert content.index("1. Alpha 条件说明") < content.index("2. Beta 条件说明")
    assert compacted[0]["metadata"]["dify_composite_section_types"] == [
        "related_services",
        "process",
        "materials",
        "channels",
    ]


def test_dify_mixed_intent_compacts_unquoted_exact_entity_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        anchor_binding={"enabled": True, "anchor_fields": ["service_name"], "slot_fields": ["section_type"]},
        query_expansion_values=[
            {"metadata": "section_type", "value": "conditions", "terms": ["条件"]},
            {"metadata": "section_type", "value": "processing_time", "terms": ["时限"]},
            {"metadata": "section_type", "value": "contacts", "terms": ["电话"]},
        ],
    )
    exact_record = {
        "content": (
            "答案要点：问题：Alpha Desk 条件 时限 电话；答案：事项名称：Alpha Desk；"
            "办理地点：政务中心；咨询方式：0519-00000000；受理条件：符合条件；承诺办结时限：1个工作日。"
        ),
        "score": 0.72,
        "title": "alpha-service.txt",
        "metadata": {"service_name": "Alpha Desk", "chunk_python_plugin": _DEMO_PLUGIN_REF},
    }
    adjacent_record = {
        "content": (
            "答案要点：问题：Alpha Desk 条件 时限 电话；答案：事项名称：Alpha Related；"
            "办理地点：另一个窗口；咨询方式：0519-11111111；受理条件：相邻事项条件；承诺办结时限：2个工作日。"
        ),
        "score": 0.99,
        "title": "alpha-related.txt",
        "metadata": {"service_name": "Alpha Related", "chunk_python_plugin": _DEMO_PLUGIN_REF},
    }

    compacted = dify_api._compact_records_for_response(
        [adjacent_record, exact_record],
        query="Alpha Desk 条件 时限 电话",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert compacted == [exact_record]


def test_dify_mixed_intent_keeps_slot_records_over_single_exact_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        anchor_binding={"enabled": True, "anchor_fields": ["case_title"], "slot_fields": ["section_type"]},
        query_expansion_values=[
            {"metadata": "section_type", "value": "related_services", "terms": ["涉及事项"]},
            {"metadata": "section_type", "value": "materials", "terms": ["材料"]},
            {"metadata": "section_type", "value": "channels", "terms": ["渠道"]},
        ],
    )
    summary_record = {
        "content": "答案要点：事项名称：Alpha Package；办理材料：申请表；办理渠道：线上办理。",
        "score": 0.99,
        "title": "alpha-summary.txt",
        "metadata": {"case_title": "Alpha Package", "chunk_python_plugin": _DEMO_PLUGIN_REF},
    }
    related_record = {
        "content": "原始证据：一件事：Alpha Package\n章节：涉及事项\n事项 A、事项 B。",
        "score": 0.95,
        "title": "alpha-related.txt",
        "metadata": {
            "case_title": "Alpha Package",
            "section_type": "related_services",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }

    compacted = dify_api._compact_records_for_response(
        [summary_record, related_record],
        query="Alpha Package 涉及事项 材料 渠道",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert compacted == [summary_record, related_record]


def test_dify_metadata_anchor_bonus_matches_case_title_overlap() -> None:
    import app.api.v1.integrations_dify as dify_api

    record = {
        "content": "一件事：开办餐饮店“一件事”\n章节：系统入口",
        "metadata": {
            "case_title": "开办餐饮店“一件事”",
            "chunk_kind": "one_thing_operation_entry",
        },
    }

    assert (
        dify_api._record_metadata_anchor_bonus(
            record,
            query="餐饮店设立“一件事”办理入口在哪里",
        )
        >= 0.1
    )


def test_dify_metadata_anchor_confident_for_contained_case_title() -> None:
    import app.api.v1.integrations_dify as dify_api

    record = {
        "content": "一件事：开办餐饮店“一件事”\n章节：系统入口",
        "metadata": {
            "case_title": "开办餐饮店“一件事”",
            "chunk_kind": "one_thing_operation_entry",
        },
    }

    assert dify_api._records_have_confident_metadata_anchor(
        [record],
        query="开办餐饮店“一件事”在哪里进入办理",
    )


def test_dify_metadata_anchor_title_terms_include_short_cjk_entity_terms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)

    terms = dify_api._metadata_anchor_title_query_terms(
        "餐饮店设立“一件事”办理入口在哪里",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert "餐饮店" in terms
    assert "入口在哪里" not in "".join(terms[:6])


def test_dify_service_anchor_priority_ignores_generic_how_to_phrases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)

    assert not dify_api._query_prefers_service_anchor(
        "居家适老化改造通过苏服办APP如何办理",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )
    assert not dify_api._query_prefers_service_anchor(
        "办理抵押权注销的收费标准是什么？",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )
    assert dify_api._query_prefers_service_anchor(
        "常州市护士执业证书遗失补办在哪里办理",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )
    assert dify_api._query_prefers_service_anchor(
        "办理「危险化学品经营许可首次申请」前，办理地点在哪里？",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )
    assert dify_api._query_prefers_service_anchor(
        "麻烦查一下旅客运输船舶营运证的配发（新增），行使层级、办理地点、法定办结时限。",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )
    service_terms = dify_api._metadata_anchor_service_name_query_terms(
        "保健食品广告审查是不是能办？办理形式、办理地点、承诺办结时限，最好给我依据。",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )
    assert service_terms[0] == "保健食品广告审查"
    assert dify_api._query_has_specific_service_anchor_candidate(
        "保健食品广告审查是不是能办？办理形式、办理地点、承诺办结时限，最好给我依据。",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )
    assert "service_name" in dify_api._exact_query_anchor_fields_for_policy_refs((_DEMO_PLUGIN_REF,))
    compacted = dify_api._compact_mixed_intent_exact_anchor_records(
        [
            {
                "content": "事项名称：抵押权转移登记\n行使层级：市级\n办理地点：A窗口\n办理材料：申请表",
                "score": 0.84,
                "title": "service.txt",
                "metadata": {"service_name": "抵押权转移登记"},
            }
        ],
        query="请按政务知识库口径核对“抵押权转移登记”：行使层级、办理地点、办理材料。",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )
    assert len(compacted) == 1


def test_dify_question_anchor_strength_matches_reordered_cjk_question() -> None:
    import app.api.v1.integrations_dify as dify_api

    record = {
        "content": "问题：苏服办APP如何办居家适老化改造\n答案：在苏服办APP内搜索居家适老化改造。",
        "metadata": {
            "question": "苏服办APP如何办居家适老化改造",
            "chunk_kind": "qa_pair",
        },
    }

    strength = dify_api._record_question_anchor_strength(
        record,
        query="居家适老化改造通过苏服办APP如何办理",
    )

    assert strength >= dify_api._QUESTION_ANCHOR_COMPACTION_MIN_STRENGTH


def test_dify_question_anchor_strength_prefers_specific_question_overlap() -> None:
    import app.api.v1.integrations_dify as dify_api

    query = "三井街道公安窗口搬迁至哪里"
    broad_record = {
        "content": "问题：三井街道便民服务中心公安窗口可以办理哪些户口业务？\n答案：户籍业务说明。",
        "metadata": {
            "question": "三井街道便民服务中心公安窗口可以办理哪些户口业务？",
            "chunk_kind": "qa_pair",
        },
    }
    specific_record = {
        "content": "问题：三井街道公安窗口搬到哪里了？\n答案：搬迁地址说明。",
        "metadata": {
            "question": "三井街道公安窗口搬到哪里了？",
            "chunk_kind": "qa_pair",
        },
    }

    broad_strength = dify_api._record_question_anchor_strength(broad_record, query=query)
    specific_strength = dify_api._record_question_anchor_strength(specific_record, query=query)

    assert specific_strength > broad_strength
    assert specific_strength >= dify_api._QUESTION_ANCHOR_COMPACTION_MIN_STRENGTH


def test_dify_question_anchor_strength_accepts_high_overlap_declarative_rewrite() -> None:
    import app.api.v1.integrations_dify as dify_api

    record = {
        "content": "问题：道路运输从业人员出现哪些情况会被注销从业资格证件？\n答案：注销情形说明。",
        "metadata": {
            "question": "道路运输从业人员出现哪些情况会被注销从业资格证件？",
            "chunk_kind": "qa_pair",
        },
    }

    strength = dify_api._record_question_anchor_strength(
        record,
        query="道路运输从业人员从业资格证件注销情形",
    )

    assert strength >= dify_api._QUESTION_ANCHOR_COMPACTION_MIN_STRENGTH


def test_dify_metadata_anchor_db_prefers_question_anchor_for_question_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    qa_row = {
        "chunk_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "dataset_id": dataset_id,
        "chunk_index": 1,
        "page_number": None,
        "filename": "qa.txt",
        "content": "问题：网上申请调解后，是否影响法定诉权？\n答案：不影响。",
        "metadata": {
            "question": "网上申请调解后，是否影响法定诉权？",
            "chunk_kind": "qa_pair",
            "source_record_id": "qa-expected",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }
    service_row = {
        "chunk_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "dataset_id": dataset_id,
        "chunk_index": 2,
        "page_number": None,
        "filename": "service.txt",
        "content": "事项名称：劳动人事争议调解申请\n办理地点：服务中心窗口。",
        "metadata": {
            "service_name": "劳动人事争议调解申请",
            "chunk_kind": "service_item_full",
            "source_record_id": "service-wrong",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }
    queried_fields: list[str] = []

    def _condition_values(condition):  # noqa: ANN001, ANN202
        values: list[str] = []

        def walk(node):  # noqa: ANN001, ANN202
            value = getattr(node, "value", None)
            if isinstance(value, str):
                values.append(value)
            elif isinstance(value, dict):
                for key, raw_items in value.items():
                    values.append(str(key))
                    items = raw_items if isinstance(raw_items, list | tuple | set) else [raw_items]
                    values.extend(str(item) for item in items)
            for attr in ("left", "right"):
                child = getattr(node, attr, None)
                if child is not None:
                    walk(child)
            clauses = getattr(node, "clauses", None)
            if clauses is not None:
                for child in clauses:
                    walk(child)

        walk(condition)
        return values

    class _FakeQuery:
        def __init__(self) -> None:
            self._condition = None

        def join(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def filter(self, *_conditions):  # noqa: ANN002, ANN202
            self._condition = _conditions[-1] if _conditions else None
            return self

        def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def limit(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def all(self):  # noqa: ANN202
            values = _condition_values(self._condition)
            if "question" in values:
                queried_fields.append("question")
                if any("申请调解" in value or "影响法定" in value for value in values):
                    return [qa_row]
            if "service_name" in values:
                queried_fields.append("service_name")
                return [service_row]
            return []

    class _FakeDB:
        def execute(self, _statement):  # noqa: ANN001, ANN202
            return None

        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return _FakeQuery()

        def rollback(self) -> None:
            return None

    _patch_demo_policy(monkeypatch, dify_api)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )

    fallback_records = dify_api._metadata_anchor_db_fallback_records(
        db=_FakeDB(),
        tenant_id=tenant_id,
        dataset_ids=[dataset_id],
        query="网上申请调解是否影响法定诉权",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[],
    )

    assert fallback_records[0]["metadata"]["source_record_id"] == "qa-expected"
    assert queried_fields[0] == "question"
    assert "service_name" not in queried_fields

    queried_fields.clear()
    fallback_records = dify_api._metadata_anchor_db_fallback_records(
        db=_FakeDB(),
        tenant_id=tenant_id,
        dataset_ids=[dataset_id],
        query="网上申请调解是否影响法定诉权",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[
            {
                "content": "事项名称：劳动人事争议调解申请\n办理地点：服务中心窗口。",
                "score": 0.91,
                "title": "service.txt",
                "metadata": {
                    "service_name": "劳动人事争议调解申请",
                    "chunk_kind": "service_item_full",
                    "source_record_id": "service-wrong",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                },
            }
        ],
    )

    assert fallback_records[0]["metadata"]["source_record_id"] == "qa-expected"
    assert queried_fields[0] == "question"


def test_dify_metadata_anchor_db_question_query_stops_after_question_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    queried_fields: list[str] = []

    def _condition_values(condition):  # noqa: ANN001, ANN202
        values: list[str] = []

        def walk(node):  # noqa: ANN001, ANN202
            value = getattr(node, "value", None)
            if isinstance(value, str):
                values.append(value)
            elif isinstance(value, dict):
                for key, raw_items in value.items():
                    values.append(str(key))
                    items = raw_items if isinstance(raw_items, list | tuple | set) else [raw_items]
                    values.extend(str(item) for item in items)
            for attr in ("left", "right"):
                child = getattr(node, attr, None)
                if child is not None:
                    walk(child)
            clauses = getattr(node, "clauses", None)
            if clauses is not None:
                for child in clauses:
                    walk(child)

        walk(condition)
        return values

    class _FakeQuery:
        def __init__(self) -> None:
            self._condition = None

        def join(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def filter(self, *_conditions):  # noqa: ANN002, ANN202
            self._condition = _conditions[-1] if _conditions else None
            return self

        def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def limit(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def all(self):  # noqa: ANN202
            values = _condition_values(self._condition)
            if "question" in values:
                queried_fields.append("question")
            if "service_name" in values:
                queried_fields.append("service_name")
            if "case_title" in values or "source_topic" in values or "title" in values:
                queried_fields.append("title")
            return []

    class _FakeDB:
        def execute(self, _statement):  # noqa: ANN001, ANN202
            return None

        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return _FakeQuery()

        def rollback(self) -> None:
            return None

    _patch_demo_policy(monkeypatch, dify_api)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )

    fallback_records = dify_api._metadata_anchor_db_fallback_records(
        db=_FakeDB(),
        tenant_id=uuid.uuid4(),
        dataset_ids=[uuid.uuid4()],
        query="公积金账户有挂账余额的情况下，怎么退回资金？",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[],
    )

    assert fallback_records == []
    assert queried_fields
    assert set(queried_fields) == {"question"}


def test_dify_metadata_anchor_db_prefers_service_anchor_for_service_intent_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    service_row = {
        "chunk_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "dataset_id": dataset_id,
        "chunk_index": 1,
        "page_number": None,
        "filename": "service.txt",
        "content": "事项名称：护士执业证书遗失补办\n办理地点：常州市政务服务中心。",
        "metadata": {
            "service_name": "护士执业证书遗失补办",
            "chunk_kind": "service_item_full",
            "source_record_id": "service-expected",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }
    qa_row = {
        "chunk_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "dataset_id": dataset_id,
        "chunk_index": 2,
        "page_number": None,
        "filename": "qa.txt",
        "content": "问题：护士执业证书补办需要哪些材料？\n答案：材料说明。",
        "metadata": {
            "question": "护士执业证书补办需要哪些材料？",
            "chunk_kind": "qa_pair",
            "source_record_id": "qa-wrong",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }
    queried_fields: list[str] = []

    def _condition_values(condition):  # noqa: ANN001, ANN202
        values: list[str] = []

        def walk(node):  # noqa: ANN001, ANN202
            value = getattr(node, "value", None)
            if isinstance(value, str):
                values.append(value)
            for attr in ("left", "right"):
                child = getattr(node, attr, None)
                if child is not None:
                    walk(child)
            clauses = getattr(node, "clauses", None)
            if clauses is not None:
                for child in clauses:
                    walk(child)

        walk(condition)
        return values

    class _FakeQuery:
        def __init__(self) -> None:
            self._condition = None

        def join(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def filter(self, *_conditions):  # noqa: ANN002, ANN202
            self._condition = _conditions[-1] if _conditions else None
            return self

        def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def limit(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def all(self):  # noqa: ANN202
            values = _condition_values(self._condition)
            if "service_name" in values:
                queried_fields.append("service_name")
                if any("护士执业证书遗失补办" in value for value in values):
                    return [service_row]
            if "question" in values:
                queried_fields.append("question")
                if any("护士执业证书" in value for value in values):
                    return [qa_row]
            return []

    class _FakeDB:
        def execute(self, _statement):  # noqa: ANN001, ANN202
            return None

        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return _FakeQuery()

        def rollback(self) -> None:
            return None

    _patch_demo_policy(monkeypatch, dify_api)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )

    fallback_records = dify_api._metadata_anchor_db_fallback_records(
        db=_FakeDB(),
        tenant_id=tenant_id,
        dataset_ids=[dataset_id],
        query="常州市护士执业证书遗失补办在哪里办理",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[],
    )

    assert fallback_records[0]["metadata"]["source_record_id"] == "service-expected"
    assert queried_fields[0] == "service_name"


def test_dify_metadata_anchor_db_can_prefer_question_anchor_for_mixed_subquery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    service_row = {
        "chunk_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "dataset_id": dataset_id,
        "chunk_index": 1,
        "page_number": None,
        "filename": "service.txt",
        "content": "事项名称：人员参保登记\n办理地点：普通政务服务中心。",
        "metadata": {
            "service_name": "人员参保登记",
            "chunk_kind": "service_item_full",
            "source_record_id": "service-default",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }
    qa_row = {
        "chunk_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "dataset_id": dataset_id,
        "chunk_index": 2,
        "page_number": None,
        "filename": "qa.txt",
        "content": "问题：请问我可以在哪里办理人员参保登记？\n答案：请拨打街道为民服务中心咨询。",
        "metadata": {
            "question": "请问我可以在哪里办理人员参保登记？",
            "chunk_kind": "qa_pair",
            "source_record_id": "qa-subquery",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }
    queried_fields: list[str] = []

    def _condition_values(condition):  # noqa: ANN001, ANN202
        values: list[str] = []

        def walk(node):  # noqa: ANN001, ANN202
            value = getattr(node, "value", None)
            if isinstance(value, str):
                values.append(value)
            for attr in ("left", "right"):
                child = getattr(node, attr, None)
                if child is not None:
                    walk(child)
            clauses = getattr(node, "clauses", None)
            if clauses is not None:
                for child in clauses:
                    walk(child)

        walk(condition)
        return values

    class _FakeQuery:
        def __init__(self) -> None:
            self._condition = None

        def join(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def filter(self, *_conditions):  # noqa: ANN002, ANN202
            self._condition = _conditions[-1] if _conditions else None
            return self

        def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def limit(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def all(self):  # noqa: ANN202
            values = _condition_values(self._condition)
            if "question" in values:
                queried_fields.append("question")
                if any("人员参保登记" in value for value in values):
                    return [qa_row]
            if "service_name" in values:
                queried_fields.append("service_name")
                if any("人员参保登记" in value for value in values):
                    return [service_row]
            return []

    class _FakeDB:
        def execute(self, _statement):  # noqa: ANN001, ANN202
            return None

        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return _FakeQuery()

        def rollback(self) -> None:
            return None

    _patch_demo_policy(monkeypatch, dify_api)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )

    fallback_records = dify_api._metadata_anchor_db_fallback_records(
        db=_FakeDB(),
        tenant_id=tenant_id,
        dataset_ids=[dataset_id],
        query="人员参保登记在哪里办理",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[],
    )

    assert fallback_records[0]["metadata"]["source_record_id"] == "service-default"
    assert queried_fields[0] == "service_name"

    queried_fields.clear()
    fallback_records = dify_api._metadata_anchor_db_fallback_records(
        db=_FakeDB(),
        tenant_id=tenant_id,
        dataset_ids=[dataset_id],
        query="人员参保登记在哪里办理",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[],
        prefer_question_anchor_first=True,
    )

    assert fallback_records[0]["metadata"]["source_record_id"] == "qa-subquery"
    assert queried_fields[0] == "question"


def test_dify_metadata_anchor_db_checks_question_first_for_explicit_question_service_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    qa_row = {
        "chunk_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "dataset_id": dataset_id,
        "chunk_index": 1,
        "page_number": None,
        "filename": "qa.txt",
        "content": "问题：请问可以在哪里办理企业社会保险登记？\n答案：可到区域乙政务服务中心办理。",
        "metadata": {
            "question": "请问可以在哪里办理企业社会保险登记？",
            "chunk_kind": "qa_pair",
            "source_record_id": "qa-expected",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }
    service_row = {
        "chunk_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "dataset_id": dataset_id,
        "chunk_index": 2,
        "page_number": None,
        "filename": "service.txt",
        "content": "事项名称：企业社会保险登记\n办理地点：普通服务中心窗口。",
        "metadata": {
            "service_name": "企业社会保险登记",
            "chunk_kind": "service_item_full",
            "source_record_id": "service-wrong",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }
    queried_fields: list[str] = []

    def _condition_values(condition):  # noqa: ANN001, ANN202
        values: list[str] = []

        def walk(node):  # noqa: ANN001, ANN202
            value = getattr(node, "value", None)
            if isinstance(value, str):
                values.append(value)
            for attr in ("left", "right"):
                child = getattr(node, attr, None)
                if child is not None:
                    walk(child)
            clauses = getattr(node, "clauses", None)
            if clauses is not None:
                for child in clauses:
                    walk(child)

        walk(condition)
        return values

    class _FakeQuery:
        def __init__(self) -> None:
            self._condition = None

        def join(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def filter(self, *_conditions):  # noqa: ANN002, ANN202
            self._condition = _conditions[-1] if _conditions else None
            return self

        def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def limit(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def all(self):  # noqa: ANN202
            values = _condition_values(self._condition)
            if "question" in values:
                queried_fields.append("question")
                if any("企业社会保险登记" in value for value in values):
                    return [qa_row]
            if "service_name" in values:
                queried_fields.append("service_name")
                return [service_row]
            return []

    class _FakeDB:
        def execute(self, _statement):  # noqa: ANN001, ANN202
            return None

        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return _FakeQuery()

        def rollback(self) -> None:
            return None

    _patch_demo_policy(monkeypatch, dify_api)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )

    fallback_records = dify_api._metadata_anchor_db_fallback_records(
        db=_FakeDB(),
        tenant_id=tenant_id,
        dataset_ids=[dataset_id],
        query="请问可以在哪里办理企业社会保险登记",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[],
    )

    assert fallback_records[0]["metadata"]["source_record_id"] == "qa-expected"
    assert queried_fields[0] == "question"
    assert "service_name" not in queried_fields


def test_dify_metadata_anchor_db_does_not_text_scan_metadata_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    cast_called = False

    class _FakeQuery:
        def join(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def filter(self, *_conditions):  # noqa: ANN002, ANN202
            return self

        def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def limit(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def all(self):  # noqa: ANN202
            return []

    class _FakeDB:
        def execute(self, _statement):  # noqa: ANN001, ANN202
            return None

        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return _FakeQuery()

        def rollback(self) -> None:
            return None

    def _record_cast(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        nonlocal cast_called
        cast_called = True
        return object()

    _patch_demo_policy(monkeypatch, dify_api)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_TEXT_SCAN_ENABLED",
        False,
        raising=False,
    )
    monkeypatch.setattr(dify_api, "sql_cast", _record_cast)

    fallback_records = dify_api._metadata_anchor_db_fallback_records(
        db=_FakeDB(),
        tenant_id=uuid.uuid4(),
        dataset_ids=[uuid.uuid4()],
        query="公积金账户有挂账余额的情况下，怎么退回资金？",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[],
    )

    assert fallback_records == []
    assert cast_called is False


def test_dify_metadata_anchor_db_skips_when_existing_records_have_confident_metadata_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    query_count = 0

    class _FakeQuery:
        def join(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def filter(self, *_conditions):  # noqa: ANN002, ANN202
            return self

        def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def limit(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def all(self):  # noqa: ANN202
            return []

    class _FakeDB:
        def execute(self, _statement):  # noqa: ANN001, ANN202
            return None

        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            nonlocal query_count
            query_count += 1
            return _FakeQuery()

    _patch_demo_policy(monkeypatch, dify_api)

    fallback_records = dify_api._metadata_anchor_db_fallback_records(
        db=_FakeDB(),
        tenant_id=uuid.uuid4(),
        dataset_ids=[uuid.uuid4()],
        query="经开区房地产经纪机构备案在哪里办理",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[
            {
                "content": "事项名称：房地产经纪机构备案\n办理地点：常州市政务服务中心。",
                "score": 0.91,
                "title": "service.txt",
                "metadata": {
                    "service_name": "房地产经纪机构备案",
                    "chunk_kind": "service_item_full",
                    "source_record_id": "service-expected",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
                },
            }
        ],
    )

    assert fallback_records == []
    assert query_count == 0


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


def test_dify_retrieval_runs_supplemental_queries_for_mixed_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls: list[tuple[str, int, int | None, bool | None]] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_HIGH_CONFIDENCE_ENABLED",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            '{"city": {'
            f'"dataset_ids": ["{dataset_id}"], '
            f'"plugin_refs": ["{_DEMO_PLUGIN_REF}"]'
            "}}"
        ),
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    _patch_demo_policy(
        monkeypatch,
        dify_api,
        mixed_intent_leading_noise_terms=["我想", "了解"],
        mixed_intent_subject_terms=["需要什么材料", "怎么查询"],
    )

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        query = kwargs["query"]
        calls.append((query, kwargs["top_k"], kwargs["requested_top_k"], kwargs.get("enable_reranker")))
        if query == "身份证补领需要什么材料":
            return [
                {
                    "chunk_content": "身份证补领需要居民户口簿或居住证等材料。",
                    "relevance_score": 0.82,
                    "document_name": "身份证补领材料.txt",
                    "chunk_id": str(uuid.uuid4()),
                    "dataset_id": str(dataset_id),
                }
            ]
        if query == "身份证补领怎么查询办理进度":
            return [
                {
                    "chunk_content": "身份证办理进度可通过苏证通 APP 查询。",
                    "relevance_score": 0.81,
                    "document_name": "身份证进度查询.txt",
                    "chunk_id": str(uuid.uuid4()),
                    "dataset_id": str(dataset_id),
                }
            ]
        return [
            {
                "chunk_content": "居民身份证有效期说明。",
                "relevance_score": 0.9,
                "document_name": "身份证有效期.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
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
            "query": "我想同时了解身份证补领需要什么材料，另外怎么查询办理进度？",
            "retrieval_setting": {"top_k": 3, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls == [
        ("我想同时了解身份证补领需要什么材料，另外怎么查询办理进度？", 20, 3, False),
        ("身份证补领需要什么材料", 3, 3, False),
        ("身份证补领怎么查询办理进度", 3, 3, False),
    ]
    assert {record["title"] for record in res.json()["records"]} == {
        "身份证有效期.txt",
        "身份证补领材料.txt",
        "身份证进度查询.txt",
    }


def test_dify_retrieval_skips_mixed_intent_queries_when_exact_anchor_is_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls: list[str] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_HIGH_CONFIDENCE_ENABLED",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            '{"city": {'
            f'"dataset_ids": ["{dataset_id}"], '
            f'"plugin_refs": ["{_DEMO_PLUGIN_REF}"]'
            "}}"
        ),
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    _patch_demo_policy(
        monkeypatch,
        dify_api,
        anchor_binding={"enabled": True, "anchor_fields": ["service_name"], "slot_fields": ["section_type"]},
        query_expansion_values=[
            {"metadata": "section_type", "value": "materials", "terms": ["需要哪些材料"]},
            {"metadata": "section_type", "value": "channels", "terms": ["在哪里办理"]},
        ],
        mixed_intent_leading_noise_terms=["我想", "了解"],
        mixed_intent_subject_terms=["需要什么材料", "在哪里办理"],
    )

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        calls.append(kwargs["query"])
        return [
            {
                "chunk_content": (
                    "答案要点：事项名称：Alpha Desk；办理材料：营业执照；办理地点：政务中心；收费情况：不收费\n\n"
                    "原始证据：事项名称：Alpha Desk\n办理材料：营业执照\n办理地点：政务中心\n收费情况：不收费"
                ),
                "relevance_score": 0.92,
                "document_name": "alpha-service.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {"service_name": "Alpha Desk", "chunk_python_plugin": _DEMO_PLUGIN_REF},
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
            "query": "我要办理“Alpha Desk”，需要哪些材料？同时告诉我在哪里办理、是否收费。",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls == ["我要办理“Alpha Desk”，需要哪些材料？同时告诉我在哪里办理、是否收费。"]
    assert [record["title"] for record in res.json()["records"]] == ["alpha-service.txt"]


def test_dify_retrieval_skips_unquoted_mixed_intent_when_exact_anchor_record_is_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls: list[str] = []
    query = "城市建筑垃圾处置核准这个事项，帮我直接说清楚：行使层级、受理条件、承诺办结时限。"

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_HIGH_CONFIDENCE_ENABLED",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            '{"city": {'
            f'"dataset_ids": ["{dataset_id}"], '
            f'"plugin_refs": ["{_DEMO_PLUGIN_REF}"]'
            "}}"
        ),
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    _patch_demo_policy(monkeypatch, dify_api)

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        calls.append(kwargs["query"])
        return [
            {
                "chunk_content": (
                    "事项名称：城市建筑垃圾处置核准\n"
                    "行使层级：县级\n"
                    "受理条件：建设单位、施工单位或者运输单位可申请。\n"
                    "承诺办结时限：1个工作日\n"
                    "收费情况：不收费"
                ),
                "relevance_score": 0.94,
                "document_name": "天宁区事项清单.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {
                    "service_name": "城市建筑垃圾处置核准",
                    "chunk_kind": "service_item_full",
                    "chunk_python_plugin": _DEMO_PLUGIN_REF,
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
            "query": query,
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls == [query]
    assert [record["title"] for record in res.json()["records"]] == ["天宁区事项清单.txt"]


def test_dify_retrieval_does_not_skip_mixed_intent_queries_for_unquoted_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls: list[str] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_HIGH_CONFIDENCE_ENABLED",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            '{"city": {'
            f'"dataset_ids": ["{dataset_id}"], '
            f'"plugin_refs": ["{_DEMO_PLUGIN_REF}"]'
            "}}"
        ),
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    _patch_demo_policy(
        monkeypatch,
        dify_api,
        query_expansion_values=[
            {"metadata": "section_type", "value": "channels", "terms": ["在哪里办理"]},
            {"metadata": "section_type", "value": "processing_time", "terms": ["需要多长时间"]},
            {"metadata": "section_type", "value": "fees", "terms": ["是否收费"]},
        ],
        mixed_intent_leading_noise_terms=["关于"],
        mixed_intent_subject_terms=["在哪里办理", "需要多长时间", "是否收费"],
    )

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        query = kwargs["query"]
        calls.append(query)
        title_by_query = {
            "Alpha Desk在哪里办理": "alpha-place.txt",
            "Alpha Desk需要多长时间": "alpha-time.txt",
            "Alpha Desk是否收费": "alpha-fee.txt",
        }
        if query in title_by_query:
            return [
                {
                    "chunk_content": f"答案要点：问题：{query}；答案：精确答案。",
                    "relevance_score": 0.9,
                    "document_name": title_by_query[query],
                    "chunk_id": str(uuid.uuid4()),
                    "dataset_id": str(dataset_id),
                    "metadata": {"question": query, "chunk_python_plugin": _DEMO_PLUGIN_REF},
                }
            ]
        return [
            {
                "chunk_content": "答案要点：事项名称：Alpha Desk；办理地点：政务中心；收费情况：不收费",
                "relevance_score": 0.92,
                "document_name": "alpha-service.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {"service_name": "Alpha Desk", "chunk_python_plugin": _DEMO_PLUGIN_REF},
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
            "query": "关于Alpha Desk，请合并回答：在哪里办理、需要多长时间、是否收费？",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls == [
        "关于Alpha Desk，请合并回答：在哪里办理、需要多长时间、是否收费？",
        "Alpha Desk在哪里办理",
        "Alpha Desk需要多长时间",
        "Alpha Desk是否收费",
    ]


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


def test_dify_strong_question_anchor_rejects_canonical_intent_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    record = {
        "content": "答案要点：申请通过后通常会在若干工作日内到账。",
        "score": 0.99,
        "title": "faq.txt",
        "metadata": {
            "question": "汽车置换补贴通过了多久放款到账",
            "primary_alias": "汽车置换补贴多久到账",
            "aliases": ["汽车置换补贴怎么申请"],
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }
    query = "汽车置换补贴怎么申请"

    assert dify_api._record_question_anchor_strength(
        record,
        query=query,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    ) >= dify_api._QUESTION_ANCHOR_COMPACTION_MIN_STRENGTH
    assert dify_api._record_question_anchor_has_intent_conflict(
        record,
        query=query,
        anchor_fields=("question", "primary_alias"),
    )
    assert not dify_api._records_have_strong_question_anchor(
        [record],
        query=query,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )
    assert dify_api._metadata_anchor_fallback_record_score(
        record,
        query=query,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    ) == 0.0


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


def test_dify_record_ranking_prefers_declared_anchor_over_slot_only_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: {
            "schema": "mimirq.retrieval_policy.v1",
            "anchor_binding": {
                "enabled": True,
                "anchor_fields": ["case_title"],
                "slot_fields": ["field_kind"],
                "slot_only_penalty": 0.35,
                "anchor_match_bonus": 0.35,
                "anchor_slot_match_bonus": 0.1,
            },
            "query_expansion_values": [
                {"metadata": "field_kind", "value": "fee", "terms": ["fee", "cost"]},
            ],
        }
        if ref == plugin_ref
        else {},
        raising=False,
    )
    records = [
        {
            "content": "slot-only generic fee answer",
            "score": 0.92,
            "title": "generic-fee.md",
            "metadata": {"chunk_python_plugin": plugin_ref, "case_title": "Beta Permit", "field_kind": "fee"},
        },
        {
            "content": "anchored Alpha Permit fee answer",
            "score": 0.66,
            "title": "alpha-permit.md",
            "metadata": {"chunk_python_plugin": plugin_ref, "case_title": "Alpha Permit", "field_kind": "fee"},
        },
    ]

    dify_api._sort_records_for_query(records, query="Alpha Permit fee")

    assert [item["content"] for item in records] == [
        "anchored Alpha Permit fee answer",
        "slot-only generic fee answer",
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


def test_dify_record_ranking_protects_exact_service_anchor_from_generic_qa_policy_boost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        boost_fields=[
            {"metadata": "question", "weight": 2.4, "match": "fuzzy_overlap"},
            {"metadata": "service_name", "weight": 1.7, "match": "contains"},
        ],
        rerank_features=["question", "service_name"],
        anchor_binding={
            "enabled": True,
            "anchor_fields": ["service_name"],
            "slot_fields": ["question"],
            "anchor_match_bonus": 0.35,
            "slot_only_penalty": 0.35,
            "anchor_mismatch_penalty": 0.35,
        },
    )
    records = [
        {
            "content": "问题：临时救助办理条件是什么？\n答案：临时救助条件说明。",
            "score": 0.50,
            "title": "qa.txt",
            "metadata": {
                "question": "临时救助办理条件是什么？",
                "chunk_kind": "qa_pair",
                "chunk_python_plugin": _DEMO_PLUGIN_REF,
            },
        },
        {
            "content": (
                "事项名称：城市建筑垃圾处置核准\n"
                "办理地点：13号城管综合窗口\n"
                "行使层级：区级\n"
                "受理条件：申请人提交申办材料齐全、符合法定形式\n"
                "承诺办结时限：5个工作日"
            ),
            "score": 0.73,
            "title": "service.txt",
            "metadata": {
                "service_name": "城市建筑垃圾处置核准",
                "chunk_kind": "service_item_full",
                "chunk_python_plugin": _DEMO_PLUGIN_REF,
            },
        },
    ]

    dify_api._sort_records_for_query(
        records,
        query="城市建筑垃圾处置核准这个事项，帮我直接说清楚：行使层级、受理条件、承诺办结时限。",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert records[0]["metadata"]["service_name"] == "城市建筑垃圾处置核准"
    assert records[1]["metadata"]["question"] == "临时救助办理条件是什么？"


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


def test_dify_fast_latency_profile_uses_single_small_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON", f'{{"city": "{dataset_id}"}}', raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX", 10, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MIN", 20, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MULTIPLIER", 4, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX", 50, raising=False)
    monkeypatch.setattr(dify_api.settings, "ENABLE_RERANKER", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RERANKER_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUPPLEMENT_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED", False, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_ON_DEMAND_ENABLED", True, raising=False)

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        calls.append(dict(kwargs))
        return [
            {
                "chunk_content": "Alpha Desk escalation path",
                "relevance_score": 0.91,
                "document_name": "policy.md",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
            }
        ]

    def _unexpected_metadata_fallback(**_kwargs):  # noqa: ANN003, ANN202
        raise AssertionError("fast latency profile must not run metadata anchor fallback")

    def _unexpected_reranker(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("fast latency profile must not run final reranker")

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_metadata_anchor_db_fallback_records", _unexpected_metadata_fallback, raising=True)
    monkeypatch.setattr(dify_api, "get_reranker", _unexpected_reranker, raising=True)
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
            "retrieval_setting": {
                "top_k": 2,
                "score_threshold": 0.0,
                "latency_profile": "fast",
                "enable_kg_query_expansion": True,
                "enable_kg_chunk_injection": True,
                "enable_kg_chunk_boost": True,
            },
        },
    )

    assert res.status_code == 200, res.text
    assert len(calls) == 1
    assert calls[0]["top_k"] == 2
    assert calls[0]["requested_top_k"] == 2
    assert calls[0]["retrieval_mode"] == "vector"
    assert calls[0]["enable_reranker"] is False
    assert calls[0]["enable_kg_query_expansion"] is False
    assert calls[0]["enable_kg_chunk_injection"] is False
    assert calls[0]["enable_kg_chunk_boost"] is False


def test_dify_fast_latency_profile_limits_candidates_and_compacts_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    calls: list[dict[str, object]] = []
    _patch_demo_policy(monkeypatch, dify_api)

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": {{"dataset_ids": ["{dataset_id}"], "plugin_refs": ["{_DEMO_PLUGIN_REF}"]}}}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX", 10, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_CANDIDATE_TOP_K_MAX", 3, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_RESPONSE_TOP_K_MAX", 2, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_CONTENT_MAX_CHARS", 500, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED", False, raising=False)

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        calls.append(dict(kwargs))
        return [
            {
                "chunk_content": (
                    f"区县：常州市 | 事项名称：Alpha Desk {index} | 行使层级：市级 | "
                    "办理地点：A区1号窗口 | 收费情况：不收费 | 办理材料：申请表、身份证"
                ),
                "relevance_score": 0.9 - index * 0.01,
                "document_name": f"policy-{index}.md",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
            }
            for index in range(5)
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
            "query": "Alpha Desk 帮我核一下行使层级、办理地点、办理材料",
            "retrieval_setting": {
                "top_k": 5,
                "score_threshold": 0.0,
                "latency_profile": "fast",
            },
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert calls[0]["top_k"] == 3
    assert calls[0]["requested_top_k"] == 5
    assert len(body["records"]) == 2
    assert "行使层级：市级" in body["records"][0]["content"]
    assert "办理地点：A区1号窗口" in body["records"][0]["content"]
    assert "办理材料：申请表、身份证" in body["records"][0]["content"]
    assert "收费情况" not in body["records"][0]["content"]
    assert body["records"][0]["metadata"]["dify_fast_compacted"] is True


def test_dify_fast_response_enforces_total_context_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_RESPONSE_TOP_K_MAX", 3, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_CONTENT_MAX_CHARS", 500, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_TOTAL_CONTENT_MAX_CHARS", 200, raising=False)

    records = [
        {
            "content": (
                f"区县：常州市 | 事项名称：Alpha Desk {index} | 行使层级：市级 | "
                "办理地点：A区1号窗口 | 办理材料：申请表、身份证、授权书、经办人材料"
            ),
            "score": 0.9 - index * 0.01,
            "title": f"policy-{index}.md",
            "metadata": {},
        }
        for index in range(3)
    ]

    compacted = dify_api._compact_fast_records_for_response(
        records,
        query="Alpha Desk 帮我核一下行使层级、办理地点、办理材料",
        top_k=3,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert len(compacted) == 2
    assert sum(len(str(record["content"])) for record in compacted) <= 200
    assert compacted[0]["metadata"]["dify_fast_compacted"] is True
    assert compacted[0]["metadata"]["dify_fast_total_context_budget_chars"] == 200


def test_dify_fast_response_prefers_exact_field_label_over_generic_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        fast_response_field_rules=[
            {"label": "申请材料", "markers": ["申请材料", "材料"]},
            {"label": "精细化材料提醒", "markers": ["精细化材料提醒", "详细材料指南"]},
            {"label": "办理材料", "markers": ["办理材料", "材料"]},
        ],
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_CONTENT_MAX_CHARS", 500, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_TOTAL_CONTENT_MAX_CHARS", 800, raising=False)

    records = [
        {
            "content": (
                "区县：常州市\n"
                "事项名称：Alpha Desk\n"
                "申请材料：申请表、身份证、授权书\n"
                "精细化材料提醒：可在企业开办智能体查看详细材料指南。\n"
                "办理材料：申请表、身份证、授权书、经办人材料"
            ),
            "score": 0.91,
            "title": "policy.md",
            "metadata": {},
        }
    ]

    compacted = dify_api._compact_fast_records_for_response(
        records,
        query="Alpha Desk 的精细化材料提醒是什么？",
        top_k=1,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    content = compacted[0]["content"]
    assert "精细化材料提醒：可在企业开办智能体查看详细材料指南。" in content
    assert "申请材料：" not in content
    assert "办理材料：" not in content


def test_dify_fast_response_does_not_backfill_exact_field_with_generic_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        fast_response_field_rules=[
            {"label": "申请材料", "markers": ["申请材料", "材料"]},
            {"label": "精细化材料提醒", "markers": ["精细化材料提醒", "详细材料指南"]},
            {"label": "办理材料", "markers": ["办理材料", "材料"]},
        ],
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_CONTENT_MAX_CHARS", 500, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_TOTAL_CONTENT_MAX_CHARS", 800, raising=False)

    records = [
        {
            "content": (
                "区县：常州市\n"
                "事项名称：Beta Desk\n"
                "申请材料：申请表、身份证、授权书\n"
                "办理材料：申请表、身份证、授权书、经办人材料"
            ),
            "score": 0.88,
            "title": "policy.md",
            "metadata": {},
        }
    ]

    compacted = dify_api._compact_fast_records_for_response(
        records,
        query="Beta Desk 的精细化材料提醒是什么？",
        top_k=1,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    content = compacted[0]["content"]
    assert "区县：常州市" in content
    assert "事项名称：Beta Desk" in content
    assert "申请材料：" not in content
    assert "办理材料：" not in content


def test_dify_fast_response_can_compact_from_plugin_metadata_hints(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    response_hints = _demo_response_hints()
    response_hints["answer_highlight_metadata_fields"] = [  # type: ignore[index]
        {
            "metadata": "service_fields",
            "fields": ["涉及事项", "申请材料", "办理入口"],
            "prioritize_query_fields": True,
            "requested_labels_prefix": "必答字段",
            "requested_labels_separator": "、",
        },
        {
            "metadata": "case_title",
            "label": "一件事",
            "max_chars": 200,
        },
        {
            "metadata": "related_services",
            "label": "涉及事项",
            "when_metadata": {"section_type": "composite"},
            "max_chars": 200,
        },
        {
            "metadata": "materials",
            "label": "申请材料",
            "when_metadata": {"section_type": "composite"},
            "max_chars": 200,
        },
        {
            "metadata": "urls",
            "label": "办理入口",
            "when_metadata": {"section_type": "composite"},
            "max_chars": 200,
        },
    ]
    _patch_demo_policy(monkeypatch, dify_api, response_hints=response_hints)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_CONTENT_MAX_CHARS", 500, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_TOTAL_CONTENT_MAX_CHARS", 800, raising=False)

    records = [
        {
            "content": "一件事：Alpha Package\n合并章节原文：\n办理须知\n" + ("这是一段不该直接塞给 Dify 的长流程说明。" * 80),
            "score": 0.93,
            "title": "one-thing.md",
            "metadata": {
                "section_type": "composite",
                "case_title": "Alpha Package",
                "related_services": ["事项A", "事项B"],
                "materials": ["申请表", "身份证"],
                "urls": ["https://example.test/apply"],
            },
        }
    ]

    compacted = dify_api._compact_fast_records_for_response(
        records,
        query="这个一件事涉及事项、申请材料、办理渠道是什么？",
        top_k=1,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    content = compacted[0]["content"]
    assert "必答字段：涉及事项、申请材料、办理入口" in content
    assert "一件事：Alpha Package" in content
    assert "涉及事项：事项A" in content
    assert "申请材料：申请表" in content
    assert "办理入口：https://example.test/apply" in content
    assert "不该直接塞给 Dify" not in content
    assert compacted[0]["metadata"]["dify_fast_compacted"] is True


def test_dify_fast_response_compacts_long_qa_answer_by_query_terms(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_CONTENT_MAX_CHARS", 1400, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_TOTAL_CONTENT_MAX_CHARS", 2200, raising=False)

    records = [
        {
            "content": (
                "问题：汽车置换更新\n"
                "答案：汽车置换更新可以在苏服办APP首页进入，进行2025年补贴申请。"
                "1.卖旧置换更新补贴，从此入口发起补贴申请。"
                "2.报废置换更新补贴，从此入口发起补贴申请。"
                "一、活动时间 2025年1月1日至2025年12月31日。"
                "二、补贴范围 个人消费者转让或报废本人名下乘用车，并在江苏省内购置新车。"
                + "三、补贴标准 各档补贴金额和资料审核规则。" * 80
            ),
            "score": 0.83,
            "title": "car.md",
            "metadata": {"chunk_python_plugin": _DEMO_PLUGIN_REF, "gov_knowledge_type": "qa"},
        }
    ]

    compacted = dify_api._compact_fast_records_for_response(
        records,
        query="汽车置换补贴怎么申请：苏服办APP、2025年补贴申请、卖旧置换更新补贴、报废置换更新补贴？",
        top_k=1,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    content = compacted[0]["content"]
    assert len(content) < 500
    assert "苏服办APP" in content
    assert "2025年补贴申请" in content
    assert "卖旧置换更新补贴" in content
    assert "报废置换更新补贴" in content
    assert "各档补贴金额和资料审核规则" not in content


def test_dify_fast_latency_profile_can_short_circuit_with_metadata_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    hybrid_calls: list[dict[str, object]] = []
    preflight_calls: list[dict[str, object]] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON", f'{{"city": "{dataset_id}"}}', raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED", True, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_FAST_METADATA_PREFLIGHT_STATEMENT_TIMEOUT_MS",
        321,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_FAST_METADATA_PREFLIGHT_MAX_ELAPSED_MS",
        654,
        raising=False,
    )

    def _fake_metadata_anchor_db_fallback_records(**kwargs):  # noqa: ANN003, ANN202
        preflight_calls.append(dict(kwargs))
        return [
            {
                "content": "事项名称：Alpha Desk escalation path\n办理地点：A1",
                "score": 0.96,
                "title": "policy.md",
                "metadata": {
                    "dataset_id": str(dataset_id),
                    "chunk_id": str(chunk_id),
                    "service_name": "Alpha Desk escalation path",
                },
            }
        ]

    async def _unexpected_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        hybrid_calls.append(dict(kwargs))
        raise AssertionError("metadata preflight hit should skip hybrid retrieval")

    monkeypatch.setattr(dify_api, "_metadata_anchor_db_fallback_records", _fake_metadata_anchor_db_fallback_records, raising=True)
    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _unexpected_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_query_allows_metadata_anchor_preflight", lambda *_args, **_kwargs: True, raising=True)
    monkeypatch.setattr(dify_api, "_query_has_specific_service_anchor_candidate", lambda *_args, **_kwargs: True, raising=True)
    monkeypatch.setattr(dify_api, "_records_have_strong_question_anchor", lambda *_args, **_kwargs: True, raising=True)
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
            "retrieval_setting": {
                "top_k": 2,
                "score_threshold": 0.0,
                "latency_profile": "fast",
            },
        },
    )

    assert res.status_code == 200, res.text
    assert hybrid_calls == []
    assert len(preflight_calls) == 1
    assert preflight_calls[0]["statement_timeout_ms_override"] == 321
    assert preflight_calls[0]["max_elapsed_ms"] == 654
    assert res.json()["records"][0]["title"] == "policy.md"


def test_dify_fast_latency_profile_allows_quoted_question_metadata_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    preflight_calls: list[dict[str, object]] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON", f'{{"city": "{dataset_id}"}}', raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED", True, raising=False)

    def _fake_metadata_anchor_db_fallback_records(**kwargs):  # noqa: ANN003, ANN202
        preflight_calls.append(dict(kwargs))
        return [
            {
                "content": "问题：请问我可以在哪里补办社会保障卡\n答案：雕庄街道为民服务中心。",
                "score": 0.97,
                "title": "qa.txt",
                "metadata": {
                    "dataset_id": str(dataset_id),
                    "question": "请问我可以在哪里补办社会保障卡",
                    "chunk_kind": "qa_pair",
                },
            }
        ]

    async def _unexpected_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        raise AssertionError("quoted question anchor should use metadata preflight before hybrid retrieval")

    monkeypatch.setattr(dify_api, "_metadata_anchor_db_fallback_records", _fake_metadata_anchor_db_fallback_records, raising=True)
    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _unexpected_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_query_allows_metadata_anchor_preflight", lambda *_args, **_kwargs: True, raising=True)
    monkeypatch.setattr(dify_api, "_query_has_specific_service_anchor_candidate", lambda *_args, **_kwargs: False, raising=True)
    monkeypatch.setattr(dify_api, "_records_have_confident_metadata_anchor", lambda *_args, **_kwargs: True, raising=True)
    monkeypatch.setattr(dify_api, "_records_have_strong_question_anchor", lambda *_args, **_kwargs: True, raising=True)
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
            "query": "我想办理“请问我可以在哪里补办社会保障卡”，不想跑错窗口。",
            "retrieval_setting": {
                "top_k": 2,
                "score_threshold": 0.0,
                "latency_profile": "fast",
            },
        },
    )

    assert res.status_code == 200, res.text
    assert len(preflight_calls) == 1
    assert res.json()["records"][0]["title"] == "qa.txt"


def test_dify_fast_latency_profile_skips_broad_metadata_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    hybrid_calls: list[dict[str, object]] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON", f'{{"city": "{dataset_id}"}}', raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED", True, raising=False)

    def _unexpected_metadata_anchor_db_fallback_records(**_kwargs):  # noqa: ANN003, ANN202
        raise AssertionError("fast broad queries should not run metadata preflight")

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        hybrid_calls.append(dict(kwargs))
        return [
            {
                "chunk_content": "线上业务渠道答案",
                "relevance_score": 0.93,
                "document_name": "qa.xlsx",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
            }
        ]

    monkeypatch.setattr(dify_api, "_metadata_anchor_db_fallback_records", _unexpected_metadata_anchor_db_fallback_records, raising=True)
    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_query_allows_metadata_anchor_preflight", lambda *_args, **_kwargs: True, raising=True)
    monkeypatch.setattr(dify_api, "_query_has_specific_service_anchor_candidate", lambda *_args, **_kwargs: False, raising=True)
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
            "query": "公积金线上业务渠道有哪些这个事项",
            "retrieval_setting": {
                "top_k": 2,
                "score_threshold": 0.0,
                "latency_profile": "fast",
            },
        },
    )

    assert res.status_code == 200, res.text
    assert len(hybrid_calls) == 1
    assert res.json()["records"][0]["content"] == "线上业务渠道答案"


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


def test_dify_query_routes_prioritize_matching_hints_without_including_unmatched_hints_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    assert dify_api._resolve_knowledge_dataset_ids("city", query="普通查询") == [base_dataset]
    assert dify_api._resolve_knowledge_dataset_ids("city", query="不动产登记交易中心地址") == [
        department_qa_dataset,
        base_dataset,
    ]


def test_dify_unmatched_route_hints_can_be_enabled_for_aggregate_knowledge(
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
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_INCLUDE_UNMATCHED_ROUTE_HINTS",
        True,
        raising=False,
    )

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


def test_dify_matched_replace_route_prioritizes_route_dataset_without_narrowing_primary_scope(
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
        assert dataset_ids == [topic_dataset, base_dataset]
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
    assert calls == [[topic_dataset, base_dataset]]
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


def test_dify_sort_prefers_exact_primary_alias_over_partial_question_match() -> None:
    import app.api.v1.integrations_dify as dify_api

    partial_question = {
        "content": "问题：如何预约办事？\n答案：可在首页网上预约。",
        "score": 0.9,
        "title": "short-faq.txt",
        "metadata": {
            "question": "如何预约办事？",
            "aliases": ["怎么预约？我想预约"],
            "primary_alias": "怎么预约？我想预约",
            "chunk_kind": "qa_pair",
        },
    }
    exact_alias = {
        "content": "问题：网上预约办事\n答案：可通过网上预约入口办理。",
        "score": 0.9,
        "title": "rich-faq.txt",
        "metadata": {
            "question": "网上预约办事",
            "aliases": ["如何预约办事？预约办事", "怎么预约"],
            "primary_alias": "如何预约办事？预约办事",
            "urls": [
                "https://example.test/app",
                "https://example.test/pc",
            ],
            "chunk_kind": "qa_pair",
        },
    }
    records = [partial_question, exact_alias]

    dify_api._sort_records_for_query(records, query="如何预约办事？预约办事")

    assert records[0] == exact_alias


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


def test_dify_retrieval_preserves_short_citation_snippet_over_full_chunk_hydration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"region-alpha": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    snippet = "区县：区域甲..."

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": snippet,
                "relevance_score": 0.73,
                "document_name": "区域甲事项列表.txt",
                "document_id": str(document_id),
                "chunk_id": str(chunk_id),
                "dataset_id": str(dataset_id),
                "metadata": {"chunk_python_plugin": _DEMO_PLUGIN_REF},
            }
        ]

    def _fake_load_chunk_content_map(**_kwargs):  # noqa: ANN003, ANN202
        raise AssertionError("snippet-bearing Dify citations should not trigger chunk hydration")

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
    assert content == snippet


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


def test_dify_sort_uses_aliases_for_question_anchor_bonus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        question_anchor_bonus=0.9,
    )
    calculation_answer = {
        "content": "问题：汽车置换更新补贴怎么算？\n答案：新能源车补贴8%。",
        "score": 0.67,
        "title": "policy.txt",
        "metadata": {
            "question": "汽车置换更新补贴怎么算？",
            "chunk_kind": "qa_pair",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }
    application_answer = {
        "content": "问题：汽车置换更新\n答案：可在苏服办APP申请汽车置换补贴。",
        "score": 0.73,
        "title": "high-frequency.xlsx",
        "metadata": {
            "question": "汽车置换更新",
            "aliases": ["办理汽车置换补贴", "常州办理车辆置换补贴申请查询"],
            "chunk_kind": "qa_pair",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }
    records = [calculation_answer, application_answer]

    dify_api._sort_records_for_query(
        records,
        query="汽车置换补贴怎么申请",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert records[0] is application_answer


def test_dify_sort_does_not_promote_url_evidence_for_non_entry_question() -> None:
    import app.api.v1.integrations_dify as dify_api

    unrelated_url_record = {
        "content": "问题：信用修复入口在哪里？\n答案：访问江苏政务服务网。",
        "score": 0.74,
        "title": "one-thing.txt",
        "metadata": {
            "question": "信用修复入口在哪里？",
            "urls": ["https://example.test/credit"],
            "chunk_kind": "qa_pair",
        },
    }
    exact_content_record = {
        "content": "问题：企业员工密码输入错误5次，无法再输入密码。\n答案：企业可通过重置密码，刷新输入限制次数。",
        "score": 0.75,
        "title": "emergency-faq.docx",
        "metadata": {
            "question": "企业在应急系统注册时，系统提示该企业统一社会信用代码已被注册。",
            "chunk_kind": "qa_pair",
        },
    }
    records = [unrelated_url_record, exact_content_record]

    dify_api._sort_records_for_query(records, query="企业员工密码输入错误5次怎么办")

    assert records[0] is exact_content_record


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


def test_dify_compaction_does_not_drop_top_exact_answer_for_nearby_strong_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(
        monkeypatch,
        dify_api,
        question_intent_terms=["材料"],
        response_compaction={
            "enabled": True,
            "min_top_score": 0.8,
            "relative_score_floor": 0.65,
            "min_records": 1,
        },
    )
    correct = {
        "content": "问题：核发居民身份证（补领）\n答案：居民户口簿、有效身份证件之一。",
        "score": 0.7,
        "title": "id-card.txt",
        "metadata": {
            "question": "核发居民身份证（补领）",
            "chunk_kind": "qa_pair",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }
    first_apply = {
        "content": "问题：居民身份证需要什么材料\n答案：居民户口簿。",
        "score": 0.725,
        "title": "id-card.txt",
        "metadata": {
            "question": "居民身份证需要什么材料",
            "chunk_kind": "qa_pair",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }
    renewal = {
        "content": "问题：居民身份证材料\n答案：居民身份证。",
        "score": 0.724,
        "title": "id-card.txt",
        "metadata": {
            "question": "居民身份证材料",
            "chunk_kind": "qa_pair",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }

    records = [correct, first_apply, renewal]

    compacted = dify_api._compact_records_for_response(
        records,
        query="居民身份证补领需要什么材料",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert compacted[0] is correct


def test_dify_retrieval_uses_map_plugin_refs_for_content_hints_when_citation_lacks_plugin_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

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
    snippet = "区县：区域甲..."

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": snippet,
                "relevance_score": 0.73,
                "document_name": "区域甲事项列表.txt",
                "chunk_id": str(chunk_id),
                "dataset_id": str(dataset_id),
                "metadata": {"service_name": "服务卡补卡"},
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(
        dify_api,
        "_load_chunk_content_map",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("snippet-bearing Dify citations should not trigger chunk hydration")
        ),
        raising=True,
    )

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
    assert content == snippet


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


def test_dify_response_hints_can_promote_plugin_declared_metadata_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    policy = {
        "schema": "mimirq.retrieval_policy.v1",
        "response_hints": {
            "answer_prefix": "答案要点",
            "source_prefix": "原始证据",
            "answer_highlight_metadata_fields": [
                {"metadata": "service_name", "label": "事项名称"},
                {"metadata": "service_fields", "fields": ["办理地点", "咨询方式"]},
                {"metadata": "answer", "label": "答案", "max_chars": 800},
            ],
        },
    }
    metadata = {
        "chunk_python_plugin": plugin_ref,
        "service_name": "服务卡补卡",
        "service_fields": {
            "办理地点": "区域甲政务服务中心",
            "咨询方式": "0519-12333",
        },
        "answer": "请携带身份证件到窗口办理。",
    }

    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: policy if ref == plugin_ref else {},
        raising=True,
    )

    hinted = dify_api._content_with_answer_hints(
        "咨询方式：0519-12333",
        metadata,
        query="服务卡补卡在哪里办理",
        policy_plugin_refs=(plugin_ref,),
    )

    assert hinted.startswith("答案要点：")
    assert "事项名称：服务卡补卡" in hinted
    assert "办理地点：区域甲政务服务中心" in hinted
    assert "咨询方式：0519-12333" in hinted
    assert "答案：请携带身份证件到窗口办理。" in hinted
    assert hinted.endswith("咨询方式：0519-12333")


def test_dify_records_hydrate_truncated_exact_anchor_slot_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    chunk_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    full_content = (
        "Case: Alpha Package\n"
        "Section: service channels\n"
        "Apply online.\n"
        "Contact: 555-0100"
    )
    _patch_demo_policy(
        monkeypatch,
        dify_api,
        anchor_binding={
            "enabled": True,
            "anchor_fields": ["case_title"],
            "slot_fields": ["section_type"],
        },
        query_expansion_values=[
            {"metadata": "section_type", "value": "channels", "terms": ["channels", "contact"]},
            {"metadata": "section_type", "value": "materials", "terms": ["materials"]},
        ],
    )
    hydration_calls: list[list[dict[str, object]]] = []

    def _fake_load_chunk_content_map(**kwargs):  # noqa: ANN003, ANN202
        hydration_calls.append(kwargs["citations"])
        return {str(chunk_id): full_content}

    monkeypatch.setattr(dify_api, "_load_chunk_content_map", _fake_load_chunk_content_map, raising=True)
    citations = [
        {
            "chunk_content": "Case: Alpha Package...",
            "relevance_score": 0.91,
            "document_name": "alpha.md",
            "chunk_id": str(chunk_id),
            "dataset_id": str(dataset_id),
            "metadata": {
                "case_title": "Alpha Package",
                "section_type": "channels",
                "chunk_python_plugin": _DEMO_PLUGIN_REF,
            },
        }
    ]

    records = dify_api._records_from_citations(
        db=object(),
        tenant_id=uuid.uuid4(),
        citations=citations,
        fallback_dataset_id=dataset_id,
        query="Alpha Package materials, channels, and contact",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert hydration_calls == [citations]
    assert full_content in records[0]["content"]


def test_dify_subquery_records_hydrate_slots_requested_by_original_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    chunk_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    full_content = "Case: Alpha Package\nChannels\nContact: 555-0100"
    _patch_demo_policy(
        monkeypatch,
        dify_api,
        anchor_binding={
            "enabled": True,
            "anchor_fields": ["case_title"],
            "slot_fields": ["section_type"],
        },
        query_expansion_values=[
            {"metadata": "section_type", "value": "related_services", "terms": ["related services"]},
            {"metadata": "section_type", "value": "channels", "terms": ["channels", "contact"]},
        ],
    )
    hydration_calls: list[list[dict[str, object]]] = []

    def _fake_load_chunk_content_map(**kwargs):  # noqa: ANN003, ANN202
        hydration_calls.append(kwargs["citations"])
        return {str(chunk_id): full_content}

    monkeypatch.setattr(dify_api, "_load_chunk_content_map", _fake_load_chunk_content_map, raising=True)
    citations = [
        {
            "chunk_content": "Case: Alpha Package...",
            "relevance_score": 0.91,
            "document_name": "alpha.md",
            "chunk_id": str(chunk_id),
            "dataset_id": str(dataset_id),
            "metadata": {
                "case_title": "Alpha Package",
                "section_type": "channels",
                "chunk_python_plugin": _DEMO_PLUGIN_REF,
            },
        }
    ]

    records = dify_api._records_from_citations(
        db=object(),
        tenant_id=uuid.uuid4(),
        citations=citations,
        fallback_dataset_id=dataset_id,
        query="Alpha Package related services",
        hydration_query="Alpha Package related services, channels, and contact",
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
    )

    assert hydration_calls == [citations]
    assert full_content in records[0]["content"]


def test_dify_response_hints_can_prioritize_plugin_declared_query_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    policy = {
        "schema": "mimirq.retrieval_policy.v1",
        "fast_response_field_rules": [
            {"label": "办理材料", "markers": ["材料"]},
            {"label": "办理流程", "markers": ["流程", "怎么办理"]},
            {"label": "咨询方式", "markers": ["咨询", "电话"]},
        ],
        "response_hints": {
            "answer_prefix": "答案要点",
            "source_prefix": "原始证据",
            "answer_highlight_metadata_fields": [
                {"metadata": "service_name", "label": "事项名称"},
                {
                    "metadata": "service_fields",
                    "fields": ["办理材料", "办理流程", "咨询方式"],
                    "prioritize_query_fields": True,
                    "requested_labels_prefix": "必答字段",
                    "requested_labels_separator": "、",
                },
            ],
        },
    }
    metadata = {
        "chunk_python_plugin": plugin_ref,
        "service_name": "服务卡补卡",
        "service_fields": {
            "办理材料": "居民身份证件；居民户口簿；外国人永久居留证；港澳台居民居住证",
            "办理流程": "提交申请；窗口受理；制卡发放",
            "咨询方式": "0519-12333",
        },
    }

    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: policy if ref == plugin_ref else {},
        raising=True,
    )

    hinted = dify_api._content_with_answer_hints(
        "事项名称：服务卡补卡",
        metadata,
        query="服务卡补卡怎么办理，咨询电话是多少",
        policy_plugin_refs=(plugin_ref,),
    )

    assert hinted.startswith("答案要点：")
    assert "必答字段：办理流程、咨询方式" in hinted
    assert hinted.index("必答字段：办理流程、咨询方式") < hinted.index("办理流程：提交申请")
    assert hinted.index("办理流程：提交申请") < hinted.index("办理材料：居民身份证件")
    assert hinted.index("咨询方式：0519-12333") < hinted.index("办理材料：居民身份证件")


def test_dify_response_hints_can_promote_plugin_declared_array_metadata_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    plugin_ref = "plugin:demo-one-thing@1.0.0:chunk"
    policy = {
        "schema": "mimirq.retrieval_policy.v1",
        "response_hints": {
            "answer_prefix": "答案要点",
            "source_prefix": "原始证据",
            "answer_highlight_metadata_fields": [
                {"metadata": "case_title", "label": "一件事"},
                {"metadata": "related_services", "label": "涉及事项"},
                {"metadata": "materials", "label": "申请材料"},
                {"metadata": "operation_steps", "label": "操作步骤"},
                {"metadata": "urls", "label": "办理入口"},
            ],
        },
    }
    metadata = {
        "chunk_python_plugin": plugin_ref,
        "case_title": "教育入学“一件事”",
        "related_services": ["新生入学信息采集", "户籍类证明"],
        "materials": ["户口簿", "合法固定住所证件"],
        "operation_steps": ["进入教育入学模块", "提交报名信息"],
        "urls": ["https://cz.jszwfw.gov.cn/"],
    }

    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: policy if ref == plugin_ref else {},
        raising=True,
    )

    hinted = dify_api._content_with_answer_hints(
        "一件事：教育入学“一件事”\n章节：涉及事项\n新生入学信息采集、户籍类证明",
        metadata,
        query="教育入学“一件事”涉及哪些事项",
        policy_plugin_refs=(plugin_ref,),
    )

    assert hinted.startswith("答案要点：")
    assert "一件事：教育入学“一件事”" in hinted
    assert "涉及事项：新生入学信息采集" in hinted
    assert "涉及事项：户籍类证明" in hinted
    assert "申请材料：户口簿" in hinted
    assert "操作步骤：进入教育入学模块" in hinted
    assert "办理入口：https://cz.jszwfw.gov.cn/" in hinted


def test_dify_response_hints_can_gate_declared_metadata_fields_by_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    plugin_ref = "plugin:demo-one-thing@1.0.0:chunk"
    policy = {
        "schema": "mimirq.retrieval_policy.v1",
        "response_hints": {
            "answer_prefix": "答案要点",
            "source_prefix": "原始证据",
            "answer_highlight_metadata_fields": [
                {"metadata": "case_title", "label": "一件事"},
                {
                    "metadata": "related_services",
                    "label": "涉及事项",
                    "when_metadata": {"section_type": "related_services"},
                },
                {
                    "metadata": "materials",
                    "label": "申请材料",
                    "when_metadata": {"section_type": "materials"},
                },
            ],
        },
    }
    metadata = {
        "chunk_python_plugin": plugin_ref,
        "section_type": "related_services",
        "case_title": "教育入学“一件事”",
        "related_services": ["新生入学信息采集", "户籍类证明"],
        "materials": ["户口簿", "合法固定住所证件"],
    }

    monkeypatch.setattr(
        dify_api,
        "_retrieval_policy_for_plugin_ref",
        lambda ref: policy if ref == plugin_ref else {},
        raising=True,
    )

    hinted = dify_api._content_with_answer_hints(
        "一件事：教育入学“一件事”\n章节：涉及事项\n新生入学信息采集、户籍类证明",
        metadata,
        query="教育入学“一件事”涉及哪些事项",
        policy_plugin_refs=(plugin_ref,),
    )

    assert "一件事：教育入学“一件事”" in hinted
    assert "涉及事项：新生入学信息采集" in hinted
    assert "涉及事项：户籍类证明" in hinted
    assert "申请材料：户口簿" not in hinted
    assert "申请材料：合法固定住所证件" not in hinted


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


def test_dify_retrieval_uses_server_tenant_when_header_attempts_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    configured_tenant_id = uuid.uuid4()
    header_tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    seen_tenant_ids: list[uuid.UUID] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID", str(configured_tenant_id), raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        seen_tenant_ids.append(kwargs["tenant_id"])
        return [
            {
                "chunk_content": "身份证补领可线上申请。",
                "relevance_score": 0.8,
                "document_name": "city.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
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
        headers={**_auth(token), "X-Tenant-ID": str(header_tenant_id)},
        json={
            "knowledge_id": "city",
            "query": "身份证补领怎么办",
            "retrieval_setting": {"top_k": 1, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert seen_tenant_ids == [configured_tenant_id]


def test_dify_retrieval_actor_requires_tenant_id_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    tenant_id = uuid.uuid4()

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", "dify-test-token", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID", "", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api, "is_production_env", lambda: True, raising=False)
    request = SimpleNamespace(headers={})

    with pytest.raises(HTTPException, match="Dify external knowledge tenant is not configured"):
        dify_api._require_dify_actor(request, authorization="Bearer dify-test-token")

    monkeypatch.setattr(dify_api, "is_production_env", lambda: False, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID", "", raising=False)

    actor = dify_api._require_dify_actor(
        request=SimpleNamespace(headers={"X-Tenant-ID": str(tenant_id)}),
        authorization="Bearer dify-test-token",
    )
    assert actor.tenant_id == tenant_id


def test_dify_trace_conversation_id_rejects_access_to_other_account_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    request = SimpleNamespace(headers={"x-mimirq-conversation-id": str(conversation_id)})
    body = dify_api.DifyExternalKnowledgeRequest(knowledge_id="external-kb", query="query")

    monkeypatch.setattr(
        dify_api,
        "_load_dify_trace_conversation",
        lambda *_args, **_kwargs: SimpleNamespace(id=conversation_id, owner_account_id="other-account"),
        raising=True,
    )

    with pytest.raises(HTTPException, match="Conversation is not accessible") as exc_info:
        dify_api._dify_trace_conversation_id(
            request=request,
            body=body,
            db=object(),
            tenant_id=tenant_id,
            account_id="system:dify",
        )

    assert exc_info.value.status_code == 403


def test_dify_trace_conversation_id_accepts_conversation_id_for_same_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    request = SimpleNamespace(headers={"x-mimirq-conversation-id": str(conversation_id)})
    body = dify_api.DifyExternalKnowledgeRequest(knowledge_id="external-kb", query="query")

    monkeypatch.setattr(
        dify_api,
        "_load_dify_trace_conversation",
        lambda *_args, **_kwargs: SimpleNamespace(id=conversation_id, owner_account_id="system:dify"),
        raising=True,
    )

    resolved = dify_api._dify_trace_conversation_id(
        request=request,
        body=body,
        db=object(),
        tenant_id=tenant_id,
        account_id="system:dify",
    )
    assert resolved == conversation_id


def test_dify_metadata_anchor_db_fallback_enforces_normal_document_eligibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    _patch_demo_policy(monkeypatch, dify_api)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    captured_filters: list[object] = []
    service_row = {
        "chunk_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "dataset_id": dataset_id,
        "chunk_index": 0,
        "page_number": 1,
        "filename": "service.txt",
        "content": "事项名称：保健食品广告审查\n办理地点：市级大厅",
        "metadata": {
            "service_name": "保健食品广告审查",
            "source_record_id": "service-eligible",
            "chunk_python_plugin": _DEMO_PLUGIN_REF,
        },
    }

    class _FakeQuery:
        def join(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def filter(self, *conditions):  # noqa: ANN002, ANN202
            captured_filters[:] = list(conditions)
            return self

        def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def limit(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def all(self):  # noqa: ANN202
            return [service_row]

    class _FakeDB:
        def execute(self, _statement):  # noqa: ANN001, ANN202
            return None

        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return _FakeQuery()

        def rollback(self) -> None:
            return None

    fallback_records = dify_api._metadata_anchor_db_fallback_records(
        db=_FakeDB(),
        tenant_id=tenant_id,
        dataset_ids=[dataset_id],
        query="保健食品广告审查",
        top_k=5,
        policy_plugin_refs=(_DEMO_PLUGIN_REF,),
        existing_records=[],
    )

    assert len(fallback_records) == 1
    rendered_filters = " AND ".join(str(condition) for condition in captured_filters).lower()
    captured_values: list[str] = []

    def _walk_values(node):  # noqa: ANN001, ANN202
        value = getattr(node, "value", None)
        if value is not None:
            captured_values.append(str(value))
        for attr in ("left", "right"):
            child = getattr(node, attr, None)
            if child is not None:
                _walk_values(child)
        clauses = getattr(node, "clauses", None)
        if clauses is not None:
            for child in clauses:
                _walk_values(child)

    for condition in captured_filters:
        _walk_values(condition)

    assert "documents.status" in rendered_filters
    assert "completed" in captured_values
    assert "documents.publication_status" in rendered_filters
    assert "published" in captured_values
    assert "documents.archived_at is null" in rendered_filters
    assert "documents.disabled_at is null" in rendered_filters
    assert "document_chunks.disabled_at is null" in rendered_filters


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


def test_dify_record_conversion_uses_mimirq_score_from_metadata() -> None:
    from app.api.v1.integrations_dify import _citation_to_dify_record

    record = _citation_to_dify_record(
        {
            "content": "service item evidence",
            "document_name": "service.txt",
            "metadata": {
                "mimirq_score": 0.89,
                "service_name": "Alpha Permit",
            },
        },
        dataset_id=None,
    )

    assert record["score"] == pytest.approx(0.89)
    assert record["metadata"]["mimirq_score"] == 0.89


def test_dify_record_conversion_does_not_use_generic_metadata_score() -> None:
    from app.api.v1.integrations_dify import _citation_to_dify_record

    record = _citation_to_dify_record(
        {
            "content": "business metadata evidence",
            "document_name": "business.txt",
            "metadata": {
                "score": 99,
                "service_name": "Alpha Permit",
            },
        },
        dataset_id=None,
    )

    assert record["score"] == 0.0
    assert record["metadata"]["score"] == 99


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


def test_dify_records_from_citations_preserve_snippet_without_chunk_hydration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    snippet = "答案要点：身份证补领材料为居民户口簿。"
    citation = {
        "chunk_content": snippet,
        "relevance_score": 0.88,
        "document_name": "身份证补领材料.txt",
        "chunk_id": str(uuid.uuid4()),
        "dataset_id": str(uuid.uuid4()),
    }

    def _unexpected_load_chunk_content_map(**_kwargs):  # noqa: ANN003, ANN202
        raise AssertionError("bounded Dify snippets should not be replaced by hydrated chunk bodies")

    monkeypatch.setattr(dify_api, "_load_chunk_content_map", _unexpected_load_chunk_content_map, raising=True)

    records = dify_api._records_from_citations(
        db=object(),
        tenant_id=uuid.uuid4(),
        citations=[citation],
        fallback_dataset_id=None,
        query="身份证补领需要什么材料",
    )

    assert len(records) == 1
    assert records[0]["content"] == snippet
    assert records[0]["title"] == "身份证补领材料.txt"


def test_dify_external_retrieval_logs_history_rag_trace_when_conversation_context_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import integrations_dify as dify_api

    logged: list[dict[str, object]] = []
    monkeypatch.setattr(dify_api, "log_metrics", lambda payload: logged.append(payload))

    conversation_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    request_id = "dify-http-trace-1"

    dify_api._log_dify_external_rag_trace(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        request_id=request_id,
        question="保健食品广告审查归哪个层级办理？",
        response_records=[
            dify_api.DifyExternalKnowledgeRecord(
                content="不应进入 trace 原文",
                score=0.93,
                title="service-item.txt",
                metadata={
                    "document_id": "doc-1",
                    "chunk_id": "chunk-1",
                    "chunk_index": 7,
                    "page_number": 2,
                    "hit_type": "hybrid",
                    "reranker_provider": "bge",
                    "rerank_score": 0.91,
                    "rerank_elapsed_sec": 0.12,
                    "rerank_model_used": "bge-reranker-large",
                },
            )
        ],
        top_k=5,
        candidate_top_k=12,
        retrieval_path="rag:primary_scope",
        elapsed_ms=321.4,
        metadata_anchor_fallback_count=1,
        mixed_intent_query_count=2,
    )

    assert len(logged) == 1
    payload = logged[0]
    assert payload["event"] == "rag_trace"
    assert payload["source"] == "dify_external_knowledge"
    assert payload["conversation_id"] == str(conversation_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["request_id"] == request_id
    assert payload["question"] == "保健食品广告审查归哪个层级办理？"
    assert payload["citations_count"] == 1
    assert payload["retrieval"] == {
        "mode": "dify_external_knowledge",
        "requested_mode": "external_knowledge",
        "top_k": 5,
        "query_count": 3,
        "per_query": [
            {
                "kind": "main",
                "query_chars": len("保健食品广告审查归哪个层级办理？"),
                "query_preview": "保健食品广告审查归哪个层级办理？",
                "path": "rag:primary_scope",
                "ok": True,
            }
        ],
        "elapsed_sec": pytest.approx(0.3214),
        "errors": [],
        "enable_reranker": True,
        "reranker_provider": "bge",
        "reranker_top_n": 12,
    }
    assert payload["citations"][0]["document_id"] == "doc-1"
    assert payload["citations"][0]["chunk_id"] == "chunk-1"
    assert payload["citations"][0]["rerank_score"] == pytest.approx(0.91)
    assert "content" not in payload["citations"][0]

    from app.services.rag_trace_service import normalize_rag_trace_record

    history_trace = normalize_rag_trace_record(payload)
    assert history_trace.conversation_id == str(conversation_id)
    assert history_trace.request_id == request_id
    assert history_trace.retrieval.mode == "dify_external_knowledge"
    assert history_trace.retrieval.query_count == 3
    assert history_trace.rerank.enabled is True
    assert history_trace.citations[0].document_id == "doc-1"


def test_dify_trace_context_accepts_body_and_header_extensions() -> None:
    from app.api.v1 import integrations_dify as dify_api

    body_conversation_id = uuid.uuid4()
    body = dify_api.DifyExternalKnowledgeRequest(
        knowledge_id="external-kb",
        query="保健食品广告审查",
        conversation_id=body_conversation_id,
        request_id="body-request-id",
    )
    request = SimpleNamespace(
        headers={
            "x-mimirq-conversation-id": str(uuid.uuid4()),
            "x-mimirq-request-id": "header-request-id",
        },
        state=SimpleNamespace(request_id="state-request-id"),
    )

    assert dify_api._dify_trace_conversation_id(request, body) == body_conversation_id
    assert dify_api._dify_trace_request_id(request, body) == "body-request-id"

    header_conversation_id = uuid.uuid4()
    body_without_trace = dify_api.DifyExternalKnowledgeRequest(
        knowledge_id="external-kb",
        query="保健食品广告审查",
    )
    header_request = SimpleNamespace(
        headers={
            "x-mimirq-conversation-id": str(header_conversation_id),
            "x-mimirq-request-id": "header-request-id",
        },
        state=SimpleNamespace(request_id="state-request-id"),
    )

    assert dify_api._dify_trace_conversation_id(header_request, body_without_trace) == header_conversation_id
    assert dify_api._dify_trace_request_id(header_request, body_without_trace) == "header-request-id"


def test_dify_trace_context_auto_creates_mimirq_conversation_for_dify_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import integrations_dify as dify_api

    created_conversation_id = uuid.uuid4()
    calls: list[dict[str, object]] = []

    class _DB:
        pass

    db = _DB()
    tenant_id = uuid.uuid4()
    request = SimpleNamespace(headers={}, state=SimpleNamespace(request_id="req-1"))
    body = dify_api.DifyExternalKnowledgeRequest(
        knowledge_id="external-kb",
        query="保健食品广告审查归哪个层级办理？",
        dify_conversation_id="dify-conv-001",
        dify_message_id="dify-msg-001",
        dify_workflow_run_id="dify-run-001",
    )

    def fake_ensure(**kwargs):  # noqa: ANN003, ANN202
        calls.append(dict(kwargs))
        return created_conversation_id

    monkeypatch.setattr(dify_api, "_ensure_dify_trace_conversation", fake_ensure, raising=True)

    resolved = dify_api._dify_trace_conversation_id(
        request,
        body,
        db=db,
        tenant_id=tenant_id,
        account_id="system:dify",
    )

    assert resolved == created_conversation_id
    assert calls == [
        {
            "db": db,
            "tenant_id": tenant_id,
            "account_id": "system:dify",
            "source_conversation_id": "dify-conv-001",
            "source_message_id": "dify-msg-001",
            "source_run_id": "dify-run-001",
            "question": "保健食品广告审查归哪个层级办理？",
        }
    ]


def test_dify_trace_conversation_resolution_locks_source_scope_before_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import integrations_dify as dify_api

    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    db = object()
    events: list[tuple[str, object]] = []

    monkeypatch.setattr(
        dify_api,
        "_lock_dify_conversation_turn_scope",
        lambda **kwargs: events.append(("lock", kwargs["conversation_scope"])),
        raising=True,
    )

    def _find_existing(_db, **kwargs):  # noqa: ANN001, ANN003, ANN202
        events.append(("find", kwargs["source_conversation_id"]))
        return conversation_id

    monkeypatch.setattr(dify_api, "_find_dify_trace_conversation", _find_existing, raising=True)
    monkeypatch.setattr(
        dify_api,
        "_load_dify_trace_conversation",
        lambda *_args, **_kwargs: SimpleNamespace(id=conversation_id, owner_account_id="system:dify"),
        raising=True,
    )

    resolved = dify_api._ensure_dify_trace_conversation(
        db=db,
        tenant_id=tenant_id,
        account_id="system:dify",
        source_conversation_id="dify-conv-001",
        source_message_id="dify-msg-001",
        source_run_id="dify-run-001",
        question="普通话考试要带什么？",
    )

    assert resolved == conversation_id
    assert events == [("lock", "dify-conv-001"), ("find", "dify-conv-001")]


def test_dify_trace_conversation_refuses_cross_account_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import integrations_dify as dify_api

    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    add_called = False

    class _NoWriteDB:
        def add(self, _value) -> None:  # noqa: ANN001
            nonlocal add_called
            add_called = True

    monkeypatch.setattr(
        dify_api,
        "_lock_dify_conversation_turn_scope",
        lambda **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(
        dify_api,
        "_find_dify_trace_conversation",
        lambda *_args, **_kwargs: conversation_id,
        raising=True,
    )
    monkeypatch.setattr(
        dify_api,
        "_load_dify_trace_conversation",
        lambda *_args, **_kwargs: SimpleNamespace(id=conversation_id, owner_account_id="acct-other"),
        raising=True,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_TRACE_AUTO_CREATE_CONVERSATION_ENABLED",
        True,
        raising=False,
    )

    resolved = dify_api._ensure_dify_trace_conversation(
        db=_NoWriteDB(),
        tenant_id=tenant_id,
        account_id="acct-1",
        source_conversation_id="dify-conv-001",
        source_message_id="dify-msg-001",
        source_run_id="dify-run-001",
        question="普通话考试要带什么？",
    )

    assert resolved is None
    assert add_called is False


def test_dify_retrieval_endpoint_logs_trace_for_dify_conversation_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import integrations_dify as dify_api

    token = "dify-test-token"
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    created_conversation_id = uuid.uuid4()
    ensured: list[dict[str, object]] = []
    logged: list[dict[str, object]] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID", str(tenant_id), raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"city": "{dataset_id}"}}',
        raising=False,
    )

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": "保健食品广告审查办理层级：省级。办理时间：工作日。",
                "relevance_score": 0.93,
                "document_name": "service-rag.txt",
                "chunk_id": "chunk-1",
                "dataset_id": str(dataset_id),
                "metadata": {"document_id": "doc-1", "chunk_id": "chunk-1"},
            }
        ]

    def _fake_ensure(**kwargs):  # noqa: ANN003, ANN202
        ensured.append(dict(kwargs))
        return created_conversation_id

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)
    monkeypatch.setattr(dify_api, "_ensure_dify_trace_conversation", _fake_ensure, raising=True)
    monkeypatch.setattr(dify_api, "log_metrics", lambda payload: logged.append(payload), raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": "保健食品广告审查归哪个层级办理？",
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
            "dify_conversation_id": "dify-conv-001",
            "dify_message_id": "dify-msg-001",
            "dify_workflow_run_id": "dify-run-001",
            "request_id": "dify-request-001",
        },
    )

    assert res.status_code == 200, res.text
    assert ensured
    assert ensured[-1]["tenant_id"] == tenant_id
    assert ensured[-1]["account_id"] == "system:dify"
    assert ensured[-1]["source_conversation_id"] == "dify-conv-001"
    assert ensured[-1]["source_message_id"] == "dify-msg-001"
    assert ensured[-1]["source_run_id"] == "dify-run-001"
    assert logged
    rag_trace = [payload for payload in logged if payload.get("event") == "rag_trace"][-1]
    assert rag_trace["conversation_id"] == str(created_conversation_id)
    assert rag_trace["tenant_id"] == str(tenant_id)
    assert rag_trace["request_id"] == "dify-request-001"
    assert rag_trace["dify_message_id"] == "dify-msg-001"
    assert rag_trace["dify_workflow_run_id"] == "dify-run-001"
    assert rag_trace["citations_count"] == 1


def test_dify_retrieval_trace_includes_mixed_intent_subqueries_and_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import integrations_dify as dify_api

    token = "dify-test-token"
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    created_conversation_id = uuid.uuid4()
    logged: list[dict[str, object]] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID", str(tenant_id), raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_HIGH_CONFIDENCE_ENABLED",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        (
            '{"city": {'
            f'"dataset_ids": ["{dataset_id}"], '
            f'"plugin_refs": ["{_DEMO_PLUGIN_REF}"]'
            "}}"
        ),
        raising=False,
    )
    _patch_demo_policy(
        monkeypatch,
        dify_api,
        mixed_intent_leading_noise_terms=["我想", "了解"],
        mixed_intent_subject_terms=["需要什么材料", "怎么查询"],
    )

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        query = kwargs["query"]
        return [
            {
                "chunk_content": f"{query} -> 命中证据",
                "relevance_score": 0.82,
                "document_name": f"{query}.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)
    monkeypatch.setattr(dify_api, "_load_chunk_content_map", lambda **_kwargs: {}, raising=True)
    monkeypatch.setattr(dify_api, "log_metrics", lambda payload: logged.append(payload), raising=True)
    monkeypatch.setattr(
        dify_api,
        "_ensure_dify_trace_conversation",
        lambda **_kwargs: created_conversation_id,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    query = "我想同时了解身份证补领需要什么材料，另外怎么查询办理进度？"
    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "city",
            "query": query,
            "retrieval_setting": {"top_k": 3, "score_threshold": 0.0},
            "dify_conversation_id": "dify-conv-001",
            "request_id": "dify-request-002",
        },
    )

    assert res.status_code == 200, res.text
    rag_trace = [payload for payload in logged if payload.get("event") == "rag_trace"][-1]
    per_query = rag_trace["retrieval"]["per_query"]
    assert [item["kind"] for item in per_query] == ["main", "subq", "subq"]
    assert per_query[0]["query_preview"] == query
    assert per_query[0]["path"] == "rag:primary_scope"
    assert per_query[1]["query_preview"] == "身份证补领需要什么材料"
    assert per_query[1]["path"] == "rag:mixed_intent_subquery"
    assert per_query[2]["query_preview"] == "身份证补领怎么查询办理进度"
    assert per_query[2]["path"] == "rag:mixed_intent_subquery"


def test_dify_conversation_turn_endpoint_persists_final_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import integrations_dify as dify_api

    token = "dify-test-token"
    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    user_message_id = uuid.uuid4()
    assistant_message_id = uuid.uuid4()
    calls: list[dict[str, object]] = []
    offload_request_dbs: list[object] = []
    worker_db = _DummyDB()

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID", str(tenant_id), raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    def _fake_persist(**kwargs):  # noqa: ANN003, ANN202
        calls.append(dict(kwargs))
        return dify_api.DifyConversationTurnResponse(
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            reused_user_message=True,
        )

    async def _fake_offload(func, *args, request_db, **kwargs):  # noqa: ANN001, ANN202
        offload_request_dbs.append(request_db)
        return func(worker_db, *args, **kwargs)

    monkeypatch.setattr(dify_api, "_persist_dify_conversation_turn", _fake_persist, raising=True)
    monkeypatch.setattr(
        dify_api,
        "run_blocking_call_with_managed_session",
        _fake_offload,
        raising=False,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/conversation-turns",
        headers=_auth(token),
        json={
            "query": "麻烦帮我查一下普通话考试，主要想知道要带什么。（我在常州）",
            "answer": "普通话考试具体测试计划可以在常州市教育局官网中查看。",
            "trace_request_id": "trace-req-001",
            "dify_conversation_id": "dify-conv-001",
            "dify_message_id": "dify-msg-001",
            "dify_workflow_run_id": "dify-run-001",
            "citations": [{"document_id": "doc-1", "chunk_id": "chunk-1"}],
        },
    )

    assert res.status_code == 200, res.text
    assert res.json() == {
        "conversation_id": str(conversation_id),
        "user_message_id": str(user_message_id),
        "assistant_message_id": str(assistant_message_id),
        "reused_user_message": True,
    }
    assert len(offload_request_dbs) == 1
    assert offload_request_dbs[0] is not worker_db
    assert len(calls) == 1
    call = calls[0]
    assert call["db"] is worker_db
    assert call["tenant_id"] == tenant_id
    assert call["account_id"] == "system:dify"
    assert call["query"] == "麻烦帮我查一下普通话考试，主要想知道要带什么。（我在常州）"
    assert call["answer"] == "普通话考试具体测试计划可以在常州市教育局官网中查看。"
    assert call["trace_request_id"] == "trace-req-001"
    assert call["source_conversation_id"] == "dify-conv-001"
    assert call["source_message_id"] == "dify-msg-001"
    assert call["source_run_id"] == "dify-run-001"
    assert call["citations"] == [{"document_id": "doc-1", "chunk_id": "chunk-1"}]


def test_dify_conversation_turn_retry_returns_existing_messages_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import integrations_dify as dify_api

    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    user_message = SimpleNamespace(id=uuid.uuid4(), role="user")
    assistant_message = SimpleNamespace(id=uuid.uuid4(), role="assistant")
    lookup_calls: list[dict[str, object]] = []
    lock_calls: list[dict[str, object]] = []

    class _NoWriteDB:
        def add(self, _value) -> None:  # noqa: ANN001
            raise AssertionError("an idempotent retry must not write")

    monkeypatch.setattr(
        dify_api,
        "_lock_dify_conversation_turn_scope",
        lambda **kwargs: lock_calls.append(dict(kwargs)),
        raising=False,
    )
    monkeypatch.setattr(
        dify_api,
        "_load_dify_trace_conversation",
        lambda *_args, **_kwargs: SimpleNamespace(id=conversation_id, owner_account_id="system:dify"),
        raising=True,
    )

    def _fake_find_existing(_db, **kwargs):  # noqa: ANN001, ANN003, ANN202
        lookup_calls.append(dict(kwargs))
        return user_message, assistant_message

    monkeypatch.setattr(
        dify_api,
        "_find_persisted_dify_conversation_turn",
        _fake_find_existing,
        raising=False,
    )
    monkeypatch.setattr(
        dify_api,
        "_find_reusable_dify_seed_message",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(
        dify_api,
        "_log_dify_result_rag_trace",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("retry must not duplicate trace")),
        raising=True,
    )

    results = [
        dify_api._persist_dify_conversation_turn(
            db=_NoWriteDB(),
            tenant_id=tenant_id,
            account_id="system:dify",
            query="普通话考试要带什么？",
            answer="请携带有效身份证件。",
            trace_request_id="trace-req-001",
            source_conversation_id="dify-conv-001",
            source_message_id="  dify-msg-001  ",
            source_run_id="dify-run-001",
            citations=[],
            conversation_id=conversation_id,
        )
        for _ in range(2)
    ]

    assert len(lookup_calls) == 2
    assert [call["conversation_scope"] for call in lock_calls] == ["dify-conv-001", "dify-conv-001"]
    assert all(call["source_message_id"] == "dify-msg-001" for call in lookup_calls)
    assert all(result.conversation_id == conversation_id for result in results)
    assert all(result.user_message_id == user_message.id for result in results)
    assert all(result.assistant_message_id == assistant_message.id for result in results)
    assert all(result.reused_user_message is True for result in results)


def test_dify_conversation_turn_rejects_explicit_conversation_owned_by_another_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import integrations_dify as dify_api

    conversation_id = uuid.uuid4()
    monkeypatch.setattr(dify_api, "_lock_dify_conversation_turn_scope", lambda **_kwargs: None)
    monkeypatch.setattr(
        dify_api,
        "_load_dify_trace_conversation",
        lambda *_args, **_kwargs: SimpleNamespace(id=conversation_id, owner_account_id="acct-other"),
    )

    with pytest.raises(HTTPException, match="Conversation is not accessible") as exc_info:
        dify_api._persist_dify_conversation_turn(
            db=_DummyDB(),
            tenant_id=uuid.uuid4(),
            account_id="acct-1",
            query="普通话考试要带什么？",
            answer="请携带有效身份证件。",
            trace_request_id=None,
            source_conversation_id="dify-conv-001",
            source_message_id="dify-msg-001",
            source_run_id=None,
            citations=[],
            conversation_id=conversation_id,
        )

    assert exc_info.value.status_code == 403


def test_dify_turn_citations_for_storage_drops_invalid_frontend_citations() -> None:
    from app.api.v1.integrations_dify import _dify_turn_citations_for_storage

    valid_document_id = uuid.uuid4()
    valid_chunk_id = uuid.uuid4()

    stored = _dify_turn_citations_for_storage(
        [
            {"document_id": "live-doc", "chunk_id": "live-chunk"},
            {
                "document_id": str(valid_document_id),
                "chunk_id": str(valid_chunk_id),
                "chunk_content": "答案：普通话考试具体测试计划可以在常州市教育局官网中查看。",
                "document_name": "常见问题优化补充.txt",
                "retrieval_mode": "dify_external_knowledge",
            },
        ]
    )

    assert stored == [
        {
            "document_id": str(valid_document_id),
            "chunk_id": str(valid_chunk_id),
            "chunk_content": "答案：普通话考试具体测试计划可以在常州市教育局官网中查看。",
            "document_name": "常见问题优化补充.txt",
            "retrieval_mode": "dify_external_knowledge",
        }
    ]


def test_dify_result_trace_logs_final_result_step_without_raw_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import integrations_dify as dify_api
    from app.services.rag_trace_service import normalize_rag_trace_record

    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    logged: list[dict[str, object]] = []

    monkeypatch.setattr(dify_api, "log_metrics", lambda payload: logged.append(payload), raising=True)

    dify_api._log_dify_result_rag_trace(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        request_id="trace-req-001",
        question="麻烦帮我查一下普通话考试，主要想知道要带什么。（我在常州）",
        answer="普通话考试具体测试计划可以在常州市教育局官网中查看。",
        source_conversation_id="dify-conv-001",
        source_message_id="dify-msg-001",
        source_run_id="dify-run-001",
        citations=[{"document_id": "doc-1", "chunk_id": "chunk-1"}],
    )

    assert len(logged) == 1
    payload = logged[0]
    assert payload["event"] == "rag_trace"
    assert payload["source"] == "dify_result"
    assert payload["conversation_id"] == str(conversation_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["request_id"] == "trace-req-001"
    assert "普通话考试具体测试计划" not in json.dumps(payload, ensure_ascii=False)
    assert payload["dify_result"] == {
        "status": "completed",
        "answer_chars": 26,
        "answer_hash": dify_api._diagnostic_query_hash("普通话考试具体测试计划可以在常州市教育局官网中查看。"),
        "source_conversation_id": "dify-conv-001",
        "source_message_id": "dify-msg-001",
        "source_run_id": "dify-run-001",
        "citations_count": 1,
    }

    history_trace = normalize_rag_trace_record(payload)
    assert history_trace.conversation_id == str(conversation_id)
    assert history_trace.request_id == "trace-req-001"
    assert history_trace.steps[-1].key == "dify_result"
    assert history_trace.steps[-1].label == "Dify Result"
    assert history_trace.steps[-1].meta["answer_chars"] == 26
    assert history_trace.steps[-1].meta["source_message_id"] == "dify-msg-001"
