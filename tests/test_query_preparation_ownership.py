import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest


def _request(*, rewrite_enabled=True):
    from app.rag.retrieval.planning.contracts import IndustryQuerySettings, QueryPreparationRequest, RewriteSettings

    return QueryPreparationRequest(
        question="What is it?",
        history_text="We discussed Ragvia.",
        rewrite=RewriteSettings(rewrite_enabled, "kb_followup.v1", 0.0, 400),
        industry=IndustryQuerySettings(False, (), 16, 2000),
        temporal_enabled=False,
    )


class _Models:
    def __init__(self, *, failure=None):
        self.failure = failure
        self.calls = []

    def rewrite(self, *, strategy_id, temperature):
        owner = self

        class Model:
            model_name = "test-model"

            def invoke(self, *, question, history):
                owner.calls.append((question, history, strategy_id, temperature))
                if owner.failure is not None:
                    raise owner.failure
                return '"What is Ragvia?"'

        return Model()


def test_query_preparation_owns_rewrite_result_and_strategy_identity() -> None:
    from app.rag.retrieval.planning.planner import prepare_query

    models = _Models()
    result = prepare_query(_request(), models=models)
    assert result.query == "What is Ragvia?"
    assert result.rewrite.used is True and result.rewrite.failure is None
    assert result.rewrite.model_used == "test-model"
    assert result.rewrite.strategy_id == "kb_followup.v1"
    assert result.rewrite.strategy_hash
    assert len(models.calls) == 1


def test_disabled_or_history_free_rewrite_never_resolves_a_model() -> None:
    from app.rag.retrieval.planning.planner import prepare_query

    class NoModel:
        def rewrite(self, **kwargs):
            pytest.fail("unneeded model resolved")

    disabled = prepare_query(_request(rewrite_enabled=False), models=NoModel())
    no_history = prepare_query(replace(_request(), history_text="(No conversation history)"), models=NoModel())
    assert disabled.query == no_history.query == "What is it?"
    assert disabled.rewrite.strategy_id is None
    assert no_history.rewrite.strategy_id == "kb_followup.v1"


def test_optional_rewrite_failure_preserves_original_error_and_query(monkeypatch) -> None:
    from app.rag.retrieval.planning import planner

    clock = iter((1.0, 1.25))
    monkeypatch.setattr(planner.time, "perf_counter", lambda: next(clock))
    failure = TimeoutError("optional rewrite timed out")
    result = planner.prepare_query(_request(), models=_Models(failure=failure))
    assert result.query == "What is it?"
    assert result.rewrite.failure is failure
    assert result.rewrite.used is False
    assert result.rewrite.elapsed_sec == 0.25


def test_required_model_resolution_failure_is_not_optional_empty_success() -> None:
    from app.rag.retrieval.planning.planner import prepare_query

    failure = ValueError("missing rewrite runtime")

    class MissingModel:
        def rewrite(self, **kwargs):
            raise failure

    with pytest.raises(ValueError) as caught:
        prepare_query(_request(), models=MissingModel())
    assert caught.value is failure


def test_industry_expansion_precedes_temporal_analysis_and_keeps_original_failures(monkeypatch) -> None:
    from app.rag.retrieval.planning import planner as query_planning

    failure = RuntimeError("temporal sidecar failed")

    def temporal(query):
        assert query == "What is Ragvia? industry terms"
        raise failure

    monkeypatch.setattr(
        query_planning,
        "apply_industry_rules_query_expansion",
        lambda query, **kwargs: (query + " industry terms", {"enabled": True, "used": True}),
    )
    monkeypatch.setattr(query_planning, "detect_temporal_intent", temporal)
    result = query_planning.prepare_query(replace(_request(), temporal_enabled=True), models=_Models())
    assert result.query == "What is Ragvia? industry terms"
    assert result.temporal.failure is failure
    assert result.temporal.metadata["detected"] is False


@pytest.mark.parametrize("field", ["query_rewrite_temperature", "query_rewrite_max_chars"])
def test_invalid_rewrite_configuration_fails_at_state_adapter(field) -> None:
    from app.rag.retrieval.stages import preparation

    with pytest.raises((TypeError, ValueError)):
        preparation._build_retrieval_request(
            {"enable_query_rewrite": True, field: "invalid-number"},
            question="What is it?",
            history_text="(No conversation history)",
        )


def test_missing_required_model_is_not_reported_as_a_successful_unchanged_query() -> None:
    from app.rag.retrieval.planning.planner import prepare_query
    from app.rag.runtime.query_models import EngineQueryModels

    with pytest.raises(KeyError, match="default"):
        prepare_query(_request(), models=EngineQueryModels(lambda: SimpleNamespace(models={})))


def test_preparation_executes_without_importing_orchestrator_engine_or_reader() -> None:
    script = """
import importlib.abc
import sys
class NoAdapters(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'app.rag.runtime.engine','app.rag.retrieval.recall.retriever','app.rag.retrieval.orchestrator'}:
            raise AssertionError('Query preparation imports upper adapter: ' + fullname)
sys.meta_path.insert(0, NoAdapters())
from app.rag.retrieval.planning.contracts import IndustryQuerySettings, QueryPreparationRequest, RewriteSettings
from app.rag.retrieval.planning.planner import prepare_query
class Model:
    model_name = 'test-model'
    def invoke(self, *, question, history):
        assert question == 'What is it?' and history == 'Ragvia was discussed.'
        return 'What is Ragvia?'
class Models:
    def rewrite(self, *, strategy_id, temperature):
        return Model()
request = QueryPreparationRequest('What is it?','Ragvia was discussed.',RewriteSettings(True,'kb_followup.v1',0.0,400),IndustryQuerySettings(False,(),16,2000),False)
result = prepare_query(request, models=Models())
assert result.query == 'What is Ragvia?' and result.rewrite.used
assert result.rewrite.failure is None
assert 'app.rag.runtime.engine' not in sys.modules
assert 'app.rag.retrieval.orchestrator' not in sys.modules
assert 'app.rag.retrieval.recall.retriever' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
