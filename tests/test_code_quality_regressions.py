from __future__ import annotations

from app.api.v1.documents import PipelineOptionOverrides, _resolve_pipeline_option_overrides
from app.rag.chunking.strategies.git_commit_log import _extract_commit_header_value
from app.rag.pipelines.langgraph import RagStateBuildOptions, _resolve_rag_state_build_options


def test_extract_commit_header_value_parses_known_prefixes() -> None:
    assert _extract_commit_header_value("Author: Jane Doe <jane@example.com>", prefix="author:") == "Jane Doe <jane@example.com>"
    assert _extract_commit_header_value("Date:   Fri Mar 21 12:34:56 2026 +0800", prefix="date:") == "Fri Mar 21 12:34:56 2026 +0800"
    assert _extract_commit_header_value("Subject: demo", prefix="author:") is None


def test_resolve_pipeline_option_overrides_returns_typed_dataclass() -> None:
    resolved = _resolve_pipeline_option_overrides(
        overrides=PipelineOptionOverrides(chunk_size=256),
        legacy_overrides={"chunk_overlap": 32},
    )

    assert isinstance(resolved, PipelineOptionOverrides)
    assert resolved.chunk_size == 256
    assert resolved.chunk_overlap == 32


def test_resolve_rag_state_build_options_returns_typed_dataclass() -> None:
    resolved = _resolve_rag_state_build_options(
        options=RagStateBuildOptions(question="hello", top_k=5),
        legacy_overrides={"score_threshold": 0.2},
    )

    assert isinstance(resolved, RagStateBuildOptions)
    assert resolved.question == "hello"
    assert resolved.top_k == 5
    assert resolved.score_threshold == 0.2
