
import json
import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.documents import Document

import app.api.v1.scim as scim
import app.parsing.parsers.html_parser as html_parser_module
import app.parsing.utils.artifact_normalizer as artifact_normalizer_module
import app.rag.retrieval.sparse as sparse_module
from app.api.v1 import document_manual as manual_module
from app.parsing.parsers.html_parser import HtmlParser
from app.parsing.quality.reading_order import score_reading_order
from app.parsing.utils.artifact_normalizer import normalize_extracted_artifacts
from app.parsing.utils.document_elements import normalize_document_elements
from app.rag.chunking.strategies.qa_markdown import QAMarkdownChunker
from app.rag.chunking.strategies.qa_pairs import QAPairsChunker
from app.rag.chunking.strategies.timeline_events import TimelineEventsChunker


def _summarize_chunks(chunker, text: str) -> list[tuple[str, dict]]:
    docs = chunker.split_documents([Document(page_content=text, metadata={"source": "fixture"})])
    return [
        (
            doc.page_content,
            {key: value for key, value in doc.metadata.items() if key != "source"},
        )
        for doc in docs
    ]


def _tagged_block(text: str, *, page: int, left: int, right: int, top: int, bottom: int) -> str:
    return f"{text}\n@@{page}\t{left}\t{right}\t{top}\t{bottom}##\n"


def test_scim_patch_group_membership_characterizes_add_remove_audit_and_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    group_id = uuid4()
    captured: dict[str, object] = {}

    class _FakeDB:
        def __init__(self) -> None:
            self.commit_calls = 0

        def commit(self) -> None:
            self.commit_calls += 1

    def fake_add_members(_db, *, tenant_id, group_id, member_ids):
        captured["add"] = (tenant_id, group_id, list(member_ids))
        return len(member_ids)

    def fake_remove_members(_db, *, tenant_id, group_id, member_ids):
        captured["remove"] = (tenant_id, group_id, list(member_ids))
        return len(member_ids)

    def fake_audit_log_event(_db, **kwargs):
        captured["audit"] = kwargs

    monkeypatch.setattr(scim.settings, "SCIM_PATCH_GROUP_MEMBERSHIP_ENABLED", True, raising=False)
    monkeypatch.setattr(scim.TenantGroupService, "add_members", fake_add_members)
    monkeypatch.setattr(scim.TenantGroupService, "remove_members", fake_remove_members)
    monkeypatch.setattr(
        scim.TenantGroupService,
        "get_group",
        lambda _db, *, tenant_id, group_id: SimpleNamespace(id=group_id, tenant_id=tenant_id),
    )
    monkeypatch.setattr(
        scim.TenantGroupService,
        "list_members",
        lambda _db, *, tenant_id, group_id, skip, limit: (
            2,
            [SimpleNamespace(user_id="alice"), SimpleNamespace(user_id="bob")],
        ),
    )
    monkeypatch.setattr(scim, "audit_log_event", fake_audit_log_event)
    monkeypatch.setattr(
        scim,
        "_scim_group",
        lambda group, *, members, include_members=False: {
            "id": str(group.id),
            "include_members": include_members,
            "members": list(members or []),
        },
    )

    response = scim.patch_group_membership(
        group_id,
        {
            "schemas": [scim._URN_PATCH_OP],
            "Operations": [
                {
                    "op": "add",
                    "value": [
                        {"value": "alice"},
                        {"value": "alice"},
                        {"value": "bob"},
                    ],
                },
                {
                    "op": "remove",
                    "path": "members",
                    "value": {"members": [{"value": "carol"}, {"value": "carol"}]},
                },
                {
                    "op": "remove",
                    "path": 'members[value eq "dan"]',
                },
            ],
        },
        tenant_id=tenant_id,
        actor_id="system:scim",
        db=_FakeDB(),
    )

    assert response.status_code == 200
    assert json.loads(response.body) == {
        "id": str(group_id),
        "include_members": True,
        "members": ["alice", "bob"],
    }
    assert captured["add"] == (tenant_id, group_id, ["alice", "bob"])
    assert captured["remove"] == (tenant_id, group_id, ["carol", "dan"])
    assert captured["audit"] == {
        "tenant_id": tenant_id,
        "actor_id": "system:scim",
        "action": "scim.group.members.patch",
        "resource_type": "tenant_group",
        "resource_id": str(group_id),
        "details": {
            "member_add_requested": 2,
            "member_remove_requested": 2,
            "member_add_updated": 2,
            "member_remove_updated": 2,
        },
    }


