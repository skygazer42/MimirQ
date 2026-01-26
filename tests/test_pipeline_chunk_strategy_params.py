import pytest
from pydantic import ValidationError
from langchain_core.documents import Document

from app.api.schemas.document import DocumentPipelineOptions
from app.services.pipeline_config import parse_pipeline_from_metadata
from app.parsing.processors.processor import _merge_small_chunks_by_min_chars


def test_document_pipeline_options_validates_chunk_strategy_params_primitives():
    opts = DocumentPipelineOptions(
        chunk_strategy_params={
            "child_ratio": 0.5,
            "min_child_size": 200,
            "keep_separator": True,
            "separator": "\\n\\n",
        }
    )
    assert opts.chunk_strategy_params["child_ratio"] == 0.5
    assert opts.chunk_strategy_params["min_child_size"] == 200


def test_document_pipeline_options_rejects_nested_chunk_strategy_params():
    with pytest.raises(ValidationError):
        DocumentPipelineOptions(chunk_strategy_params={"bad": {"nested": True}})


def test_parse_pipeline_from_metadata_sanitizes_chunk_strategy_params():
    opts = parse_pipeline_from_metadata(
        {
            "pipeline": {
                "chunk_strategy_params": {
                    "ok": 1,
                    "drop": {"nested": True},
                }
            }
        }
    )
    assert opts.chunk_strategy_params == {"ok": 1}


def test_merge_small_chunks_by_min_chars_merges_with_neighbors():
    docs = [Document(page_content="aa bb cc", metadata={"page_index": 1})]
    chunks = [
        Document(
            page_content="aa",
            metadata={
                "page_index": 1,
                "start_char_base": 0,
                "start_char_local": 0,
                "end_char_local": 2,
                "start_char": 0,
                "end_char": 2,
            },
        ),
        Document(
            page_content=" bb",
            metadata={
                "page_index": 1,
                "start_char_base": 0,
                "start_char_local": 2,
                "end_char_local": 5,
                "start_char": 2,
                "end_char": 5,
            },
        ),
        Document(
            page_content=" cc",
            metadata={
                "page_index": 1,
                "start_char_base": 0,
                "start_char_local": 5,
                "end_char_local": 8,
                "start_char": 5,
                "end_char": 8,
            },
        ),
    ]

    out = _merge_small_chunks_by_min_chars(documents=docs, chunks=chunks, min_chars=3)
    assert len(out) == 1
    assert out[0].page_content == "aa bb cc"
    assert out[0].metadata.get("merged_small_chunks") == 2

