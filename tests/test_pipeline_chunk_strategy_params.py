import pytest
from langchain_core.documents import Document
from pydantic import ValidationError

from app.api.schemas.document import DocumentPipelineOptions
from app.parsing.processors.processor import _merge_small_chunks_by_min_chars, _truncate_chunks_for_limit
from app.services.pipeline_config import (
    build_pipeline_metadata,
    parse_pipeline_from_metadata,
    resolve_pipeline_effective,
)
from app.types.pipeline import PipelineOptions

LEGACY_IMPORT_GOVERNANCE_REF = "tests.fixtures.python_pipeline_import_plugin:govern_documents"
LEGACY_IMPORT_CHUNK_REF = "tests.fixtures.python_pipeline_import_plugin:chunk_documents"


def test_document_pipeline_options_validates_chunk_strategy_params_primitives():
    opts = DocumentPipelineOptions(
        chunk_strategy_params={
            "child_ratio": 0.5,
            "min_child_size": 200,
            "keep_separator": True,
            "separator": "\\n\\n",
        }
    )
    assert opts.chunk_strategy_params["child_ratio"] == pytest.approx(0.5)
    assert opts.chunk_strategy_params["min_child_size"] == 200


def test_document_pipeline_options_validates_kg_python_params_primitives():
    opts = DocumentPipelineOptions(
        kg_python_params={
            "profile": "demo",
            "max_events": 20,
            "strict": True,
        }
    )

    assert opts.kg_python_params == {"profile": "demo", "max_events": 20, "strict": True}


def test_document_pipeline_options_rejects_nested_chunk_strategy_params():
    with pytest.raises(ValidationError):
        DocumentPipelineOptions(chunk_strategy_params={"bad": {"nested": True}})


def test_document_pipeline_options_rejects_unknown_business_keys():
    with pytest.raises(ValidationError, match="business_only_window_chars"):
        DocumentPipelineOptions(business_only_window_chars=1500)


def test_document_pipeline_options_openapi_contract_is_closed():
    schema = DocumentPipelineOptions.model_json_schema()

    assert schema["additionalProperties"] is False


def test_document_pipeline_options_rejects_nested_kg_python_params():
    with pytest.raises(ValidationError, match="kg_python_params values must be JSON primitives"):
        DocumentPipelineOptions(kg_python_params={"business_profile": {"mode": "nested"}})


def test_document_pipeline_options_rejects_cross_stage_registered_plugin_refs():
    with pytest.raises(ValidationError, match="governance_python_plugin registered ref must target the governance stage"):
        DocumentPipelineOptions(governance_python_plugin="plugin:demo-service@1.0.0:chunk")

    with pytest.raises(ValidationError, match="chunk_python_plugin registered ref must target the chunk stage"):
        DocumentPipelineOptions(chunk_python_plugin="plugin:demo-service@1.0.0:governance")

    with pytest.raises(ValidationError, match="kg_python_plugin registered ref must target the kg stage"):
        DocumentPipelineOptions(kg_python_plugin="plugin:demo-service@1.0.0:chunk")


def test_document_pipeline_options_rejects_import_path_named_plugin_by_default():
    with pytest.raises(ValidationError, match="python plugin import refs are disabled"):
        DocumentPipelineOptions(governance_python_plugin=LEGACY_IMPORT_GOVERNANCE_REF)


def test_document_pipeline_options_allows_import_path_named_plugin_when_prefix_configured(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "PYTHON_PIPELINE_PLUGIN_ALLOW_PREFIXES", "tests.fixtures.", raising=False)

    opts = DocumentPipelineOptions(
        governance_python_plugin=LEGACY_IMPORT_GOVERNANCE_REF,
        chunk_python_plugin=LEGACY_IMPORT_CHUNK_REF,
    )

    assert opts.governance_python_plugin == LEGACY_IMPORT_GOVERNANCE_REF
    assert opts.chunk_python_plugin == LEGACY_IMPORT_CHUNK_REF


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


def test_parse_pipeline_from_metadata_sanitizes_kg_python_params():
    opts = parse_pipeline_from_metadata(
        {
            "pipeline": {
                "kg_python_plugin": "plugin:demo-service@1.0.0:kg",
                "kg_python_params": {
                    "profile": "demo",
                    "drop": {"nested": True},
                },
            }
        }
    )

    assert opts.kg_python_plugin == "plugin:demo-service@1.0.0:kg"
    assert opts.kg_python_params == {"profile": "demo"}


def test_build_pipeline_metadata_roundtrips_kg_python_params():
    pipeline = DocumentPipelineOptions(
        kg_python_plugin="plugin:demo-service@1.0.0:kg",
        kg_python_params={"profile": "demo"},
    )
    opts = PipelineOptions(**pipeline.model_dump(exclude_none=True))

    meta = build_pipeline_metadata(opts)

    assert meta == {
        "kg_python_plugin": "plugin:demo-service@1.0.0:kg",
        "kg_python_params": {"profile": "demo"},
    }


def test_parse_pipeline_from_metadata_drops_cross_stage_registered_plugin_refs():
    opts = parse_pipeline_from_metadata(
        {
            "pipeline": {
                "governance": {
                    "python_plugin": "plugin:demo-service@1.0.0:chunk",
                },
                "chunk_python_plugin": "plugin:demo-service@1.0.0:governance",
                "kg_python_plugin": "plugin:demo-service@1.0.0:chunk",
            }
        }
    )

    assert opts.governance_python_plugin is None
    assert opts.chunk_python_plugin is None
    assert opts.kg_python_plugin is None