def test_html_parser_characterizes_xpath_priority_and_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        html_parser_module,
        "read_text_file",
        lambda _path: SimpleNamespace(
            text="<html><title>Doc</title><main>Readable</main></html>",
            encoding="utf-8",
            confidence=0.99,
            had_bom=False,
        ),
    )
    monkeypatch.setattr(
        html_parser_module,
        "_get_readability",
        lambda: SimpleNamespace(
            Document=lambda _html: SimpleNamespace(
                short_title=lambda: "Readable title",
                title=lambda: "Fallback title",
                summary=lambda: "<article>Readable body</article>",
            )
        ),
    )
    monkeypatch.setattr(
        html_parser_module,
        "extract_text_from_html",
        lambda _html, xpath: SimpleNamespace(text="XPath body", matched_nodes=2, xpath_error=f"used:{xpath}"),
    )

    class _UnexpectedHTMLText:
        @staticmethod
        def extract_text(*_args, **_kwargs):
            raise AssertionError("html_text fallback should not run when XPath returns text")

    monkeypatch.setattr(html_parser_module, "_get_html_text", lambda: _UnexpectedHTMLText())

    document = HtmlParser().parse(Path("sample.html"), html_xpath="//main")[0]

    assert document.page_content == "XPath body"
    assert document.metadata == {
        "source": "sample.html",
        "file_type": "html",
        "encoding": "utf-8",
        "encoding_confidence": 0.99,
        "encoding_had_bom": False,
        "title": "Readable title",
        "html_xpath": "//main",
        "html_xpath_matches": 2,
        "html_xpath_error": "used://main",
    }


def test_score_reading_order_characterizes_two_column_pages_after_block_capping() -> None:
    markdown = "".join(
        [
            _tagged_block("L1", page=1, left=0, right=40, top=0, bottom=10),
            _tagged_block("R1", page=1, left=60, right=100, top=0, bottom=10),
            _tagged_block("L2", page=1, left=0, right=40, top=20, bottom=30),
            _tagged_block("R2", page=1, left=60, right=100, top=20, bottom=30),
            _tagged_block("L3", page=1, left=0, right=40, top=40, bottom=50),
            _tagged_block("R3", page=1, left=60, right=100, top=40, bottom=50),
        ]
    )

    assert score_reading_order(markdown, max_blocks=4, min_blocks=2) == {
        "schema": "mimirq.reading_order_score.v1",
        "method": "position_tags",
        "score": 0.8333,
        "nid": 0.1667,
        "blocks": 4,
        "tag_count": 6,
        "pages": [1],
        "column_pages": 1,
        "warnings": [],
    }


def test_normalize_document_elements_characterizes_markdown_and_derived_image_outputs() -> None:
    elements = normalize_document_elements(
        [
            Document(
                page_content="See ![Chart](plots/chart.png)",
                metadata={
                    "element_kind": "paragraph",
                    "page": 1,
                    "position_tagged_markdown": "![Chart](plots/chart.png)\n@@1\t10\t40\t50\t90##\n",
                },
            ),
            Document(
                page_content="See ![QR code](qr.png)",
                metadata={
                    "element_kind": "paragraph",
                    "page": 2,
                    "derived_elements": [
                        {
                            "element_kind": "image",
                            "attributes": {
                                "image_code_text": "SCAN-ME",
                                "source_backend": "ocr",
                                "source_element_id": "src-1",
                            },
                            "caption": "QR code badge",
                            "score": "0.7",
                        }
                    ],
                },
            ),
        ]
    )

    assert elements == [
        {
            "id": "paragraph:1:0",
            "kind": "paragraph",
            "page": 1,
            "pages": None,
            "visual_kind": None,
            "text": "See ![Chart](plots/chart.png)",
            "bbox": None,
            "confidence": None,
            "source_backend": None,
            "source_element_id": None,
            "attributes": None,
        },
        {
            "id": "paragraph:1:0:image:0",
            "kind": "image",
            "page": 1,
            "pages": None,
            "visual_kind": "chart",
            "text": "Chart",
            "bbox": {"x0": 10, "x1": 40, "y0": 50, "y1": 90},
            "confidence": None,
            "source_backend": None,
            "source_element_id": None,
            "attributes": {
                "src": "plots/chart.png",
                "alt": "Chart",
                "source_content_type": "markdown_image",
                "visual_kind": "chart",
            },
        },
        {
            "id": "paragraph:2:1",
            "kind": "paragraph",
            "page": 2,
            "pages": None,
            "visual_kind": None,
            "text": "See ![QR code](qr.png)",
            "bbox": None,
            "confidence": None,
            "source_backend": None,
            "source_element_id": None,
            "attributes": None,
        },
        {
            "id": "paragraph:2:1:derived:0",
            "kind": "image",
            "page": 2,
            "pages": None,
            "visual_kind": "qr",
            "text": "SCAN-ME",
            "bbox": None,
            "confidence": 0.7,
            "source_backend": "ocr",
            "source_element_id": "src-1",
            "attributes": {
                "image_code_text": "SCAN-ME",
                "source_backend": "ocr",
                "source_element_id": "src-1",
                "caption": "QR code badge",
                "score": "0.7",
                "visual_kind": "qr",
            },
        },
    ]


