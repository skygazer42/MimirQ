import datetime as dt
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.documents import Document

if not hasattr(dt, "UTC"):
    dt.UTC = dt.timezone.utc

from app.parsing.processors.support import stages as stages_mod
from app.parsing.processors.support.results import ChunkAssetOptions
from app.parsing.processors.support.stages import (
    ChunkAssetStage,
    ChunkingStage,
    InlineAssetStage,
    ParsingStage,
)


class _FakeDB:
    def commit(self) -> None:
        return None

    def refresh(self, _document) -> None:
        return None


class _FakeParsingService:
    INTEGRATED_PIPELINE_STRATEGIES: set[str] = set()

    def __init__(self) -> None:
        self.recorded: list[dict[str, str]] = []

    def _record_processing_metadata(
        self, _db, _tenant_id, _document_id, *, parser_backend: str, chunk_strategy: str
    ) -> None:
        self.recorded.append({"parser_backend": parser_backend, "chunk_strategy": chunk_strategy})


class _FakeAssetService:
    def _upload_inline_images_to_minio(self, **_kwargs):
        return _kwargs["markdown_text"], [], _kwargs["start_index"]

    def _extract_and_upload_image_to_minio(self, _metadata, **_kwargs):
        return None

    def _extract_img_id_from_content(self, _content: str) -> str | None:
        return None


@pytest.mark.asyncio
async def test_parsing_stage_uses_parse_cache_without_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stages_mod.settings, "PARSE_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(stages_mod.settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(stages_mod, "build_remote_parse_cache_key", lambda **_kwargs: "cache-key", raising=True)
    monkeypatch.setattr(
        stages_mod.parse_cache_service,
        "get",
        lambda **_kwargs: (
            SimpleNamespace(
                documents=[{"page_content": "cached body", "metadata": {"source": "parser.pdf"}, "id": "doc-1"}]
            ),
            123,
        ),
        raising=True,
    )
    monkeypatch.setattr(
        stages_mod,
        "run_parser_subprocess",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("subprocess should not run on cache hit")),
        raising=True,
    )
    monkeypatch.setattr(
        stages_mod,
        "compute_document_analytics",
        lambda **_kwargs: SimpleNamespace(to_dict=lambda: {"summary": "ok"}),
        raising=True,
    )

    stage = ParsingStage(_FakeParsingService())
    db_document = SimpleNamespace(
        doc_metadata={"file_sha256": "abc123", "pipeline_hash": "pipe-1"},
        filename="cached.pdf",
    )

    result = await stage.run(
        db=_FakeDB(),
        db_document=db_document,
        file_path=Path("/tmp/cached.pdf"),
        document_id=uuid4(),
        tenant_id=uuid4(),
        dataset_id="dataset-1",
        parser_backend="basic",
        chunk_strategy="separator",
    )

    assert result.documents is not None
    assert result.documents[0].page_content == "cached body"
    assert result.documents[0].metadata["source"] == "cached.pdf"
    assert db_document.doc_metadata["parse_cache"]["hit"] is True
    assert result.resolved_backend == "basic"


def test_inline_asset_stage_prefers_asset_base_dir_and_preserves_derived_elements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(stages_mod.settings, "MINIO_ENABLED", False, raising=False)
    monkeypatch.setattr(stages_mod.settings, "FORMULA_OCR_ENABLED", False, raising=False)
    monkeypatch.setattr(stages_mod.settings, "CHART_TO_DATA_ENABLED", False, raising=False)

    expected_origin = Path("/tmp/assets")

    def _fake_add_image_code_blocks(content: str, *, origin_path: Path):
        assert origin_path == expected_origin
        return (
            f"{content}\n[code]",
            1,
            SimpleNamespace(
                code_elements=[{"kind": "qr"}],
                to_dict=lambda: {"codes": 1},
            ),
        )

    monkeypatch.setattr(stages_mod, "add_image_code_blocks", _fake_add_image_code_blocks, raising=True)

    stage = InlineAssetStage(_FakeAssetService())
    result = stage.run(
        documents=[
            Document(
                page_content="inline body",
                metadata={"asset_base_dir": str(expected_origin), "page": 3},
            )
        ],
        tenant_id=uuid4(),
        dataset_id="dataset-1",
        document_id=uuid4(),
        origin_path=Path("/tmp/original"),
        start_index=2,
    )

    assert result.documents[0].page_content.endswith("[code]")
    assert result.documents[0].metadata["derived_elements"] == [{"kind": "qr", "page": 3, "id": "image_code:3:0"}]
    assert result.image_codes_added == 1
    assert result.next_asset_index == 2


