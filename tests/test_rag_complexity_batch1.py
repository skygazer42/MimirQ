from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from PIL import Image

from app.rag.checkpointer.sqlite import SqliteSaver
from app.rag.evaluation.poc_runner.reports.png_renderer import render_dataset_analysis_png
from app.rag.evaluation.replay_capture import sanitize_citations_for_capture
from app.rag.kg.extraction.config import _clean_kg_python_params
from app.rag.kg.extraction.skill_processor import _coerce_str_list
from app.rag.llm.factory import create_llm_client
from app.rag.llm.fallback import FallbackLLMClient
from app.rag.pipeline_plugins import refs as plugin_refs
from app.rag.pipeline_plugins.contracts import DISPLAY_METADATA_KEY, EVALUABLE_METADATA_KEY, INDEXED_METADATA_KEY
from app.rag.pipeline_plugins.golden_drafts import build_golden_draft_bundle_from_chunks
from app.rag.pipeline_plugins.refs import clean_python_plugin_ref
from app.rag.preprocessing.near_dedup import INDEX_VERSION, load_near_dedup_index
from app.rag.preprocessing.paragraph_dedup import drop_duplicate_paragraphs


def _checkpoint_with_id(checkpoint_id: str) -> dict:
    checkpoint = dict(empty_checkpoint())
    checkpoint["id"] = checkpoint_id
    return checkpoint


def test_sqlite_saver_list_respects_namespace_before_filter_limit_and_pending_writes(tmp_path: Path) -> None:
    saver = SqliteSaver(db_path=str(tmp_path / "checkpoints.db"), table_prefix="complexity_batch1")

    base_config = {"configurable": {"thread_id": "thread-1", "checkpoint_ns": "ns-a"}}
    older_config = saver.put(
        base_config,
        _checkpoint_with_id("cp-001"),
        {"kind": "keep", "order": 1},
        {},
    )
    newer_config = saver.put(
        older_config,
        _checkpoint_with_id("cp-002"),
        {"kind": "skip", "order": 2},
        {},
    )
    saver.put_writes(newer_config, [("alpha", {"value": 1}), ("beta", ["x"])], task_id="task-1")

    saver.put(
        {"configurable": {"thread_id": "thread-1", "checkpoint_ns": "ns-b"}},
        _checkpoint_with_id("cp-003"),
        {"kind": "keep", "order": 3},
        {},
    )
    saver.put(
        {"configurable": {"thread_id": "thread-2", "checkpoint_ns": "ns-a"}},
        _checkpoint_with_id("cp-004"),
        {"kind": "keep", "order": 4},
        {},
    )

    listed = list(
        saver.list(
            {"configurable": {"thread_id": "thread-1", "checkpoint_ns": "ns-a"}},
            filter={"kind": "keep"},
            before=newer_config,
            limit=1,
        )
    )

    assert [item.config["configurable"]["checkpoint_id"] for item in listed] == ["cp-001"]
    assert listed[0].metadata["kind"] == "keep"
    assert listed[0].pending_writes == []

    all_items = list(saver.list(None))
    assert {item.config["configurable"]["checkpoint_id"] for item in all_items} == {
        "cp-001",
        "cp-002",
        "cp-003",
        "cp-004",
    }

    with_writes = list(
        saver.list({"configurable": {"thread_id": "thread-1", "checkpoint_ns": "ns-a", "checkpoint_id": "cp-002"}})
    )
    assert with_writes[0].pending_writes == [
        ("task-1", "alpha", {"value": 1}),
        ("task-1", "beta", ["x"]),
    ]


def test_render_dataset_analysis_png_returns_expected_canvas() -> None:
    payload = render_dataset_analysis_png(
        {
            "meta": {"dataset_name": "Demo Dataset", "generated_at": "2026-08-16T12:00:00Z"},
            "metric_cards": [{"key": f"metric_{idx}", "value": idx} for idx in range(5)],
            "feedback_coverage": {"key": "coverage", "value": "87%"},
            "metrics": {"precision": 0.9, "recall": 0.8},
            "counts": {"documents": 4},
            "top_examples": {
                "good": [
                    {"interaction_id": "i-1", "original_query": "How do I restart service A?"},
                ]
            },
            "coverage_heatmap": {
                "rows": [
                    {"filename": "a.md", "retrieval_hit_count": 4, "negative_feedback_count": 1},
                ]
            },
            "umap_scatter": {
                "points": [
                    {"x": 0.1, "y": 0.5, "group": "document", "kind": "document"},
                    {
                        "x": 0.9,
                        "y": 0.2,
                        "group": "out_of_scope_candidate",
                        "kind": "query",
                        "label": "candidate-a",
                    },
                ]
            },
        }
    )

    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    image = Image.open(BytesIO(payload))
    assert image.mode == "RGB"
    assert image.size == (1400, 1360)