def test_splade_sparse_encoder_characterizes_special_token_zeroing_and_score_thresholds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    torch = pytest.importorskip("torch")
    encoder = sparse_module.SpladeSparseEncoder(
        model_name="demo",
        batch_size=4,
        max_length=8,
        top_k=3,
        min_weight=0.2,
    )

    class _FakeTokenizer:
        all_special_ids = [0]

        def __call__(self, _texts, **_kwargs):
            return {
                "attention_mask": torch.tensor(
                    [
                        [1, 1, 1],
                        [1, 1, 0],
                    ],
                    dtype=torch.int64,
                )
            }

        @staticmethod
        def convert_ids_to_tokens(ids: list[int]) -> list[str]:
            mapping = {
                0: "[PAD]",
                1: "alpha",
                2: "beta",
                3: "gamma",
                4: "delta",
            }
            return [mapping[idx] for idx in ids]

    class _FakeModel:
        @staticmethod
        def __call__(**_enc):
            return SimpleNamespace(
                logits=torch.tensor(
                    [
                        [
                            [0.0, 2.0, -1.0, 0.0, 0.0],
                            [1.0, 0.5, 1.5, 0.0, 0.0],
                            [0.0, 0.0, 0.0, 0.0, 0.1],
                        ],
                        [
                            [0.0, 0.0, 0.0, 3.0, 0.0],
                            [0.0, 0.0, 0.1, 0.0, 0.0],
                            [5.0, 5.0, 5.0, 5.0, 5.0],
                        ],
                    ],
                    dtype=torch.float32,
                )
            )

    encoder._tokenizer = _FakeTokenizer()
    encoder._model = _FakeModel()
    encoder._torch_device = "cpu"
    monkeypatch.setattr(encoder, "_ensure_loaded", lambda: None)

    vectors = encoder.encode_batch(["first", "second"])

    assert vectors[0].weights == pytest.approx(
        {
            "alpha": 1.0986123,
            "beta": 0.9162907,
        },
        rel=1e-5,
    )
    assert vectors[1].weights == pytest.approx({"gamma": 1.3862944}, rel=1e-5)


