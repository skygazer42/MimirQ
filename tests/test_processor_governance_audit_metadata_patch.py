from __future__ import annotations


def test_collect_parser_asset_refs_collects_images_and_artifact_dirs() -> None:
    from langchain_core.documents import Document

    from app.parsing.processors.processor import ParseResult, _collect_parser_asset_refs

    parsed = ParseResult(
        resolved_backend="deepdoc",
        resolved_chunk_strategy="default",
        documents=[
            Document(
                page_content="doc",
                metadata={
                    "images": [{"img_id": "img-1"}, {"img_id": "img-2"}],
                    "artifact_dir": "artifacts/doc",
                },
            )
        ],
        chunks=[
            Document(
                page_content="chunk",
                metadata={"artifact_dir": "artifacts/chunk"},
            )
        ],
    )
    image_ids: set[str] = set()
    artifact_dirs: set[str] = set()

    _collect_parser_asset_refs(
        parsed,
        document_img_ids=image_ids,
        artifact_dirs=artifact_dirs,
    )

    assert image_ids == {"img-1", "img-2"}
    assert artifact_dirs == {"artifacts/doc", "artifacts/chunk"}


def test_apply_inline_asset_audit_patch_writes_available_fields() -> None:
    from app.parsing.processors.processor import InlineAssetResult, _apply_inline_asset_audit_patch

    class _Doc:
        def __init__(self) -> None:
            self.doc_metadata = {}

    class _DB:
        def __init__(self) -> None:
            self.committed = False
            self.refreshed = False

        def commit(self) -> None:
            self.committed = True

        def refresh(self, _doc) -> None:  # noqa: ANN001
            self.refreshed = True

    db = _DB()
    doc = _Doc()
    inline = InlineAssetResult(
        documents=[],
        uploaded_img_ids=[],
        next_asset_index=0,
        image_codes_added=2,
        image_code_audit={"added": 2},
        captions_added=3,
        caption_backend="vlm",
        caption_audit={"backend": "vlm"},
        formulas_added=1,
        formula_backend="ocr",
        formula_audit={"backend": "ocr"},
        charts_added=4,
        chart_backend="chart",
        chart_audit={"backend": "chart"},
    )

    _apply_inline_asset_audit_patch(db, doc, inline)

    assert doc.doc_metadata["image_codes_added"] == 2
    assert doc.doc_metadata["image_code_audit"] == {"added": 2}
    assert doc.doc_metadata["image_captions_added"] == 3
    assert doc.doc_metadata["image_caption_backend"] == "vlm"
    assert doc.doc_metadata["formula_ocr_added"] == 1
    assert doc.doc_metadata["formula_ocr_backend"] == "ocr"
    assert doc.doc_metadata["chart_data_added"] == 4
    assert doc.doc_metadata["chart_data_backend"] == "chart"
    assert db.committed is True
    assert db.refreshed is True


def test_processor_build_governance_audit_metadata_patch() -> None:
    from langchain_core.documents import Document

    from app.parsing.processors.processor import DocumentProcessorService

    svc = DocumentProcessorService()
    before = [Document(page_content="abc", metadata={})]
    after = [
        Document(
            page_content="ab",
            metadata={
                "governance_quality": {
                    "chars_non_space": 10,
                    "chars_alnum_cjk": 5,
                    "lines_total": 10,
                    "lines_outline": 2,
                    "content_chars": 50,
                }
            },
        )
    ]

    patch = svc._build_governance_audit_metadata_patch(before_items=before, after_items=after)

    assert patch["governance_char_stats"]["original_chars"] == 3
    assert patch["governance_char_stats"]["cleaned_chars"] == 2
    assert patch["governance_char_stats"]["reduction_pct"] == 33

    quality = patch["governance_quality"]
    assert abs(float(quality["density"]) - 0.5) < 1e-9
    assert abs(float(quality["heading_ratio"]) - 0.2) < 1e-9
    assert patch["governance_quality_source"] == "cleaned"
