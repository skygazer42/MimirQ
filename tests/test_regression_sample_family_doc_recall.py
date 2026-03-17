from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4


def test_build_regression_sample_emits_doc_and_family_recall_when_keys_present() -> None:
    from app.rag.evaluation.regression_sample_builder import build_regression_sample  # noqa: WPS433

    doc_id = uuid4()
    ref_chunk_a = uuid4()
    ref_chunk_b = uuid4()
    got_chunk_a = ref_chunk_a
    got_chunk_other = uuid4()

    case = SimpleNamespace(
        dataset_id=uuid4(),
        expected_answer=None,
        reference_sources=[
            {
                "document_id": str(doc_id),
                "chunk_id": str(ref_chunk_a),
                "family_collapse_key": "famA",
                "quote": "ref a",
            },
            {
                "document_id": str(doc_id),
                "chunk_id": str(ref_chunk_b),
                "family_collapse_key": "famB",
                "quote": "ref b",
            },
        ],
    )

    item = {
        "case_id": str(uuid4()),
        "question": "q",
        "response": "",
        "retrieved_contexts": [],
        "citations": [
            {"document_id": str(doc_id), "chunk_id": str(got_chunk_a), "family_collapse_key": "famA"},
            {"document_id": str(doc_id), "chunk_id": str(got_chunk_other), "family_collapse_key": "famC"},
        ],
        "abstain_triggered": False,
        "abstain_reason": None,
        "top_relevance_score": 0.9,
    }

    _sample_kwargs, meta = build_regression_sample(case, item)

    assert meta.get("retrieval_recall") == 0.5
    assert meta.get("retrieval_doc_recall") == 1.0
    assert meta.get("retrieval_family_recall") == 0.5
    assert meta.get("retrieval_family_hit") is True

