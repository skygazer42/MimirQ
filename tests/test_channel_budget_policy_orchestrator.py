from __future__ import annotations

from typing import Any

import pytest


def test_orchestrator_applies_channel_budget_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)

    captured_updates: list[dict[str, Any]] = []

    class _CapturingRetriever:
        _last_debug_metrics: dict[str, Any] = {}

        def model_copy(self, **kwargs):  # noqa: ANN001, ANN002, ANN003
            captured_updates.append(dict((kwargs or {}).get("update") or {}))
            return self

        def invoke(self, _q):  # noqa: ANN001
            return []

    class _FakeEngine:
        def _annotate_docs_with_role(self, docs, _kind):  # noqa: ANN001
            return docs

        def fuse_docs_rrf(self, docs_by_query, rrf_k=60, meta_prefix="query_expansion"):  # noqa: ANN001, ARG002
            out = []
            for ds in docs_by_query or []:
                out.extend(list(ds or []))
            return out

    monkeypatch.setattr(orch, "hybrid_retriever", _CapturingRetriever(), raising=True)
    monkeypatch.setattr(orch, "get_rag_engine", lambda: _FakeEngine(), raising=True)

    out = orch.run_retrieval(
        {
            "question": "how to tune retrieval budgets",
            "history": [],
            "top_k": 5,
            "retrieval_mode": "hybrid",
            "channel_budget_policy": {
                "schema": "mimirq.channel_budget_policy.v1",
                "fusion_strategy": "budgeted_rrf",
                "profiles": {
                    "hybrid": {
                        "fusion_budgets": {"vector": 2, "bm25": 1, "lexical": 1, "sparse": 1},
                        "fusion_min_scores": {"sparse": 0.01},
                    }
                },
            },
        }
    )

    base_update = next(u for u in captured_updates if "k" in u)
    assert base_update.get("fusion_strategy") == "budgeted_rrf"
    assert dict(base_update.get("fusion_budgets") or {}) == {"vector": 2, "bm25": 1, "lexical": 1, "sparse": 1}
    assert dict(base_update.get("fusion_min_scores") or {}) == {"sparse": 0.01}

    metrics = out.get("metrics") if isinstance(out, dict) else {}
    assert bool((metrics or {}).get("channel_budget_policy_used")) is True
    qd = out.get("query_debug") if isinstance(out, dict) else {}
    cbp = (qd or {}).get("channel_budget_policy") if isinstance(qd, dict) else {}
    assert isinstance(cbp, dict)
    assert cbp.get("selected_profile") == "hybrid"
