import asyncio
import importlib.util
import sys
from enum import Enum
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

MODULE_PATH = Path("/data/temp34/MimirQ/app/rag/evaluation/kg_search_diagnostics.py")


class _SimpleModel:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


class _RerankStrategy(str, Enum):
    PAGERANK = "pagerank"
    RRF = "rrf"


class _SearchConfig:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)
        self.rerank = SimpleNamespace(strategy=_RerankStrategy.PAGERANK, max_results=0)
        self.expand = SimpleNamespace(enabled=True, max_hops=2)


def _compute_kg_hit_metrics(*, events: list[dict[str, Any]], evidence_chunk_ids: set[str], k: int) -> dict[str, Any]:
    evidence = {str(value).strip() for value in evidence_chunk_ids}
    matches = [
        index for index, event in enumerate(events or [], 1) if str(event.get("chunk_id") or "").strip() in evidence
    ]
    first_hit = matches[0] if matches else None
    matched = {
        str(event.get("chunk_id") or "").strip()
        for event in events or []
        if str(event.get("chunk_id") or "").strip() in evidence
    }
    return {
        "hit_at_k": bool(first_hit is not None and first_hit <= k),
        "mrr": (1.0 / first_hit) if first_hit else 0.0,
        "recall": (len(matched) / len(evidence)) if evidence else 0.0,
        "ndcg": (1.0 / first_hit) if first_hit else 0.0,
        "map": (1.0 / first_hit) if first_hit else 0.0,
        "matched_evidence_chunks": len(matched),
        "total_evidence_chunks": len(evidence),
        "k": k,
    }


