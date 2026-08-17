import sys
from types import SimpleNamespace
from typing import Any

from app.rag.pipelines import langgraph


def test_build_rag_state_does_not_deepcopy_runtime_database_dependency(monkeypatch) -> None:
    runtime_db = SimpleNamespace(module=sys)
    seen: list[object] = []

    def fake_prompt_fields(**kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs["db"])
        return {}

    def fake_metadata_filter(**kwargs: Any) -> dict[str, Any] | None:
        seen.append(kwargs["db"])
        return kwargs["metadata_filter"]

    monkeypatch.setattr(langgraph, "_resolve_prompt_template_fields", fake_prompt_fields)
    monkeypatch.setattr(langgraph, "_apply_active_pipeline_metadata_filter", fake_metadata_filter)

    state = langgraph.build_rag_state(
        options=langgraph.RagStateBuildOptions(
            question="What is the launch code?",
            db=runtime_db,
        )
    )

    assert seen == [runtime_db, runtime_db]
    assert state["question"] == "What is the launch code?"
    assert "db" not in state
