from __future__ import annotations

from uuid import UUID, uuid4

import pytest


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

    def delete(self, synchronize_session=False):  # noqa: ANN001
        return 0


class _FakeDB:
    def __init__(self, *, run, cases):
        self._run = run
        self._cases = cases
        self.added = []

    def query(self, model):  # noqa: ANN001
        name = getattr(model, "__name__", str(model))
        if name == "RagasRegressionRun":
            return _FakeQuery(self._run)
        if name == "RagasRegressionCase":
            return _FakeQuery(self._cases)
        if name == "RagasRegressionItem":
            return _FakeQuery(None)
        # Deterministic gate test intentionally avoids DB joins for DBDocument attrs
        # by keeping reference_sources empty in the fake cases.
        raise AssertionError(f"unexpected model in query(): {name}")

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    def commit(self) -> None:
        return None

    def close(self) -> None:
        return None


class _FakeRun:
    def __init__(self):
        self.status = "pending"
        self.started_at = None
        self.finished_at = None
        self.metrics = ["faithfulness_det", "refusal_correctness"]
        self.params = {}
        self.summary = {}
        self.error_message = None


class _FakeCase:
    def __init__(self, *, case_id: UUID, question: str, expected_refusal: bool):
        self.id = case_id
        self.question = question
        self.updated_at = None
        self.dataset_id = None
        self.extra = {"expected_refusal": bool(expected_refusal)}


def test_regression_eval_supports_deterministic_answer_gate_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Ensure the regression runner supports an answer-level deterministic gate mode:
    - no ragas imports needed
    - runs the RAG graph to get answers
    - computes offline metrics (faithfulness_det + refusal_correctness) via item_meta aggregation
    """
    from app.rag.evaluation import ragas as mod

    run = _FakeRun()
    case_ok = _FakeCase(case_id=uuid4(), question="Case: grounded", expected_refusal=False)
    case_refuse = _FakeCase(case_id=uuid4(), question="Case: should refuse", expected_refusal=True)
    fake_db = _FakeDB(run=run, cases=[case_ok, case_refuse])

    monkeypatch.setattr(mod, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(mod.DatasetService, "ensure_member", lambda *args, **kwargs: None)

    dataset_id = uuid4()
    monkeypatch.setattr(mod, "_resolve_case_scope", lambda **kwargs: ([], dataset_id))

    # Keep context deterministic and compatible with the claim-support heuristic.
    monkeypatch.setattr(mod, "_extract_contexts", lambda **kwargs: ["The sky is blue."])

    # Deterministic graph runner stub (no external LLM dependency).
    import app.rag.graph as rag_graph

    def _fake_run_rag_graph(**kwargs):  # noqa: ANN003
        q = str(kwargs.get("question") or "")
        if "refuse" in q:
            return {
                "answer": "Unable to answer due to insufficient evidence.",
                "citations": [],
                "abstain_triggered": True,
                "abstain_reason": "low_evidence",
                "metrics": {},
            }
        return {
            "answer": "The sky is blue.",
            "citations": [],
            "abstain_triggered": False,
            "abstain_reason": None,
            "metrics": {},
        }

    monkeypatch.setattr(rag_graph, "run_rag_graph", _fake_run_rag_graph)

    # If deterministic gate mode accidentally imports ragas, make it fail loudly.
    import builtins

    orig_import = builtins.__import__

    def _blocking_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        if name == "ragas" or str(name).startswith("ragas."):
            raise ImportError("blocked")
        return orig_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _blocking_import)

    mod.run_regression_ragas_evaluation(
        run_id=uuid4(),
        tenant_id=uuid4(),
        account_id="acct",
        case_ids=[case_ok.id, case_refuse.id],
        dataset_id=dataset_id,
        metric_names=["faithfulness_det", "refusal_correctness"],
        skip_empty_contexts=False,
        max_cases=10,
        rag_params={},
    )

    assert run.status == "completed"
    assert (run.params or {}).get("mode") == "deterministic_gate"
    assert run.summary.get("faithfulness_det") == 1.0
    assert run.summary.get("refusal_correctness") == 1.0

