
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from langchain_core.documents import Document
from PIL import Image

from app.parsing.enrich.watermark_detector import remove_document_watermark_elements
from app.parsing.models.manifest import SmallModelManifest, SmallModelSpec
from app.parsing.models.runtime import SmallModelRuntime
from app.parsing.parsers.docling_parser import DoclingParser
from app.parsing.preprocess.paddle_doc_preprocess import preprocess_with_paddle_doc
from app.parsing.processors.cross_page_merge import merge_cross_page_markdown_pages
from app.parsing.quality.benchmark import table_cell_f1
from app.parsing.quality.scorer import _detect_preprocess_info
from app.rag.retrieval.orchestration.anchors import _apply_metadata_exact_anchor_doc_ordering
from app.rag.retrieval.plugin_policy import record_retrieval_policy_anchor_binding_scores
from app.rag.workflows.parallelization import ParallelWorkflow


def test_remove_document_watermark_elements_keeps_order_and_counts_reasons() -> None:
    elements = [
        {
            "id": "noise",
            "kind": "text",
            "page": 1,
            "text": "Company Confidential",
            "bbox": {"x0": 100, "x1": 200, "y0": 100, "y1": 130},
        },
        {
            "id": "table",
            "kind": "table",
            "page": 1,
            "text": "Alpha Overlay",
            "bbox": {"x0": 100, "x1": 200, "y0": 110, "y1": 140},
        },
        {
            "id": "repeat-1",
            "kind": "text",
            "page": 1,
            "text": "Alpha Overlay",
            "bbox": {"x0": 100, "x1": 200, "y0": 110, "y1": 140},
        },
        {
            "id": "repeat-2",
            "kind": "text",
            "page": 2,
            "text": "Alpha Overlay",
            "bbox": {"x0": 102, "x1": 202, "y0": 112, "y1": 142},
        },
        {
            "id": "keep",
            "kind": "text",
            "page": 2,
            "text": "Real body text",
            "bbox": {"x0": 10, "x1": 40, "y0": 10, "y1": 260},
        },
    ]

    result = remove_document_watermark_elements(elements, min_pages=2)

    assert result.changed is True
    assert [item["id"] for item in result.elements] == ["table", "keep"]
    assert result.removed_ids == ["noise", "repeat-1", "repeat-2"]
    assert result.pages == [1, 2]
    assert result.reasons == {"pdf_export_noise": 1, "repeated_overlay": 2}


def test_small_model_runtime_resolve_preserves_local_and_download_disabled_paths(tmp_path: Path) -> None:
    onnx_path = tmp_path / "model.onnx"
    onnx_path.write_bytes(b"x" * 2048)
    manifest = SmallModelManifest(
        path=tmp_path / "manifest.yaml",
        tasks={
            "table": {
                "local": SmallModelSpec(
                    task="table",
                    model_id="local",
                    kind="onnx",
                    path=str(onnx_path),
                    max_size_mb=0.001,
                ),
            },
            "ocr": {
                "remote": SmallModelSpec(
                    task="ocr",
                    model_id="remote",
                    kind="hf_transformers",
                    repo_id="demo/repo",
                    path="missing-model",
                ),
            },
        },
        defaults={"table": "local", "ocr": "remote"},
    )
    runtime = SmallModelRuntime(manifest=manifest)

    rejected = runtime.resolve("table")
    disabled = runtime.resolve("ocr", allow_download=False)

    assert rejected.available is False
    assert rejected.reason == "model_too_large_for_cpu"
    assert rejected.path == onnx_path
    assert rejected.size_mb is not None
    assert disabled.available is False
    assert disabled.reason == "hf_download_disabled"
    assert disabled.repo_id == "demo/repo"