def test_sanitize_citations_for_capture_keeps_only_allowlisted_keys_and_limit() -> None:
    citations = [
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "relevance_score": 0.7,
            "chunk_content": "secret",
            "document_name": "private",
        },
        {"chunk_id": "chunk-2", "retrieval_role": "supporting", "unknown": "value"},
        "not-a-dict",
    ]

    assert sanitize_citations_for_capture(citations, max_items=1) == [
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "relevance_score": 0.7,
        }
    ]
    assert sanitize_citations_for_capture(citations, max_items=3) == [
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "relevance_score": 0.7,
        },
        {
            "chunk_id": "chunk-2",
            "retrieval_role": "supporting",
        },
    ]


def test_clean_kg_python_params_trims_keys_and_rejects_non_primitive_values() -> None:
    assert _clean_kg_python_params(
        {
            " answer ": "value",
            "flag": True,
            "blank   ": None,
            " ": "drop-me",
        }
    ) == {
        "answer": "value",
        "flag": True,
        "blank": None,
    }

    with pytest.raises(ValueError, match="kg_python_params values must be JSON primitives"):
        _clean_kg_python_params({"nested": {"bad": "value"}})


def test_coerce_str_list_handles_multiline_lists_scalars_and_caps() -> None:
    assert _coerce_str_list(" one \n\n two \n", max_items=5) == ["one", "two"]
    assert _coerce_str_list([" alpha ", "", 3, None, "beta"], max_items=3) == ["alpha", "3", "beta"]
    assert _coerce_str_list(42, max_items=1) == ["42"]
    assert _coerce_str_list("ignored", max_items=0) == []


@pytest.mark.asyncio
async def test_create_llm_client_builds_unique_fallback_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[tuple[str, object, object]] = []
    http_client = object()
    http_async_client = object()

    def fake_ctor(*, model_config=None, http_client=None, http_async_client=None):
        model_name = str((model_config or {}).get("model") or "")
        created.append((model_name, http_client, http_async_client))
        if model_name == "broken":
            raise RuntimeError("boom")
        return SimpleNamespace(model_name=model_name)

    monkeypatch.setattr("app.rag.llm.factory.OpenAIChatClient", fake_ctor)
    monkeypatch.setattr("app.rag.llm.factory.settings.LLM_FALLBACK_ENABLED", True, raising=False)
    monkeypatch.setattr(
        "app.rag.llm.factory.settings.LLM_FALLBACK_MODELS",
        json.dumps(["primary", "fallback-a", "broken", {"model": "fallback-a"}, {"model": "fallback-b"}]),
        raising=False,
    )

    client = await create_llm_client(
        model_config={"model": "primary"},
        http_client=http_client,
        http_async_client=http_async_client,
    )

    assert isinstance(client, FallbackLLMClient)
    assert [entry.model_name for entry in client._clients] == ["primary", "fallback-a", "fallback-b"]
    assert created == [
        ("primary", http_client, http_async_client),
        ("fallback-a", http_client, http_async_client),
        ("broken", http_client, http_async_client),
        ("fallback-b", http_client, http_async_client),
    ]


