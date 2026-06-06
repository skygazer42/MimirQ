from __future__ import annotations

import uuid

import langchain
import pytest
from fastapi import HTTPException


@pytest.fixture(autouse=True)
def _stub_langchain_globals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(langchain, "debug", False, raising=False)
    monkeypatch.setattr(langchain, "verbose", False, raising=False)


def test_retrieval_scope_rejects_empty_explicit_dataset_even_when_empty_docs_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.rag as rag_api
    import app.services.dataset_profile_service as profile_service
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)

    class _EmptyQuery:
        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def with_entities(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def limit(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def first(self):
            return None

    monkeypatch.setattr(
        profile_service,
        "build_dataset_documents_query",
        lambda *_args, **_kwargs: (object(), _EmptyQuery()),
        raising=True,
    )

    with pytest.raises(HTTPException) as exc:
        rag_api._enforce_non_empty_retrieval_scope(  # noqa: SLF001
            db=object(),
            tenant_id=uuid.uuid4(),
            account_id="u",
            scope_document_ids=[],
            scope_dataset_id=uuid.uuid4(),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "No accessible documents for retrieval"


@pytest.mark.asyncio
async def test_blocking_retrieval_limiter_runs_work_in_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.rag_runtime_limiter as limiter

    captured: dict = {}

    async def _to_thread(func, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        captured["offloaded_func"] = func
        return func(*args, **kwargs)

    monkeypatch.setattr(limiter.asyncio, "to_thread", _to_thread, raising=True)

    def _work(value: int) -> int:
        return value + 1

    out = await limiter.run_blocking_retrieval_call(_work, 41)

    assert out == 42
    assert captured.get("offloaded_func") is limiter._run_with_gate_timed  # noqa: SLF001


def test_blocking_retrieval_limiter_defaults_to_serial_backend_protection() -> None:
    import app.services.rag_runtime_limiter as limiter

    assert limiter._configured_limit() == 1  # noqa: SLF001


@pytest.mark.asyncio
async def test_blocking_retrieval_limiter_reports_queue_and_exec_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    async def _to_thread(func, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        return func(*args, **kwargs)

    monkeypatch.setattr(limiter.asyncio, "to_thread", _to_thread, raising=True)
    metrics: dict = {}

    def _work(value: int) -> int:
        return value + 1

    out = await limiter.run_blocking_retrieval_call(_work, 41, runtime_metrics=metrics)

    assert out == 42
    assert metrics["rag_offload_limit"] == 1
    assert metrics["rag_offload_queue_ms"] >= 0.0
    assert metrics["rag_offload_exec_ms"] >= 0.0


@pytest.mark.asyncio
async def test_rag_retrieve_passes_must_recall_fields_into_rag_state(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.rag as rag_api
    from app.api.schemas.chat import ChatRAGConfig
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_ALLOW_OPEN_SCOPE", True, raising=False)
    monkeypatch.setattr(rag_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    captured: dict = {}

    def _build_rag_state(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return {}

    def _retrieve_node(_state):  # noqa: ANN001
        return {"citations": [], "metrics": {}, "query_for_retrieval": "q"}

    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod

    monkeypatch.setattr(lg_mod, "build_rag_state", _build_rag_state, raising=True)
    monkeypatch.setattr(orch_mod, "run_retrieval", _retrieve_node, raising=True)

    body = rag_api.EvidenceRetrieveRequest(
        query="q",
        rag_config=ChatRAGConfig(
            retrieval_contract_mode="must_recall_strict",
            must_recall=True,
            must_recall_expected_source_keys=["inventory", "users"],
            must_recall_required_anchor_fields=["chunk_id", "document_id"],
        ),
    )
    response = await rag_api.retrieve_evidence(
        body=body,
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )

    assert captured.get("retrieval_contract_mode") == "must_recall_strict"
    assert captured.get("must_recall") is True
    assert list(captured.get("must_recall_expected_source_keys") or []) == ["inventory", "users"]
    assert list(captured.get("must_recall_required_anchor_fields") or []) == ["chunk_id", "document_id"]
    capsule = response.evidence_capsule or {}
    assert str(capsule.get("schema") or "") == "mimirq.evidence_capsule.v1"
    assert str(capsule.get("capsule_hash") or "")


@pytest.mark.asyncio
async def test_rag_retrieve_passes_hierarchy_recall_fields_into_rag_state(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.rag as rag_api
    from app.api.schemas.chat import ChatRAGConfig
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_ALLOW_OPEN_SCOPE", True, raising=False)
    monkeypatch.setattr(rag_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    captured: dict = {}

    def _build_rag_state(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return {}

    def _retrieve_node(_state):  # noqa: ANN001
        return {"citations": [], "metrics": {}, "query_for_retrieval": "q"}

    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod

    monkeypatch.setattr(lg_mod, "build_rag_state", _build_rag_state, raising=True)
    monkeypatch.setattr(orch_mod, "run_retrieval", _retrieve_node, raising=True)

    body = rag_api.EvidenceRetrieveRequest(
        query="q",
        rag_config=ChatRAGConfig(retrieval_profile="hierarchy_recall20"),
    )
    await rag_api.retrieve_evidence(
        body=body,
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )

    assert captured.get("retrieval_profile") == "hierarchy_recall20"
    assert captured.get("enable_hierarchy_recall") is True
    assert captured.get("hierarchy_family_collapse") is True
    assert captured.get("hierarchy_overfetch_factor") == 4


@pytest.mark.asyncio
async def test_retrieve_preview_accepts_dataset_ids_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.rag as rag_api
    from app.api.schemas.chat import ChatRAGConfig
    from app.core.config import settings

    ds1 = uuid.uuid4()
    ds2 = uuid.uuid4()

    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_ALLOW_OPEN_SCOPE", False, raising=False)
    monkeypatch.setattr(rag_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(rag_api.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(rag_api.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(rag_api, "_enforce_non_empty_retrieval_scope", lambda *_a, **_k: None, raising=True)

    captured: dict = {}

    def _build_rag_state(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return dict(kwargs)

    def _run_retrieval(state):  # noqa: ANN001
        return {"citations": [], "metrics": {}, "query_for_retrieval": state.get("question") or ""}

    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod

    monkeypatch.setattr(lg_mod, "build_rag_state", _build_rag_state, raising=True)
    monkeypatch.setattr(orch_mod, "run_retrieval", _run_retrieval, raising=True)

    response = await rag_api.retrieve_preview(
        body=rag_api.RetrievePreviewRequest(
            query="社保卡在哪里办理",
            dataset_ids=[ds1, ds2],
            rag_config=ChatRAGConfig(top_k=10, score_threshold=0.35),
        ),
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )

    assert captured.get("dataset_id") is None
    assert captured.get("document_ids") is None
    assert captured.get("metadata_filter") == {"dataset_id": {"$in": [str(ds1), str(ds2)]}}
    assert response.metrics["scope_dataset_ids"] == [str(ds1), str(ds2)]


@pytest.mark.asyncio
async def test_retrieve_evidence_accepts_dataset_ids_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.rag as rag_api
    from app.api.schemas.chat import ChatRAGConfig
    from app.core.config import settings

    ds1 = uuid.uuid4()
    ds2 = uuid.uuid4()

    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_ALLOW_OPEN_SCOPE", False, raising=False)
    monkeypatch.setattr(rag_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(rag_api.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(rag_api.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(rag_api, "_enforce_non_empty_retrieval_scope", lambda *_a, **_k: None, raising=True)

    captured: dict = {}

    def _build_rag_state(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return dict(kwargs)

    def _run_retrieval(state):  # noqa: ANN001
        return {
            "citations": [{"document_id": "doc-1", "content": "命中"}],
            "metrics": {},
            "query_for_retrieval": state.get("question") or "",
        }

    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod

    monkeypatch.setattr(lg_mod, "build_rag_state", _build_rag_state, raising=True)
    monkeypatch.setattr(orch_mod, "run_retrieval", _run_retrieval, raising=True)

    response = await rag_api.retrieve_evidence(
        body=rag_api.EvidenceRetrieveRequest(
            query="社保卡在哪里办理",
            dataset_ids=[ds1, ds2],
            rag_config=ChatRAGConfig(top_k=10, score_threshold=0.35),
        ),
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )

    assert captured.get("dataset_id") is None
    assert captured.get("document_ids") is None
    assert captured.get("metadata_filter") == {"dataset_id": {"$in": [str(ds1), str(ds2)]}}
    assert response.metrics["scope_dataset_ids"] == [str(ds1), str(ds2)]
    assert response.has_evidence is True


@pytest.mark.asyncio
async def test_retrieve_preview_offloads_blocking_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.rag as rag_api
    from app.api.schemas.chat import ChatRAGConfig
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_ALLOW_OPEN_SCOPE", True, raising=False)
    monkeypatch.setattr(rag_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    captured: dict = {}

    def _build_rag_state(**kwargs):  # noqa: ANN003
        return dict(kwargs)

    def _run_retrieval(state):  # noqa: ANN001
        return {"citations": [], "metrics": {}, "query_for_retrieval": state.get("question") or ""}

    async def _run_blocking_retrieval_call(func, *args, runtime_metrics=None, **kwargs):  # noqa: ANN001, ANN002, ANN003
        captured["offloaded"] = True
        captured["func"] = func
        if runtime_metrics is not None:
            runtime_metrics.update({})
        return func(*args, **kwargs)

    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod

    monkeypatch.setattr(lg_mod, "build_rag_state", _build_rag_state, raising=True)
    monkeypatch.setattr(orch_mod, "run_retrieval", _run_retrieval, raising=True)
    monkeypatch.setattr(rag_api, "run_blocking_retrieval_call", _run_blocking_retrieval_call, raising=True)

    await rag_api.retrieve_preview(
        body=rag_api.RetrievePreviewRequest(query="q", rag_config=ChatRAGConfig()),
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )

    assert captured == {"offloaded": True, "func": _run_retrieval}


@pytest.mark.asyncio
async def test_retrieve_preview_reports_blocking_retrieval_offload_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.rag as rag_api
    from app.api.schemas.chat import ChatRAGConfig
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_ALLOW_OPEN_SCOPE", True, raising=False)
    monkeypatch.setattr(rag_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    def _build_rag_state(**kwargs):  # noqa: ANN003
        return dict(kwargs)

    def _run_retrieval(state):  # noqa: ANN001
        return {"citations": [], "metrics": {}, "query_for_retrieval": state.get("question") or ""}

    async def _run_blocking_retrieval_call(func, *args, runtime_metrics=None, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if runtime_metrics is not None:
            runtime_metrics.update(
                {
                    "rag_offload_limit": 1,
                    "rag_offload_queue_ms": 12.3,
                    "rag_offload_exec_ms": 45.6,
                }
            )
        return func(*args, **kwargs)

    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod

    monkeypatch.setattr(lg_mod, "build_rag_state", _build_rag_state, raising=True)
    monkeypatch.setattr(orch_mod, "run_retrieval", _run_retrieval, raising=True)
    monkeypatch.setattr(rag_api, "run_blocking_retrieval_call", _run_blocking_retrieval_call, raising=True)

    res = await rag_api.retrieve_preview(
        body=rag_api.RetrievePreviewRequest(query="q", rag_config=ChatRAGConfig()),
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )

    assert res.metrics["rag_offload_limit"] == 1
    assert res.metrics["rag_offload_queue_ms"] == pytest.approx(12.3)
    assert res.metrics["rag_offload_exec_ms"] == pytest.approx(45.6)


@pytest.mark.asyncio
async def test_retrieve_preview_explicit_query_image_injects_image_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.rag as rag_api
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)
    monkeypatch.setattr(rag_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(rag_api.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(rag_api.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)

    class _NonEmptyQuery:
        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def with_entities(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def limit(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def first(self):
            return object()

    import app.services.dataset_profile_service as profile_service

    monkeypatch.setattr(
        profile_service,
        "build_dataset_documents_query",
        lambda *_args, **_kwargs: (object(), _NonEmptyQuery()),
        raising=True,
    )

    captured_state: dict = {}

    def _build_rag_state(**kwargs):  # noqa: ANN003
        return dict(kwargs)

    def _run_retrieval(state):  # noqa: ANN001
        captured_state.update(state)
        return {
            "citations": [],
            "metrics": {},
            "query_for_retrieval": state.get("question") or "",
        }

    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod

    monkeypatch.setattr(lg_mod, "build_rag_state", _build_rag_state, raising=True)
    monkeypatch.setattr(orch_mod, "run_retrieval", _run_retrieval, raising=True)
    monkeypatch.setattr(
        "app.services.chat_image_service.build_chat_image_context_docs",
        lambda *_a, **_k: ([{"page_content": "image-doc", "metadata": {"kind": "image"}}], {"enabled": True, "used": True, "reason": "explicit_query_image", "hits": 1, "returned": 1}),
        raising=True,
    )

    body = rag_api.RetrievePreviewRequest(
        query="Explain the login flow",
        query_image="Show the login screenshot",
        dataset_id=uuid.uuid4(),
    )
    res = await rag_api.retrieve_preview(
        body=body,
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )

    assert captured_state.get("tag_docs") == [{"page_content": "image-doc", "metadata": {"kind": "image"}}]
    assert (captured_state.get("image_meta") or {}).get("query_source") == "query_image"
    assert (captured_state.get("multimodal_router") or {}).get("modality") == "image"
    assert (res.metrics.get("multimodal_router") or {}).get("reasons") == ["explicit_query_image"]
    assert (res.metrics.get("image") or {}).get("query_source") == "query_image"


@pytest.mark.asyncio
async def test_retrieve_preview_passes_query_decomposition_override_into_rag_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.rag as rag_api
    from app.api.schemas.chat import ChatRAGConfig
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_ALLOW_OPEN_SCOPE", True, raising=False)
    monkeypatch.setattr(rag_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    captured: dict = {}

    def _build_rag_state(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return dict(kwargs)

    def _run_retrieval(state):  # noqa: ANN001
        return {
            "citations": [],
            "metrics": {"decompose_enabled": bool(state.get("enable_query_decomposition"))},
            "query_for_retrieval": state.get("question") or "",
        }

    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod

    monkeypatch.setattr(lg_mod, "build_rag_state", _build_rag_state, raising=True)
    monkeypatch.setattr(orch_mod, "run_retrieval", _run_retrieval, raising=True)

    body = rag_api.RetrievePreviewRequest(
        query="q",
        rag_config=ChatRAGConfig(enable_query_decomposition=False),
    )
    await rag_api.retrieve_preview(
        body=body,
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )

    assert captured.get("enable_query_decomposition") is False