def test_chunking_stage_prefers_plugin_over_built_in_chunker(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    def _fake_apply_plugin(documents, *, plugin_ref: str, params: dict[str, object], context: dict[str, object]):
        observed["documents"] = documents
        observed["plugin_ref"] = plugin_ref
        observed["params"] = params
        observed["context"] = context
        return [Document(page_content="plugin chunk", metadata={"plugin": True})]

    monkeypatch.setattr(stages_mod, "apply_chunk_python_plugin", _fake_apply_plugin, raising=True)
    monkeypatch.setattr(
        stages_mod.chunker_factory,
        "get_chunker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("built-in chunker should not run")),
        raising=True,
    )

    result = ChunkingStage().run(
        documents=[Document(page_content="alpha", metadata={})],
        chunk_strategy="separator",
        chunk_size=200,
        chunk_overlap=20,
        chunk_strategy_params={"shared": "from-strategy", "override": "old"},
        chunk_python_plugin="plugins.chunker",
        chunk_python_params={"override": "new"},
    )

    assert result.chunks[0].metadata == {"plugin": True}
    assert observed["plugin_ref"] == "plugins.chunker"
    assert observed["params"] == {"shared": "from-strategy", "override": "new"}
    assert observed["context"] == {
        "chunk_strategy": "separator",
        "chunk_size": 200,
        "chunk_overlap": 20,
    }


def test_chunking_stage_normalizes_separator_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    class _FakeSeparatorChunker:
        PRESET_SEPARATORS = {"paragraph": "\n\n"}

        def __init__(
            self, *, chunk_size: int, chunk_overlap: int, separator: str, keep_separator: bool, max_chunk_size: int
        ):
            observed["init"] = {
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "separator": separator,
                "keep_separator": keep_separator,
                "max_chunk_size": max_chunk_size,
            }

        def split_documents(self, documents):
            observed["documents"] = documents
            return [Document(page_content="separator chunk", metadata={})]

    monkeypatch.setattr(stages_mod, "SeparatorChunker", _FakeSeparatorChunker, raising=True)

    result = ChunkingStage().run(
        documents=[Document(page_content="alpha\nbeta", metadata={})],
        chunk_strategy="separator",
        chunk_size=100,
        chunk_overlap=10,
        chunk_strategy_params={
            "separator_preset": "custom",
            "separator": "\\n",
            "keep_separator": "off",
            "separator_max_chunk_size": "11",
        },
    )

    assert result.chunks[0].page_content == "separator chunk"
    assert observed["init"] == {
        "chunk_size": 100,
        "chunk_overlap": 10,
        "separator": "\n",
        "keep_separator": False,
        "max_chunk_size": 11,
    }


def test_chunk_asset_stage_emits_redacted_ocr_child_with_sequence_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeImage:
        def close(self) -> None:
            return None

    deps = SimpleNamespace(
        append_image_understanding_text=lambda content, *, caption, ocr_text, code_text: (
            f"{content}\ncaption={caption}\nocr={ocr_text}\ncode={code_text}"
        ),
        decode_image_codes=lambda _img: {"text": "CODE-1", "values": ["CODE-1"], "visual_kind": "diagram"},
        derive_image_caption=lambda content, _meta: f"{content} secret@example.com",
        infer_visual_kind_from_pixels=lambda _img: "photo",
        load_image_for_ocr=lambda _meta, _tenant_id: (_FakeImage(), True),
        ocr_image=lambda _img, _max_chars: "ocr secret@example.com",
        redact_ocr_text=lambda text, **_kwargs: (
            text.replace("secret@example.com", "[MASK]"),
            {"email": 1},
            {"token": 1},
        ),
        score_chunk_quality=lambda _content, *, meta: {
            "schema": "mimirq.chunk_quality.v1",
            "score": 0.9,
            "kind": meta.get("doc_type_kwd"),
        },
    )

    stage = ChunkAssetStage(_FakeAssetService())
    monkeypatch.setattr(stage, "_load_deps", lambda: deps, raising=True)

    document_id = uuid4()
    result = stage.run(
        chunks=[
            Document(page_content="image body", metadata={"doc_type_kwd": "image"}),
            Document(page_content="plain text", metadata={}),
        ],
        tenant_id=uuid4(),
        document_id=document_id,
        options=ChunkAssetOptions(
            dataset_id="dataset-1",
            resolved_backend="mineru",
            resolved_chunk_strategy="separator",
            image_caption_enabled=True,
            image_ocr_enabled=True,
            pii_anonymize=True,
            secrets_redact=True,
        ),
    )

    assert [chunk.metadata["chunk_index"] for chunk in result.chunks] == [0, 1, 2]
    assert [chunk.metadata.get("doc_type_kwd", "") for chunk in result.chunks] == ["image", "ocr", ""]
    assert result.chunks[0].metadata["image_caption"].endswith("[MASK]")
    assert result.chunks[0].metadata["image_ocr_text"] == "ocr [MASK]"
    assert result.chunks[0].metadata["image_ocr_pii_hits"] == {"email": 1}
    assert result.chunks[0].metadata["image_ocr_secrets_hits"] == {"token": 1}
    assert "caption=image body [MASK]" in result.chunks[0].page_content
    assert result.chunks[1].page_content == "ocr [MASK]"
    assert result.chunks[1].metadata["chunk_role"] == "ocr"
    assert result.chunks[1].metadata["image_parent_chunk_index"] == 0
    assert result.chunks[1].metadata["prev_chunk_index"] == 0
    assert result.chunks[1].metadata["next_chunk_index"] == 2
    assert result.chunks[2].metadata["prev_chunk_index"] == 1
    assert result.chunks[2].metadata["parser_backend"] == "mineru"