def _install_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    def add_module(name: str, **attrs: Any) -> ModuleType:
        module = ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        if "." not in name:
            module.__path__ = []  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, name, module)
        return module

    for package_name in [
        "app",
        "app.api",
        "app.api.schemas",
        "app.core",
        "app.models",
        "app.rag",
        "app.rag.evaluation",
        "app.rag.kg",
        "app.rag.kg.search",
        "app.services",
    ]:
        pkg = add_module(package_name)
        pkg.__path__ = []  # type: ignore[attr-defined]

    add_module(
        "app.api.schemas.kg_diagnostics",
        KGEvalAttribution=_SimpleModel,
        KGHardcaseOut=_SimpleModel,
        KGSearchDiagnosticsItem=_SimpleModel,
        KGSearchDiagnosticsRequest=_SimpleModel,
        KGSearchDiagnosticsResponse=_SimpleModel,
        KGSearchDiagnosticsSummary=_SimpleModel,
        KGSearchEntityOut=_SimpleModel,
        KGSearchEventOut=_SimpleModel,
        KGSearchRunMetrics=_SimpleModel,
        KGSearchRunResult=_SimpleModel,
    )
    add_module("app.core.config", settings=SimpleNamespace(KG_EXTRACT_MAX_CONCURRENCY=3))
    add_module("app.models.document", Document=type("Document", (), {}), DocumentChunk=type("DocumentChunk", (), {}))
    add_module("app.models.evaluation", RagasRegressionCase=type("RagasRegressionCase", (), {}))
    add_module(
        "app.rag.evaluation.kg_hardcase_deterministic",
        generate_hardcases_deterministic=lambda **_kwargs: [],
    )
    add_module(
        "app.rag.evaluation.kg_hardcase_generator",
        generate_hardcases_llm=lambda **_kwargs: [],
    )
    add_module(
        "app.rag.evaluation.kg_search_diagnostics_metrics",
        compute_kg_hit_metrics=_compute_kg_hit_metrics,
    )
    add_module(
        "app.rag.kg.models",
        KgEntity=type("KgEntity", (), {}),
        KgEventEntity=type("KgEventEntity", (), {}),
        KgRelation=type("KgRelation", (), {}),
        KgSourceEvent=type("KgSourceEvent", (), {}),
    )
    add_module(
        "app.rag.kg.search.config",
        RerankStrategy=_RerankStrategy,
        SearchConfig=_SearchConfig,
    )
    add_module("app.rag.kg.search.searcher", KGSearcher=type("KGSearcher", (), {}))
    add_module(
        "app.rag.kg.utils",
        get_logger=lambda _name: SimpleNamespace(debug=lambda *_a, **_k: None, warning=lambda *_a, **_k: None),
    )
    add_module(
        "app.services.regression_run_scope",
        validate_case_ids_belong_to_dataset=lambda **_kwargs: None,
    )

    spec = importlib.util.spec_from_file_location("tests.kg_search_diagnostics_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class _FakeField:
    def __init__(self, name: str) -> None:
        self.name = name

    def __eq__(self, other: Any) -> tuple[str, str, Any]:  # type: ignore[override]
        return ("eq", self.name, other)

    def in_(self, values: Any) -> tuple[str, str, list[Any]]:
        return ("in", self.name, list(values))

    def desc(self) -> tuple[str, str]:
        return ("desc", self.name)


class _CaseQuery:
    def __init__(self, cases: list[Any], fields: tuple[Any, ...]) -> None:
        self._cases = list(cases)
        self._fields = fields

    def filter(self, *conditions: Any) -> "_CaseQuery":
        for op, name, value in conditions:
            if op == "eq":
                self._cases = [case for case in self._cases if getattr(case, name) == value]
            if op == "in":
                allowed = set(value)
                self._cases = [case for case in self._cases if getattr(case, name) in allowed]
        return self

    def order_by(self, order: tuple[str, str]) -> "_CaseQuery":
        direction, field_name = order
        self._cases.sort(key=lambda case: getattr(case, field_name), reverse=(direction == "desc"))
        return self

    def limit(self, size: int) -> "_CaseQuery":
        self._cases = self._cases[:size]
        return self

    def count(self) -> int:
        return len(self._cases)

    def all(self) -> list[Any]:
        if self._fields and self._fields[0] is not self._model:
            return [tuple(getattr(case, field.name) for field in self._fields) for case in self._cases]
        return list(self._cases)

    @property
    def _model(self) -> Any:
        return self._fields[0] if len(self._fields) == 1 else None


class _CaseDB:
    def __init__(self, cases: list[Any]) -> None:
        self.cases = cases
        self.rollback_calls = 0

    def query(self, *fields: Any) -> _CaseQuery:
        return _CaseQuery(self.cases, fields)

    def rollback(self) -> None:
        self.rollback_calls += 1


class _FakeSearcher:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[Any] = []

    async def search(self, cfg: Any) -> Any:
        self.calls.append(cfg)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _event(chunk_id: Any, *, title: str = "event") -> dict[str, Any]:
    return {
        "id": f"event-{chunk_id}",
        "title": title,
        "summary": title,
        "content": title,
        "chunk_id": str(chunk_id),
        "score": 1.0,
    }


def test_load_cases_validates_case_acl_and_preserves_updated_order(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _install_module(monkeypatch)
    module.RagasRegressionCase = type(
        "FakeCaseModel",
        (),
        {
            "tenant_id": _FakeField("tenant_id"),
            "dataset_id": _FakeField("dataset_id"),
            "id": _FakeField("id"),
            "updated_at": _FakeField("updated_at"),
        },
    )

    tenant_id = uuid4()
    dataset_id = uuid4()
    case_old = SimpleNamespace(id=uuid4(), tenant_id=tenant_id, dataset_id=dataset_id, updated_at=1)
    case_new = SimpleNamespace(id=uuid4(), tenant_id=tenant_id, dataset_id=dataset_id, updated_at=5)
    case_other = SimpleNamespace(id=uuid4(), tenant_id=tenant_id, dataset_id=uuid4(), updated_at=9)
    db = _CaseDB([case_old, case_new, case_other])
    validate_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(module, "validate_case_ids_belong_to_dataset", lambda **kwargs: validate_calls.append(kwargs))

    total, cases = module._load_cases(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        req=SimpleNamespace(case_ids=[case_old.id, case_old.id, case_new.id]),
        max_cases=10,
    )

    assert total == 2
    assert [case.id for case in cases] == [case_new.id, case_old.id]
    assert validate_calls[0]["case_ids"] == [case_old.id, case_new.id]
    assert validate_calls[0]["rows"] == [
        (case_old.id, dataset_id),
        (case_new.id, dataset_id),
    ]


def test_run_kg_search_diagnostics_deterministic_scope_order_and_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _install_module(monkeypatch)
    dataset_id = uuid4()
    scoped_doc_id = uuid4()
    chunk_hit = uuid4()
    chunk_miss = uuid4()
    case_scoped = SimpleNamespace(
        id=uuid4(),
        question="scoped question",
        tags=["scoped"],
        document_ids=[scoped_doc_id],
        reference_sources=[{"chunk_id": str(chunk_hit), "quote": "quote"}],
    )
    case_failed = SimpleNamespace(
        id=uuid4(),
        question="failed question",
        tags=["failed"],
        document_ids=[],
        reference_sources=[{"chunk_id": str(chunk_miss), "quote": "quote"}],
    )
    responses = [
        {"events": [_event(chunk_hit, title="baseline hit")], "entities": [], "clues": [], "stats": {}},
        {"events": [], "entities": [], "clues": [], "stats": {"relation_expansion": {"enabled": True}}},
        {"events": [], "entities": [], "clues": [], "stats": {"relation_expansion": {"enabled": True}}},
        {"events": [], "entities": [], "clues": [], "stats": {"relation_expansion": {"enabled": True}}},
        {"events": [], "entities": [], "clues": [], "stats": {"relation_expansion": {"enabled": True}}},
        {"events": [], "entities": [], "clues": [], "stats": {"relation_expansion": {"enabled": True}}},
        {"events": [_event(chunk_miss, title="hardcase hit")], "entities": [], "clues": [], "stats": {}},
    ]
    fake_searcher = _FakeSearcher(responses)
    monkeypatch.setattr(module, "KGSearcher", lambda: fake_searcher)
    monkeypatch.setattr(module, "_load_cases", lambda *_a, **_k: (2, [case_scoped, case_failed]))
    monkeypatch.setattr(
        module,
        "_resolve_ground_truth_event_ids",
        lambda _db, **kwargs: ["gt"] if str(chunk_miss) in kwargs["evidence_chunk_ids"] else ["gt-hit"],
    )
    monkeypatch.setattr(module, "_ground_truth_has_skill", lambda *_a, **_k: False)
    monkeypatch.setattr(
        module,
        "_deterministic_hardcase_candidates",
        lambda *_a, **_k: ([("a", "b")], ["skill"], ["tag"]),
    )
    monkeypatch.setattr(
        module,
        "generate_hardcases_deterministic",
        lambda **_kwargs: [SimpleNamespace(kind="knowledge_pressure", question="hardcase q", rationale="why")],
    )

    response = asyncio.run(
        module.run_kg_search_diagnostics(
            db=SimpleNamespace(rollback=lambda: None),
            tenant_id=uuid4(),
            account_id="acct",
            req=SimpleNamespace(
                dataset_id=dataset_id,
                case_ids=[],
                max_cases=5,
                k=3,
                auto_extract_kg=False,
                extract_skills=None,
                extract_relations=None,
                hardcase_mode="deterministic",
                hardcases_per_failed_case=1,
                max_failed_cases_for_hardcase=3,
                llm_temperature=0.2,
            ),
        )
    )

    assert [item.case_id for item in response.items] == [case_scoped.id, case_failed.id]
    assert fake_searcher.calls[0].dataset_id is None
    assert fake_searcher.calls[0].document_ids == [scoped_doc_id]
    assert fake_searcher.calls[1].dataset_id == dataset_id
    assert fake_searcher.calls[-1].query == "hardcase q"
    assert response.items[1].hardcases[0].run.query == "hardcase q"
    assert response.items[1].hardcases[0].run.metrics.hit_at_k is True
    assert response.summary.hardcases_generated == 1


def test_run_kg_search_diagnostics_preflight_and_llm_hardcases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _install_module(monkeypatch)
    dataset_id = uuid4()
    doc_ok = uuid4()
    doc_fail = uuid4()
    chunk_id = uuid4()
    case = SimpleNamespace(
        id=uuid4(),
        question="llm question",
        tags=["llm"],
        document_ids=[],
        reference_sources=[
            {"chunk_id": str(chunk_id), "document_id": str(doc_ok), "quote": "alpha"},
            {"chunk_id": str(chunk_id), "document_id": str(doc_fail), "quote": "beta"},
        ],
    )
    db = _CaseDB([case])
    responses = [
        {
            "events": [],
            "entities": [],
            "clues": [],
            "stats": {"relation_expansion": {"enabled": True, "edges_used": 1}},
        },
        {
            "events": [],
            "entities": [],
            "clues": [],
            "stats": {"relation_expansion": {"enabled": True, "edges_used": 1}},
        },
        {
            "events": [_event(chunk_id, title="relation fix")],
            "entities": [],
            "clues": [],
            "stats": {"relation_expansion": {"enabled": False}},
        },
        {
            "events": [],
            "entities": [],
            "clues": [],
            "stats": {"relation_expansion": {"enabled": True, "edges_used": 1}},
        },
        {
            "events": [],
            "entities": [],
            "clues": [],
            "stats": {"relation_expansion": {"enabled": True, "edges_used": 1}},
        },
        {
            "events": [_event(chunk_id, title="llm hardcase hit")],
            "entities": [],
            "clues": [],
            "stats": {},
        },
    ]
    fake_searcher = _FakeSearcher(responses)
    monkeypatch.setattr(module, "KGSearcher", lambda: fake_searcher)
    monkeypatch.setattr(module, "_load_cases", lambda *_a, **_k: (1, [case]))
    monkeypatch.setattr(module, "_resolve_ground_truth_event_ids", lambda *_a, **_k: ["gt"])
    monkeypatch.setattr(module, "_ground_truth_has_skill", lambda *_a, **_k: False)
    monkeypatch.setattr(module, "_load_missing_kg_document_ids", lambda *_a, **_k: [doc_ok, doc_fail])

    async def fake_extract(**kwargs: Any) -> tuple[bool, str | None, int]:
        if kwargs["document_id"] == doc_ok:
            return True, None, 2
        return False, "boom", 0

    async def fake_llm_client() -> object:
        return object()

    async def fake_llm_hardcases(**_kwargs: Any) -> list[Any]:
        return [SimpleNamespace(kind="reasoning_pressure", question="llm hardcase", rationale="because")]

    monkeypatch.setattr(module, "_ensure_kg_extracted_for_document", fake_extract)
    monkeypatch.setattr(module, "_load_kg_diagnostics_llm_client", fake_llm_client)
    monkeypatch.setattr(module, "generate_hardcases_llm", fake_llm_hardcases)

    response = asyncio.run(
        module.run_kg_search_diagnostics(
            db=db,
            tenant_id=uuid4(),
            account_id="acct",
            req=SimpleNamespace(
                dataset_id=dataset_id,
                case_ids=[],
                max_cases=5,
                k=3,
                auto_extract_kg=True,
                extract_skills=None,
                extract_relations=None,
                hardcase_mode="llm",
                hardcases_per_failed_case=1,
                max_failed_cases_for_hardcase=2,
                llm_temperature=0.2,
            ),
        )
    )

    assert response.summary.preflight["documents_total"] == 2
    assert response.summary.preflight["documents_missing_kg"] == 2
    assert response.summary.preflight["documents_extracted_ok"] == 1
    assert response.summary.preflight["documents_extracted_failed"] == 1
    assert response.summary.preflight["errors"] == [{"document_id": str(doc_fail), "error": "boom", "event_count": 0}]
    assert db.rollback_calls == 1
    assert response.items[0].attribution.primary_cause == "relation"
    assert response.summary.hardcases_generated == 1
    assert response.items[0].hardcases[0].run.metrics.hit_at_k is True
