from copy import deepcopy

import pytest

from app.rag.core import retrieval_profiles
from app.rag.core.evidence_capsule_builder import (
    build_evidence_capsule,
    recompute_capsule_hash,
    sign_evidence_capsule,
    validate_evidence_capsule,
)
from app.rag.evaluation import chunk_diagnostics
from app.rag.evaluation.poc_runner.source_builder import build_dataset_analysis_sources


def test_evidence_capsule_validation_preserves_hash_anchor_and_signature_reasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capsule = build_evidence_capsule(
        query_for_retrieval="Where is the policy?",
        citations=[{"document_id": "doc-1", "chunk_id": "chunk-1", "page_number": 2}],
        metrics={"retrieval_mode": "hybrid"},
        retrieval_trace={"trace_id": "trace-1"},
    )
    capsule.pop("signature", None)

    assert validate_evidence_capsule(
        capsule,
        strict=True,
        verify_signature=False,
    ) == (True, "ok")

    missing_anchor = deepcopy(capsule)
    missing_anchor["citations"][0].pop("evidence_anchor_hash")
    missing_anchor["capsule_hash"] = recompute_capsule_hash(missing_anchor)
    assert validate_evidence_capsule(
        missing_anchor,
        strict=True,
        verify_signature=False,
    ) == (False, "missing_evidence_anchor_hash")

    signed = deepcopy(capsule)
    signed["signature"] = sign_evidence_capsule(signed, secret="secret")
    monkeypatch.setattr(
        "app.rag.core.evidence_capsule_builder._signing_secret_from_settings",
        lambda: "secret",
    )
    assert validate_evidence_capsule(
        signed,
        strict=True,
        verify_signature=True,
    ) == (True, "ok")


@pytest.mark.parametrize(
    ("profile", "kwargs", "expected"),
    [
        (
            "fast",
            {},
            {
                "retrieval_mode": "vector",
                "top_k": 10,
                "enable_reranker": False,
                "reranker_provider": "none",
            },
        ),
        (
            "balanced",
            {"enable_reranker": False},
            {
                "retrieval_mode": "hybrid",
                "top_k": 10,
                "enable_reranker": False,
                "reranker_provider": "none",
                "reranker_top_n": 1,
            },
        ),
        (
            "quality",
            {"reranker_provider": "cohere"},
            {
                "retrieval_mode": "hybrid",
                "top_k": 20,
                "reranker_provider": "cohere",
                "reranker_top_n": 40,
                "enable_hierarchy_recall": True,
            },
        ),
        (
            "hierarchy_grounded_strict",
            {},
            {
                "retrieval_contract_mode": "evidence_strict",
                "visible_evidence_only": True,
                "enable_hierarchy_recall": True,
            },
        ),
    ],
)
def test_retrieval_profile_overrides_preserve_profile_contracts(
    profile: str,
    kwargs: dict[str, object],
    expected: dict[str, object],
) -> None:
    result = retrieval_profiles.apply_retrieval_profile_overrides(
        profile=profile,
        top_k=5,
        score_threshold=0.7,
        **kwargs,
    )
    assert {key: result[key] for key in expected} == expected


def test_chunk_diagnostics_preserves_attribution_noise_and_self_knowledge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        chunk_diagnostics,
        "split_into_claims",
        lambda _answer, *, max_claims: ["supported", "noisy", "uncited"][:max_claims],
    )
    monkeypatch.setattr(chunk_diagnostics, "_is_informative_claim", lambda _claim: True)

    def _is_supported(claim: str, evidence: str, *, verifier_mode: str) -> bool:
        assert verifier_mode == "strict"
        return (claim, evidence) in {
            ("supported", "relevant context"),
            ("noisy", "noise context"),
            ("supported", "reference"),
            ("uncited", "reference"),
        }

    monkeypatch.setattr(chunk_diagnostics, "is_claim_supported", _is_supported)

    assert chunk_diagnostics.compute_chunk_diagnostics(
        answer="answer",
        retrieved_contexts=["relevant context", "noise context"],
        context_relevance=[True, False],
        reference_evidence_text="reference",
    ) == {
        "chunk_utilization": 1.0,
        "chunk_attribution": 0.6667,
        "noise_sensitivity": 0.5,
        "self_knowledge_ratio": 0.5,
        "counts": {
            "claims_total": 3,
            "claims_supported": 2,
            "claims_noisy": 1,
            "claims_correct_total": 2,
            "claims_correct_uncited": 1,
            "chunks_total": 2,
            "chunks_used": 2,
        },
    }


def test_dataset_analysis_source_builder_preserves_request_linkage_and_counts() -> None:
    result = build_dataset_analysis_sources(
        traces=[{"request_id": "req-1", "conversation_id": "conv-1"}],
        conversations=[{"id": "conv-1", "title": "Example"}],
        messages=[
            {
                "id": "user-1",
                "conversation_id": "conv-1",
                "role": "user",
                "created_at": "2026-08-16T09:00:00Z",
                "content": "Question",
            },
            {
                "id": "assistant-1",
                "conversation_id": "conv-1",
                "role": "assistant",
                "created_at": "2026-08-16T09:01:00Z",
                "message_metadata": {"request_id": "req-1"},
                "content": "Answer",
            },
        ],
        feedback_rows=[
            {
                "id": "feedback-1",
                "conversation_id": "conv-1",
                "message_id": "assistant-1",
                "rating": -1,
                "extra": {"retrieval_trace_request_id": "req-1"},
            }
        ],
    )

    assert result["counts"] == {
        "all_interactions": 1,
        "feedback_interactions": 1,
        "attributable_feedback_interactions": 1,
    }
    row = result["rows"][0]
    assert row["assistant_message"]["id"] == "assistant-1"
    assert row["user_message"]["id"] == "user-1"
    assert row["feedback"]["id"] == "feedback-1"
    assert row["linkage"] == {
        "assistant_match": "request_id",
        "feedback_match": "request_id",
    }