def test_build_golden_draft_bundle_from_chunks_preserves_bundle_contract() -> None:
    chunk = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000011"),
        document_id=UUID("00000000-0000-0000-0000-000000000022"),
        chunk_index=3,
        page_number=5,
        start_char=10,
        end_char=40,
        content="Use the restart lever for the Billing service.",
        doc_metadata={
            "service": "Billing",
            "category": "Support",
            "doc_pipeline_key": "doc:billing",
            "pipeline_hash": "hash-1",
            "semantic_keys": ["billing", "restart"],
            DISPLAY_METADATA_KEY: {"audiences": ["Ops", "Ops", "Finance"]},
            EVALUABLE_METADATA_KEY: {"service": "Billing"},
            INDEXED_METADATA_KEY: {"semantic_keys": ["billing", "ops"]},
        },
    )
    duplicate_payload = dict(chunk.__dict__)
    duplicate_payload["id"] = uuid4()
    duplicate_payload["content"] = "A duplicate chunk that should not add another item."
    duplicate_question_chunk = SimpleNamespace(**duplicate_payload)
    bundle = build_golden_draft_bundle_from_chunks(
        dataset_id=UUID("00000000-0000-0000-0000-000000000033"),
        chunks=[chunk, duplicate_question_chunk],
        golden_rules={
            "schema": "mimirq.golden_rules.v1",
            "query_templates": {"default": ["How do I restart {service}?"]},
            "template_selector_fields": ["missing_selector"],
            "expected_metadata": ["service"],
            "answer_key_point_fields": ["audiences"],
            "tag_fields": ["category"],
        },
        plugin_id="golden-plugin",
        plugin_version="1.0.0",
        plugin_ref="plugin:golden-plugin@1.0.0:chunk",
        plugin_package_hash="pkg-123",
        max_items=5,
    )

    assert bundle["schema"]
    assert bundle["dataset_id"] == "00000000-0000-0000-0000-000000000033"
    assert len(bundle["items"]) == 1

    item = bundle["items"][0]
    assert item["question"] == "How do I restart Billing?"
    assert item["expected_answer"] == "Use the restart lever for the Billing service."
    assert item["tags"] == ["plugin:golden-plugin", "golden_draft", "Support"]
    assert item["extra"] == {
        "source": "plugin_golden_draft",
        "plugin_id": "golden-plugin",
        "plugin_version": "1.0.0",
        "plugin_ref": "plugin:golden-plugin@1.0.0:chunk",
        "plugin_package_hash": "pkg-123",
        "expected_metadata": {"service": "Billing"},
        "answer_key_points": ["Ops", "Finance"],
    }
    assert item["reference_sources"] == [
        {
            "document_id": "00000000-0000-0000-0000-000000000022",
            "chunk_id": "00000000-0000-0000-0000-000000000011",
            "chunk_index": 3,
            "page_number": 5,
            "start_char": 10,
            "end_char": 40,
            "doc_pipeline_key": "doc:billing",
            "pipeline_hash": "hash-1",
            "semantic_keys": ["billing", "restart", "ops"],
            "quote": "Use the restart lever for the Billing service.",
        }
    ]


def test_clean_python_plugin_ref_accepts_registered_and_allowed_import_refs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plugin_refs.settings, "PYTHON_PIPELINE_PLUGIN_ALLOW_PREFIXES", "allowed.pkg", raising=False)

    assert clean_python_plugin_ref("plugin:demo-plugin@1.2.3:kg", expected_stage="kg") == "plugin:demo-plugin@1.2.3:kg"
    assert clean_python_plugin_ref("allowed.pkg.module:run", field_name="kg_python_plugin") == "allowed.pkg.module:run"

    with pytest.raises(ValueError, match="custom path message"):
        clean_python_plugin_ref("pkg/module.py", file_path_message="custom path message")


def test_load_near_dedup_index_filters_invalid_rows_and_normalizes_values(tmp_path: Path) -> None:
    path = tmp_path / "near-dedup.json"
    path.write_text(
        json.dumps(
            {
                "version": INDEX_VERSION,
                "buckets": {
                    "band-1": [" ABCD ", "", None, "ef01"],
                    3: ["skip-key"],
                    "band-2": "skip-value",
                },
            }
        ),
        encoding="utf-8",
    )

    assert load_near_dedup_index(path) == {
        "3": ["skip-key"],
        "band-1": ["abcd", "ef01"],
    }

    path.write_text(json.dumps({"version": INDEX_VERSION + 1, "buckets": {"band-1": ["abcd"]}}), encoding="utf-8")
    assert load_near_dedup_index(path) == {}


def test_drop_duplicate_paragraphs_removes_repeated_plain_paragraphs_only() -> None:
    repeated = "This repeated boilerplate paragraph is intentionally long enough to be deduplicated."
    text = "\n\n".join(
        [
            "# Heading stays",
            repeated,
            repeated,
            repeated,
            "| table | row |",
            "```python\nprint('keep code fence')\n```",
        ]
    )

    result = drop_duplicate_paragraphs(text)

    assert repeated not in result.text
    assert "# Heading stays" in result.text
    assert "| table | row |" in result.text
    assert "print('keep code fence')" in result.text
    assert result.paragraphs_total == 6
    assert result.paragraphs_dropped == 3
    assert result.changed is True
