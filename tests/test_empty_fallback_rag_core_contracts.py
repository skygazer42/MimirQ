from uuid import uuid4

import pytest

from app.rag.core.claim_evidence import build_claim_evidence_map
from app.rag.core.code_fence import extract_first_code_fence
from app.rag.core.confidence import compute_confidence_score
from app.rag.core.evidence_expectations import evaluate_evidence_anchor_expectations
from app.rag.core.pipeline_scope import apply_active_pipeline_metadata_filter
from app.rag.core.sentence_citations import render_sentence_citations_inline, render_sentence_citations_markdown


@pytest.mark.parametrize("field", [None, False, 0])
def test_invalid_required_anchor_names_cannot_disable_the_check(field):
    with pytest.raises((AttributeError, TypeError)):
        evaluate_evidence_anchor_expectations(citations=[], required_fields=[field])


def test_code_fence_allowlist_requires_string_info_values():
    with pytest.raises((AttributeError, TypeError)):
        extract_first_code_fence("```\nUnlabelled content.\n```", allowed_info_strings=[None])


@pytest.mark.parametrize("renderer", [render_sentence_citations_inline, render_sentence_citations_markdown])
def test_citation_rendering_exposes_missing_internal_claim_text(renderer):
    with pytest.raises(KeyError, match="claim"):
        renderer([{"evidence": []}])


def test_claim_mapping_skips_unmatched_record_variants_and_keeps_valid_siblings():
    result = build_claim_evidence_map(
        "The service supports tenant isolation.",
        evidence_chunks=[
            {"document_id": "unmatched-record"},
            {"document_id": "doc-1", "chunk_id": "chunk-1", "text": "The service supports tenant isolation."},
        ],
    )
    assert result[0]["evidence"][0]["chunk_id"] == "chunk-1"


def test_confidence_scoring_requires_severity_for_a_reported_gap():
    with pytest.raises(KeyError, match="severity"):
        compute_confidence_score(
            faithfulness_score=1.0,
            claim_total=1,
            claim_supported=1,
            evidence_gap={"has_gap": True},
        )


def test_pipeline_scope_does_not_treat_a_missing_persisted_status_as_inactive():
    document_id = uuid4()

    class Query:
        def query(self, *args):
            return self

        def filter(self, *args):
            return self

        def all(self):
            return [(document_id, None, {})]

    with pytest.raises((AttributeError, TypeError)):
        apply_active_pipeline_metadata_filter(
            db=Query(), tenant_id=uuid4(), document_ids=[document_id], metadata_filter=None
        )