def test_index_manual_document_chunks_characterizes_metadata_merging_and_image_tracking(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    document_id = uuid4()
    chunk_ids = [uuid4(), uuid4()]
    captured: dict[str, object] = {}

    class _FakeDB:
        def __init__(self) -> None:
            self.commit_calls = 0
            self.refresh_calls = 0

        def commit(self) -> None:
            self.commit_calls += 1

        def refresh(self, _obj: object) -> None:
            self.refresh_calls += 1

    class _FakeIndexer:
        def __init__(self, db) -> None:
            self.db = db

        def upsert(self, **kwargs):
            captured["upsert"] = kwargs
            return SimpleNamespace(
                chunk_result=SimpleNamespace(
                    chunk_ids=chunk_ids,
                    db_chunks=["db-chunk-1", "db-chunk-2"],
                    total_characters=123,
                )
            )

    def fake_rewrite(content: str, **kwargs):
        start_index = int(kwargs["start_index"])
        if "prebound" in content:
            return content.replace("prebound", "uploaded-1"), ["uploaded-1"], start_index + 1
        return f"{content} [rewritten]", ["uploaded-2", "uploaded-3"], start_index + 2

    monkeypatch.setattr(manual_module.settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(manual_module.settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(manual_module, "Indexer", _FakeIndexer)

    docs_mod = SimpleNamespace(
        _to_pipeline_options=lambda pipeline: {"requested": pipeline},
        resolve_pipeline_effective=lambda **_kwargs: SimpleNamespace(kg_enabled=False),
        build_indexing_options=lambda _pipeline_effective: {"mode": "manual"},
        MINIO_IMAGE_REF_RE=re.compile(r"/image-url/([^)\"]+)"),
        _rewrite_preview_images_to_minio=fake_rewrite,
        logger=SimpleNamespace(debug=lambda *_args, **_kwargs: None),
    )
    request = SimpleNamespace(
        filename="manual.md",
        file_type="MD",
        pipeline=None,
        chunks=[
            SimpleNamespace(
                content="![stored](/api/v1/documents/image-url/prebound)",
                page_number=3,
                start_char=0,
                end_char=20,
                metadata={"section": "intro"},
            ),
            SimpleNamespace(
                content="Second chunk",
                page_number=4,
                start_char=21,
                end_char=33,
                metadata={"section": "detail"},
            ),
        ],
    )
    db_document = SimpleNamespace(
        id=document_id,
        doc_metadata={
            "pipeline_hash": "pipe-123",
            "active_pipeline_hash": "old-pipe",
            "active_pipeline_ready": False,
            "img_ids": ["existing"],
        },
        status="queued",
        processing_attempts=0,
        processing_progress=0,
        current_stage=None,
        failed_stage="stale",
        error_code="stale",
        error_message="stale",
    )

    manual_module._index_manual_document_chunks(
        db=_FakeDB(),
        docs_mod=docs_mod,
        request=request,
        tenant_id=tenant_id,
        account_id="acct-1",
        dataset=SimpleNamespace(id=dataset_id, dataset_metadata={}),
        db_document=db_document,
    )

    upsert_kwargs = captured["upsert"]
    records = upsert_kwargs["records"]

    assert len(records) == 2
    assert records[0].content == "![stored](/api/v1/documents/image-url/uploaded-1)"
    assert records[0].metadata["img_id"] == "prebound"
    assert records[0].metadata["img_ids"] == ["uploaded-1"]
    assert records[0].metadata["image_count"] == 1
    assert records[0].metadata["doc_pipeline_key"] == f"{document_id}:pipe-123"
    assert records[1].content == "Second chunk [rewritten]"
    assert records[1].metadata["img_id"] == "uploaded-2"
    assert records[1].metadata["img_ids"] == ["uploaded-2", "uploaded-3"]
    assert records[1].metadata["image_count"] == 2

    assert db_document.status == "completed"
    assert db_document.processing_progress == 100
    assert db_document.current_stage == "completed"
    assert db_document.chunk_count == 2
    assert db_document.total_characters == 123
    assert db_document.processed_at is not None
    assert db_document.doc_metadata["active_pipeline_hash"] == "pipe-123"
    assert db_document.doc_metadata["active_pipeline_ready"] is True
    assert db_document.doc_metadata["img_ids"] == ["existing", "uploaded-1", "uploaded-2", "uploaded-3"]
    assert db_document.doc_metadata["image_count"] == 4


def test_normalize_extracted_artifacts_characterizes_copy_fallback_and_ref_rewriting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "extract"
    assets_dir = root / "nested"
    images_dir = root / "images"
    assets_dir.mkdir(parents=True)
    images_dir.mkdir(parents=True)

    markdown = root / "page.md"
    markdown.write_text(
        '![Alt](nested/photo.PNG)\n<img src="photo.PNG" alt="Alt">\n',
        encoding="utf-8",
    )
    (assets_dir / "photo.PNG").write_bytes(b"raw-image")
    (images_dir / "keep.png").write_bytes(b"already-normalized")

    monkeypatch.setattr(
        artifact_normalizer_module.shutil,
        "move",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("cross-device")),
    )

    result = normalize_extracted_artifacts(root)

    assert result["markdown_file"] == root / "result.md"
    assert result["image_dir"] == images_dir
    assert result["image_count"] == 1
    assert result["mapping"] == {
        "nested/photo.PNG": "images/image_001.png",
        "photo.PNG": "images/image_001.png",
    }
    assert (images_dir / "image_001.png").read_bytes() == b"raw-image"
    assert (root / "result.md").read_text(encoding="utf-8") == (
        '![Alt](images/image_001.png)\n<img src="images/image_001.png" alt="Alt">\n'
    )


def test_qa_markdown_chunker_characterizes_pair_overlap_offsets_and_previews() -> None:
    text = (
        "- **Q:** What is alpha?\n"
        "- **A:** First answer.\n"
        "- **Q:** What is beta?\n"
        "- **A:** Second answer.\n"
        "- **Q:** What is gamma?\n"
        "- **A:** Third answer.\n"
    )

    assert _summarize_chunks(QAMarkdownChunker(100, 50), text) == [
        (
            "- **Q:** What is alpha?\n- **A:** First answer.\n- **Q:** What is beta?\n- **A:** Second answer.\n",
            {
                "chunk_strategy": "qa_markdown",
                "start_char": 0,
                "end_char": 94,
                "qa_pair_count": 2,
                "qa_answered_count": 2,
                "qa_question_previews": ["** What is alpha?", "** What is beta?"],
                "chunk_index": 0,
            },
        ),
        (
            "- **Q:** What is beta?\n- **A:** Second answer.\n- **Q:** What is gamma?\n- **A:** Third answer.\n",
            {
                "chunk_strategy": "qa_markdown",
                "start_char": 47,
                "end_char": 141,
                "qa_pair_count": 2,
                "qa_answered_count": 2,
                "qa_question_previews": ["** What is beta?", "** What is gamma?"],
                "chunk_index": 1,
            },
        ),
        (
            "- **Q:** What is gamma?\n- **A:** Third answer.\n",
            {
                "chunk_strategy": "qa_markdown",
                "start_char": 94,
                "end_char": 141,
                "qa_pair_count": 1,
                "qa_answered_count": 1,
                "qa_question_previews": ["** What is gamma?"],
                "chunk_index": 2,
            },
        ),
    ]


def test_qa_pairs_chunker_characterizes_pair_overlap_offsets_and_previews() -> None:
    text = (
        "Q: Alpha?\n"
        "A: First answer.\n"
        "Q: Beta?\n"
        "A: Second answer.\n"
        "Q: Gamma?\n"
        "A: Third answer.\n"
    )

    assert _summarize_chunks(QAPairsChunker(60, 30), text) == [
        (
            "Q: Alpha?\nA: First answer.\nQ: Beta?\nA: Second answer.\n",
            {
                "chunk_strategy": "qa_pairs",
                "start_char": 0,
                "end_char": 54,
                "qa_pair_count": 2,
                "qa_answered_count": 2,
                "qa_question_previews": ["Alpha?", "Beta?"],
                "chunk_index": 0,
            },
        ),
        (
            "Q: Beta?\nA: Second answer.\nQ: Gamma?\nA: Third answer.\n",
            {
                "chunk_strategy": "qa_pairs",
                "start_char": 27,
                "end_char": 81,
                "qa_pair_count": 2,
                "qa_answered_count": 2,
                "qa_question_previews": ["Beta?", "Gamma?"],
                "chunk_index": 1,
            },
        ),
        (
            "Q: Gamma?\nA: Third answer.\n",
            {
                "chunk_strategy": "qa_pairs",
                "start_char": 54,
                "end_char": 81,
                "qa_pair_count": 1,
                "qa_answered_count": 1,
                "qa_question_previews": ["Gamma?"],
                "chunk_index": 2,
            },
        ),
    ]


def test_timeline_events_chunker_characterizes_event_overlap_offsets_and_metadata() -> None:
    text = (
        "2024-01-01 - Kickoff\n"
        "alpha\n"
        "2024-01-03 10:30 - Review\n"
        "beta\n"
        "2024-01-05 - Launch\n"
        "gamma\n"
    )

    assert _summarize_chunks(TimelineEventsChunker(70, 40), text) == [
        (
            "2024-01-01 - Kickoff\nalpha\n2024-01-03 10:30 - Review\nbeta\n",
            {
                "chunk_strategy": "timeline_events",
                "start_char": 0,
                "end_char": 58,
                "event_count": 2,
                "first_event": "2024-01-01",
                "last_event": "2024-01-03 10:30",
                "event_previews": ["Kickoff", "Review"],
                "chunk_index": 0,
            },
        ),
        (
            "2024-01-03 10:30 - Review\nbeta\n2024-01-05 - Launch\ngamma\n",
            {
                "chunk_strategy": "timeline_events",
                "start_char": 27,
                "end_char": 84,
                "event_count": 2,
                "first_event": "2024-01-03 10:30",
                "last_event": "2024-01-05",
                "event_previews": ["Review", "Launch"],
                "chunk_index": 1,
            },
        ),
        (
            "2024-01-05 - Launch\ngamma\n",
            {
                "chunk_strategy": "timeline_events",
                "start_char": 58,
                "end_char": 84,
                "event_count": 1,
                "first_event": "2024-01-05",
                "last_event": "2024-01-05",
                "event_previews": ["Launch"],
                "chunk_index": 2,
            },
        ),
    ]