def test_docling_parser_parse_converts_tables_without_local_page_images(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_docs = [
        Document(
            page_content="<table><tr><th>Col</th></tr><tr><td>Value</td></tr></table>",
            metadata={"content_type": "table", "doc_type_kwd": "table", "positions": [(0, 1, 2, 3, 4)]},
        ),
        Document(page_content="Body", metadata={"content_type": "text", "doc_type_kwd": "text"}),
    ]
    parser = DoclingParser(extract_images=True, table_mode="markdown")
    monkeypatch.setattr(
        "app.parsing.parsers.docling_parser.BaseAdvancedParser.parse", lambda self, path, **kwargs: list(base_docs)
    )

    parsed = parser.parse(tmp_path / "demo.pdf")

    assert parsed[0].page_content == "| Col |\n| --- |\n| Value |"
    assert parsed[0].metadata["element_kind"] == "table"
    assert parsed[1].page_content == "Body"


def test_preprocess_with_paddle_doc_uses_model_settings_and_writes_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.png"
    output_path = tmp_path / "output" / "preprocessed.png"
    Image.new("RGB", (2, 2), color="white").save(input_path)

    class _FakePipeline:
        def predict(self, path: str) -> list[object]:
            assert path == str(input_path)
            result = SimpleNamespace()
            result.img = {"preprocessed_img": Image.new("RGB", (2, 2), color="black")}
            result.json = {
                "angle": 90,
                "model_settings": {
                    "use_doc_orientation_classify": False,
                    "use_doc_unwarping": True,
                    "use_textline_orientation": True,
                },
            }
            return [result]

    monkeypatch.setattr(
        "app.parsing.preprocess.paddle_doc_preprocess.get_paddle_doc_preprocessor",
        lambda **kwargs: _FakePipeline(),
    )

    changed, note, info = preprocess_with_paddle_doc(
        input_path=input_path,
        output_path=output_path,
        backend="local",
        use_doc_orientation_classify=True,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )

    assert changed is True
    assert note == "paddle_ocr_ok"
    assert output_path.exists()
    assert info["angle"] == 90
    assert info["use_doc_orientation_classify"] is False
    assert info["use_doc_unwarping"] is True
    assert info["use_textline_orientation"] is True


def test_merge_cross_page_markdown_pages_merges_repeated_table_header() -> None:
    pages = [
        "| A | B |\n| --- | --- |\n| 1 | 2 |\n",
        "续表\n| A | B |\n| --- | --- |\n| 3 | 4 |\n",
    ]

    merged, stats = merge_cross_page_markdown_pages(pages)

    assert merged[0] == "| A | B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n"
    assert merged[1] == "\n"
    assert stats == {"tables_merged": 1, "lists_merged": 0, "pages_changed": 2}


def test_merge_cross_page_markdown_pages_merges_ordered_list_continuation() -> None:
    pages = [
        "1. First item\n",
        "2. Second item\n",
    ]

    merged, stats = merge_cross_page_markdown_pages(pages)

    assert merged[0] == "1. First item\n2. Second item\n"
    assert merged[1] == "\n"
    assert stats == {"tables_merged": 0, "lists_merged": 1, "pages_changed": 2}


def test_table_cell_f1_treats_cells_as_multisets() -> None:
    score = table_cell_f1(
        pred_tables=[[["A", "A"], ["B", ""]]],
        gold_tables=[[["A", "B"], ["B", ""]]],
    )

    assert score == pytest.approx(2.0 / 3.0)
    assert table_cell_f1([], []) is None


def test_detect_preprocess_info_collects_orientation_watermarks_and_closes_doc(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _Annot:
        def __init__(self, annot_type: tuple[int, str], subject: str = "") -> None:
            self.type = annot_type
            self.info = {"subject": subject}

    class _Page:
        def __init__(self, rotation: int, annots: list[_Annot]) -> None:
            self.rotation = rotation
            self._annots = annots

        def annots(self) -> list[_Annot]:
            return list(self._annots)

    class _Doc:
        def __init__(self) -> None:
            self.page_count = 3
            self.pages = [
                _Page(90, [_Annot((0, "Stamp"), "Watermark overlay")]),
                _Page(90, []),
                _Page(0, []),
            ]
            self.closed = False

        def load_page(self, index: int) -> _Page:
            return self.pages[index]

        def close(self) -> None:
            self.closed = True

    fake_doc = _Doc()
    fitz_module = ModuleType("fitz")
    fitz_module.open = lambda _path: fake_doc  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fitz", fitz_module)

    info = _detect_preprocess_info(tmp_path / "sample.pdf", sample_pages=2)

    assert info["orientation"] == 90
    assert info["rotation_counts"] == {"90": 2}
    assert info["watermark_annots"] == 1
    assert info["watermark_detected"] is True
    assert fake_doc.closed is True


def test_apply_metadata_exact_anchor_doc_ordering_promotes_exact_match() -> None:
    docs = [
        Document(page_content="generic", metadata={"score": 0.9, "chunk_id": "beta", "question": "Beta topic"}),
        Document(
            page_content="exact",
            metadata={"score": 0.4, "chunk_id": "alpha", "question": "Alpha Desk materials"},
        ),
    ]

    ordered, meta = _apply_metadata_exact_anchor_doc_ordering("Alpha Desk materials", docs)

    assert ordered[0].metadata["chunk_id"] == "alpha"
    assert ordered[0].metadata["score"] == 1.0
    assert ordered[0].metadata["metadata_exact_match_field"] == "question"
    assert meta == {"applied": True, "annotated": 1, "score_promoted": 1, "top_changed": True, "reason": "applied"}


def test_record_retrieval_policy_anchor_binding_scores_penalizes_slot_only_records() -> None:
    policy = {
        "schema": "mimirq.retrieval_policy.v1",
        "anchor_binding": {
            "enabled": True,
            "anchor_fields": ["service_name"],
            "slot_fields": ["section_type"],
            "anchor_match_bonus": 0.3,
            "anchor_slot_match_bonus": 0.2,
            "slot_only_penalty": 0.4,
            "anchor_mismatch_penalty": 0.6,
        },
        "query_expansion_values": [
            {"metadata": "section_type", "value": "materials", "terms": ["materials"]},
        ],
    }
    matching = {"metadata": {"service_name": "Alpha Desk", "section_type": "materials"}, "plugin_ref": "plugin:a"}
    bound_only = {"metadata": {"service_name": "Alpha Desk", "section_type": "fees"}, "plugin_ref": "plugin:a"}
    slot_only = {"metadata": {"service_name": "Beta Desk", "section_type": "materials"}, "plugin_ref": "plugin:a"}

    scores = record_retrieval_policy_anchor_binding_scores(
        [matching, bound_only, slot_only],
        query="Alpha Desk materials",
        plugin_ref_for_record=lambda record: record["plugin_ref"],
        metadata_layers_for_record=lambda record: [record["metadata"]],
        policy_resolver=lambda _plugin_ref: policy,
    )

    assert scores[id(matching)] == pytest.approx(0.5)
    assert scores[id(bound_only)] == pytest.approx(0.3)
    assert scores[id(slot_only)] == pytest.approx(-0.4)


@pytest.mark.asyncio
async def test_parallel_workflow_run_keeps_partial_results_and_original_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "MIDDLEWARE_ENABLED", False, raising=False)
    workflow = ParallelWorkflow()

    async def ok_task(state: dict[str, object]) -> dict[str, object]:
        return {"contexts": [{"chunk_id": "a", "score": 0.8}], "answer": state["query"]}

    async def failing_task(_state: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("boom")

    workflow.add_task("ok", ok_task)
    workflow.add_task("fail", failing_task)

    result = await workflow.run({"query": "hello", "tenant": "demo"})

    assert result.success is True
    assert result.error is None
    assert result.execution_path == ["parallel_start", "ok", "aggregate"]
    assert result.state["answer"] == "hello"
    assert result.state["tenant"] == "demo"
    assert result.state["parallel_tasks"] == ["ok"]
    assert result.state["parallel_errors"] == ["fail: boom"]
    assert result.metadata == {"tasks_completed": 1, "tasks_failed": 1}
