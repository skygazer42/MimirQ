from __future__ import annotations

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
    assert all(call[2] == 2 for call in calls)
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


def test_dify_retrieval_expands_dataset_mapping_by_query_terms(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    city_dataset = uuid.uuid4()
    xinbei_dataset = uuid.uuid4()
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
            '{"terms": ["新北区", "新北"], '
            f'"dataset_ids": ["{xinbei_dataset}"], '
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
                "chunk_content": "新北区社会保障卡补卡办理地点",
                "relevance_score": 0.91,
                "document_name": "新北区事项清单.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(xinbei_dataset),
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
            "query": "新北区社保卡补卡在哪里办理",
            "retrieval_setting": {"top_k": 2, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    assert calls == [[xinbei_dataset, city_dataset]]
    assert res.json()["records"][0]["content"] == "新北区社会保障卡补卡办理地点"


def test_dify_retrieval_prefers_full_chunk_content_over_short_citation_snippet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    full_content = (
        "区县：新北区\n"
        "事项名称：社会保障卡补卡\n"
        "办理地点：新北区政务服务中心\n"
        "办理材料：居民身份证件（必要）\n"
        "咨询方式：0519-12333"
    )

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"xinbei": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": "区县：新北区...",
                "relevance_score": 0.73,
                "document_name": "新北区事项清单.txt",
                "document_id": str(document_id),
                "chunk_id": str(chunk_id),
                "dataset_id": str(dataset_id),
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
            "knowledge_id": "xinbei",
            "query": "新北区社保卡补卡在哪里办理",
            "retrieval_setting": {"top_k": 1, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    content = res.json()["records"][0]["content"]
    assert content.startswith("答案要点：")
    assert "事项名称：社会保障卡补卡" in content
    assert "办理地点：新北区政务服务中心" in content
    assert "咨询方式：0519-12333" in content
    assert content.endswith(full_content)


def test_dify_retrieval_prepends_structured_answer_hints_for_fee_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    full_content = (
        "区县：经开区\n"
        "事项名称：社会保障卡补卡\n"
        "办理地点：常州市锦绣路2号常州市政务服务中心1号楼一楼C区2-9号窗口\n"
        "收费情况：不收费\n"
        "咨询方式：0519-12333，0519-85519290"
    )

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"jingkai": "{dataset_id}"}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**_kwargs):  # noqa: ANN003, ANN202
        return [
            {
                "chunk_content": full_content,
                "relevance_score": 0.73,
                "document_name": "经开区事项清单.txt",
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
            "knowledge_id": "jingkai",
            "query": "经开区社保卡补卡在哪里办理",
            "retrieval_setting": {"top_k": 1, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    content = res.json()["records"][0]["content"]
    hint = content.split("\n\n原始证据：", 1)[0]
    assert "办理地点：常州市锦绣路2号常州市政务服务中心1号楼一楼C区2-9号窗口" in hint
    assert "收费情况：不收费" in hint
    assert "咨询方式：0519-12333，0519-85519290" in hint
    assert full_content in content


def test_dify_retrieval_prepends_qa_answer_hints_for_long_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    full_content = (
        "检索锚点：汽车置换更新；以旧换新；购车补贴；主题：常州市高频应用知识\n"
        "问题：汽车置换更新\n"
        "答案：汽车置换更新可以在苏服办APP进行2025年补贴申请，可以申请两种类型的补贴："
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
                "document_name": "常州市高频应用知识.xlsx",
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
            "query": "汽车置换补贴怎么申请",
            "retrieval_setting": {"top_k": 1, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    content = res.json()["records"][0]["content"]
    first_line = content.splitlines()[0]
    assert first_line == "必答要点：回答申请/入口/类型类问题时必须保留这些选项名称：卖旧置换更新补贴、报废置换更新补贴"
    hint = content.split("\n\n原始证据：", 1)[0]
    assert "苏服办APP" in hint
    assert "2025年补贴申请" in hint
    assert "卖旧置换更新补贴" in hint
    assert "报废置换更新补贴" in hint
    assert content.endswith(full_content)


def test_dify_retrieval_frontloads_enumerated_options_from_existing_answer_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    full_content = (
        "答案要点：答案：汽车置换更新可以在苏服办APP进行2025年补贴申请，"
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
                "document_name": "常州市高频应用知识.xlsx",
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
                "document_name": "常州市本级12345QA.txt",
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
            "query": "身份证办证进度查询有哪些方式",
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

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    full_content = (
        "答案：网上办理流程如下：1.登录江苏政务服务网；"
        "2.选择社会保障卡居民服务一件事；3.提交申请材料。"
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
            "query": "社会保障卡居民服务一件事网上办理怎么操作",
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
                "document_name": "常州市高频应用知识.xlsx",
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

    token = "dify-test-token"
    dataset_id = uuid.uuid4()
    full_content = (
        "事项名称：社会保障卡密码修改与重置\n"
        "办理地点：常州市政务服务中心\n"
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
                "document_name": "常州市事项清单.txt",
                "chunk_id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "metadata": {"service_name": "社会保障卡密码修改与重置"},
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
            "query": "社会保障卡居民服务一件事网上办理怎么操作",
            "retrieval_setting": {"top_k": 2, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    records = res.json()["records"]
    assert records[0]["content"] == "步骤说明正文"
    assert records[0]["metadata"]["_evaluable_metadata"]["section_type"] == "operation_steps"
    assert records[1]["content"] == "入口说明正文"


def test_dify_retrieval_uses_section_type_intent_fallback_without_metadata_intents(
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
                "chunk_content": "检索锚点：社会保障卡居民服务一件事；章节意图：在线入口、操作手册入口\n入口说明正文",
                "relevance_score": 0.73,
                "document_name": "一件事操作指引.txt",
                "chunk_id": str(uuid.uuid4()),
                "metadata": {"section_type": "operation_url"},
            },
            {
                "chunk_content": "检索锚点：社会保障卡居民服务一件事；章节意图：申报流程、网上办理怎么操作\n步骤说明正文",
                "relevance_score": 0.73,
                "document_name": "一件事操作指引.txt",
                "chunk_id": str(uuid.uuid4()),
                "metadata": {"section_type": "operation_steps"},
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
            "query": "社会保障卡居民服务一件事网上办理怎么操作",
            "retrieval_setting": {"top_k": 2, "score_threshold": 0.0},
        },
    )

    assert res.status_code == 200, res.text
    records = res.json()["records"]
    assert "步骤说明正文" in records[0]["content"]
    assert "入口说明正文" in records[1]["content"]


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
                "chunk_content": "检索锚点：社会保障卡居民服务一件事；章节意图：在线入口、操作手册入口\n入口说明正文",
                "relevance_score": 0.73,
                "document_name": "一件事操作指引.txt",
                "chunk_id": str(uuid.uuid4()),
                "metadata": {},
            },
            {
                "chunk_content": "检索锚点：社会保障卡居民服务一件事；章节意图：申报流程、网上办理怎么操作\n步骤说明正文",
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
            "query": "社会保障卡居民服务一件事网上办理怎么操作",
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
