from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "run_nightly_ablations.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("run_nightly_ablations", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_default_ablations_include_hybrid_rerank_variant() -> None:
    mod = _load_module()

    ablations = mod._default_ablations()  # type: ignore[attr-defined]
    assert isinstance(ablations, list) and ablations

    assert any(
        (ab.get("rag_params") or {}).get("retrieval_mode") == "hybrid"
        and bool((ab.get("rag_params") or {}).get("enable_reranker"))
        for ab in ablations
    )


def test_default_ablations_cover_key_runtime_knobs() -> None:
    mod = _load_module()

    ablations = mod._default_ablations()  # type: ignore[attr-defined]
    assert isinstance(ablations, list) and ablations
    assert len(ablations) <= 10  # keep nightly cheap/bounded

    rag_params_list = [dict(ab.get("rag_params") or {}) for ab in ablations]

    assert any(rp.get("retrieval_profile") == "recall50" for rp in rag_params_list)
    assert any(rp.get("fusion_strategy") == "linear" for rp in rag_params_list)
    assert any(rp.get("fusion_strategy") == "budgeted_rrf" for rp in rag_params_list)
    assert any(bool(rp.get("sparse_retrieval_enabled")) for rp in rag_params_list)
    assert any(
        ab.get("ablation_key") == "sparse_bounded_slice"
        for ab in ablations
    )

    # Retrieval-only friendly by default: no LLM-backed query rewrite / multi-query in defaults.
    assert all(not bool(rp.get("enable_query_rewrite")) for rp in rag_params_list)
    assert all(not bool(rp.get("enable_multi_query")) for rp in rag_params_list)

    for rp in rag_params_list:
        if rp.get("sparse_retrieval_enabled"):
            assert str(rp.get("sparse_retrieval_provider") or "").strip()

    sparse_slice = next((ab for ab in ablations if ab.get("ablation_key") == "sparse_bounded_slice"), None)
    assert isinstance(sparse_slice, dict)
    sparse_rp = dict((sparse_slice or {}).get("rag_params") or {})
    assert sparse_rp.get("retrieval_mode") == "keyword"
    assert sparse_rp.get("fusion_strategy") == "budgeted_rrf"
    assert bool(sparse_rp.get("sparse_retrieval_enabled")) is True
    budgets = dict(sparse_rp.get("fusion_budgets") or {})
    assert int(budgets.get("sparse") or 0) > 0
    assert int(budgets.get("vector") or 0) == 0


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def order_by(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def limit(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def all(self):
        return list(self._result) if isinstance(self._result, list) else []

    def first(self):
        if isinstance(self._result, list):
            return self._result[0] if self._result else None
        return self._result


class _FakeDB:
    def __init__(self, *, dataset, cases):
        self._dataset = dataset
        self._cases = cases
        self.added = []

    def query(self, model):  # noqa: ANN001
        name = getattr(model, "__name__", str(model))
        if name == "Dataset":
            return _FakeQuery(self._dataset)
        if name == "RagasRegressionCase":
            return _FakeQuery(self._cases)
        raise AssertionError(f"unexpected model in query(): {name}")

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    def commit(self) -> None:
        return None

    def refresh(self, obj) -> None:  # noqa: ANN001
        return None

    def close(self) -> None:
        return None


class _FakeDataset:
    def __init__(self, *, owner_id: str):
        self.owner_id = owner_id


class _FakeCase:
    def __init__(self, *, case_id: UUID, question: str):
        self.id = case_id
        self.question = question


class _FakeRun:
    def __init__(self, **kwargs):  # noqa: ANN003
        self.id = uuid4()


def test_nightly_ablations_resolves_case_ids_from_bundle_in_stable_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mod = _load_module()

    tenant_id = uuid4()
    dataset_id = uuid4()

    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        (
            "{\n"
            f'  "schema": "mimirq.regression_cases.v1",\n'
            f'  "dataset_id": "{dataset_id}",\n'
            '  "items": [\n'
            '    {"question": "Q2", "reference_sources": []},\n'
            '    {"question": "Q1", "reference_sources": []}\n'
            "  ]\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    case_q1 = _FakeCase(case_id=UUID("00000000-0000-0000-0000-000000000001"), question="Q1")
    case_q2 = _FakeCase(case_id=UUID("00000000-0000-0000-0000-000000000002"), question="Q2")
    fake_db = _FakeDB(dataset=_FakeDataset(owner_id="acct"), cases=[case_q1, case_q2])

    monkeypatch.setattr(mod, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(mod, "_default_ablations", lambda: [{"ablation_key": "baseline", "rag_params": {}}])
    monkeypatch.setattr(mod, "RagasRegressionRun", _FakeRun)

    captured: list[list[UUID]] = []

    def _fake_run_regression_ragas_evaluation(**kwargs):  # noqa: ANN003
        captured.append(list(kwargs.get("case_ids") or []))

    monkeypatch.setattr(mod, "run_regression_ragas_evaluation", _fake_run_regression_ragas_evaluation)

    rc = mod.main(
        [
            "--tenant-id",
            str(tenant_id),
            "--dataset-id",
            str(dataset_id),
            "--execute",
            "--max-cases",
            "50",
            "--cases",
            str(cases_path),
        ]
    )
    assert rc == 0
    assert len(captured) == 1
    assert captured[0] == [case_q2.id, case_q1.id]


def test_nightly_ablations_fails_when_bundle_cases_missing_from_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mod = _load_module()

    tenant_id = uuid4()
    dataset_id = uuid4()

    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        (
            "{\n"
            f'  "schema": "mimirq.regression_cases.v1",\n'
            f'  "dataset_id": "{dataset_id}",\n'
            '  "items": [\n'
            '    {"question": "Q1", "reference_sources": []},\n'
            '    {"question": "MISSING", "reference_sources": []}\n'
            "  ]\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    case_q1 = _FakeCase(case_id=uuid4(), question="Q1")
    fake_db = _FakeDB(dataset=_FakeDataset(owner_id="acct"), cases=[case_q1])

    monkeypatch.setattr(mod, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(mod, "_default_ablations", lambda: [{"ablation_key": "baseline", "rag_params": {}}])
    monkeypatch.setattr(mod, "RagasRegressionRun", _FakeRun)
    monkeypatch.setattr(mod, "run_regression_ragas_evaluation", lambda **kwargs: None)

    rc = mod.main(
        [
            "--tenant-id",
            str(tenant_id),
            "--dataset-id",
            str(dataset_id),
            "--execute",
            "--max-cases",
            "50",
            "--cases",
            str(cases_path),
        ]
    )
    assert rc == 2
