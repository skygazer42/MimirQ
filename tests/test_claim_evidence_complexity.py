from langchain_core.documents import Document

from app.rag.core import claim_evidence as claim_evidence_mod
from app.rag.core.claim_evidence import _extract_span, build_claim_evidence_map


def test_extract_span_prefers_earliest_term_and_marks_trimmed_context() -> None:
    text = "Opening sentence. " + ("x" * 90) + ". Alpha evidence sentence. " + ("y" * 90) + "."

    span = _extract_span(text, ["evidence", "Alpha"], max_chars=80)

    assert span is not None
    start, end, quote = span
    assert "Alpha evidence sentence." in text[start:end]
    assert quote.startswith("...")
    assert quote.endswith("...")


def test_claim_evidence_map_keeps_uncertain_claim_without_support() -> None:
    result = build_claim_evidence_map(
        "证据不足，无法确定最终审批人。",
        evidence_chunks=[{"text": "最终审批人为财务负责人。", "chunk_id": "chunk-1"}],
    )

    assert result == [{"claim": "证据不足，无法确定最终审批人。", "evidence": []}]


def test_claim_evidence_map_ranks_overlap_and_offsets_span(monkeypatch) -> None:
    monkeypatch.setattr(claim_evidence_mod, "is_claim_supported", lambda *_args, **_kwargs: True)
    answer = "Alpha policy requires finance approval."
    supporting_text = "Intro. Alpha policy requires finance approval before payment. Tail."

    result = build_claim_evidence_map(
        answer,
        evidence_chunks=[
            {
                "text": "Alpha appears without the policy details.",
                "document_id": "doc-low",
                "chunk_id": "chunk-low",
                "start_char": 10,
            },
            {
                "text": supporting_text,
                "document_id": "doc-best",
                "chunk_id": "chunk-best",
                "start_char": "100",
            },
        ],
        max_evidence_per_claim=1,
    )

    evidence = result[0]["evidence"]
    assert len(evidence) == 1
    assert evidence[0]["document_id"] == "doc-best"
    assert evidence[0]["chunk_id"] == "chunk-best"
    assert evidence[0]["start_char"] == 106
    assert evidence[0]["end_char"] == 161
    assert evidence[0]["quote"] == "...Alpha policy requires finance approval before payment...."
    assert evidence[0]["score"] == 1.0


def test_claim_evidence_map_accepts_document_metadata_scope(monkeypatch) -> None:
    monkeypatch.setattr(claim_evidence_mod, "is_claim_supported", lambda *_args, **_kwargs: True)
    document = Document(
        page_content="Release policy requires review.",
        metadata={"document_id": "doc-1", "chunk_id": "chunk-1", "start_char": 20},
    )

    result = build_claim_evidence_map(
        "Release policy requires review.",
        evidence_chunks=[document],
    )

    assert result[0]["evidence"][0]["document_id"] == "doc-1"
    assert result[0]["evidence"][0]["chunk_id"] == "chunk-1"
    assert result[0]["evidence"][0]["start_char"] == 20