def test_resolve_pipeline_effective_drops_cross_stage_registered_plugin_refs_from_internal_options():
    opts = PipelineOptions(
        governance_python_plugin="plugin:demo-service@1.0.0:chunk",
        chunk_python_plugin="plugin:demo-service@1.0.0:governance",
        kg_python_plugin="plugin:demo-service@1.0.0:chunk",
    )

    effective = resolve_pipeline_effective(request_overrides=opts)

    assert effective.governance_python_plugin == ""
    assert effective.chunk_python_plugin == ""
    assert effective.kg_python_plugin == ""


def test_parse_pipeline_from_metadata_drops_import_path_named_plugin_by_default():
    opts = parse_pipeline_from_metadata(
        {
            "pipeline": {
                "governance": {
                    "python_plugin": LEGACY_IMPORT_GOVERNANCE_REF,
                },
                "chunk_python_plugin": LEGACY_IMPORT_CHUNK_REF,
            }
        }
    )

    assert opts.governance_python_plugin is None
    assert opts.chunk_python_plugin is None


def test_parse_pipeline_from_metadata_allows_import_path_named_plugin_when_prefix_configured(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "PYTHON_PIPELINE_PLUGIN_ALLOW_PREFIXES", "tests.fixtures.", raising=False)

    opts = parse_pipeline_from_metadata(
        {
            "pipeline": {
                "governance": {
                    "python_plugin": LEGACY_IMPORT_GOVERNANCE_REF,
                },
                "chunk_python_plugin": LEGACY_IMPORT_CHUNK_REF,
            }
        }
    )

    assert opts.governance_python_plugin == LEGACY_IMPORT_GOVERNANCE_REF
    assert opts.chunk_python_plugin == LEGACY_IMPORT_CHUNK_REF


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


def test_merge_small_chunks_by_min_chars_preserves_record_identity_boundaries():
    docs = [Document(page_content="aabbcc", metadata={"page_index": 1})]

    def chunk(text: str, start: int, end: int, record_key: str) -> Document:
        return Document(
            page_content=text,
            metadata={
                "page_index": 1,
                "start_char_base": 0,
                "start_char_local": start,
                "end_char_local": end,
                "start_char": start,
                "end_char": end,
                "_record_identity": {
                    "schema": "mimirq.record_identity.v1",
                    "key": record_key,
                    "fields": {"source_record_id": record_key},
                },
            },
        )

    chunks = [
        chunk("aa", 0, 2, "service:001"),
        chunk("bb", 2, 4, "service:002"),
        chunk("cc", 4, 6, "service:002"),
    ]

    out = _merge_small_chunks_by_min_chars(documents=docs, chunks=chunks, min_chars=3)

    assert [item.page_content for item in out] == ["aa", "bbcc"]
    assert out[0].metadata["_record_identity"]["key"] == "service:001"
    assert out[1].metadata["_record_identity"]["key"] == "service:002"


def test_merge_small_chunks_invalidates_stale_content_derived_metadata():
    docs = [Document(page_content="aa bb", metadata={"page_index": 1})]
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
                "content_hash": "hash-for-aa",
                "content_hash_algo": "sha256",
                "content_len": 2,
                "simhash64": "simhash-for-aa",
                "simhash_algo": "simhash64_sha1",
                "_retrieval_text": "索引文本：aa",
                "_retrieval_display_content": "aa",
                "chunk_quality": {"noise": 0.1},
                "chunk_semantic_role": "definition",
                "chunk_type": "short_text",
                "structure": {"kind": "sentence"},
                "_record_identity": {
                    "schema": "mimirq.record_identity.v1",
                    "key": "service:001",
                    "fields": {"source_record_id": "service:001"},
                },
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
                "_retrieval_text": "索引文本：bb",
                "_record_identity": {
                    "schema": "mimirq.record_identity.v1",
                    "key": "service:001",
                    "fields": {"source_record_id": "service:001"},
                },
            },
        ),
    ]

    out = _merge_small_chunks_by_min_chars(documents=docs, chunks=chunks, min_chars=3)
    meta = out[0].metadata

    assert out[0].page_content == "aa bb"
    for key in (
        "content_hash",
        "content_hash_algo",
        "content_len",
        "simhash64",
        "simhash_algo",
        "chunk_quality",
        "chunk_semantic_role",
        "chunk_type",
        "structure",
    ):
        assert key not in meta
    assert meta["_retrieval_text"] == "索引文本：aa\n\n索引文本：bb"
    assert meta["_retrieval_display_content"] == "aa bb"
    assert meta["_record_identity"]["key"] == "service:001"
    assert meta["merged_small_chunks"] == 1


def test_truncate_chunks_for_limit_preserves_record_identity_chunks():
    def chunk(record_key: str) -> Document:
        return Document(
            page_content=f"事项 {record_key}",
            metadata={
                "_record_identity": {
                    "schema": "mimirq.record_identity.v1",
                    "key": record_key,
                    "fields": {"source_record_id": record_key},
                }
            },
        )

    chunks = [chunk("service:001"), chunk("service:002"), chunk("service:003")]
    out, info = _truncate_chunks_for_limit(chunks, max_chunks=1, strategy="head")

    assert out == chunks
    assert info["strategy"] == "record_identity_preserved"
    assert info["truncation_skipped"] is True
