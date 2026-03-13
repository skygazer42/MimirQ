from __future__ import annotations

from uuid import uuid4

from app.api.schemas.regression import (
    RagasRegressionCaseBundleItem,
    RagasRegressionCaseCreateRequest,
    RagasRegressionCasePatchRequest,
)


def test_regression_case_create_accepts_reasoning_hops_and_evidence_chain() -> None:
    req = RagasRegressionCaseCreateRequest(
        question="What caused outage X?",
        dataset_id=uuid4(),
        reference_sources=[{"document_id": str(uuid4()), "chunk_id": str(uuid4())}],
        reasoning_hops=["find incident", "map root cause"],
        evidence_chain=[
            {"document_id": str(uuid4()), "chunk_id": str(uuid4())},
            {"document_id": str(uuid4()), "chunk_id": str(uuid4())},
        ],
    )
    assert len(req.reasoning_hops) == 2
    assert len(req.evidence_chain) == 2


def test_regression_case_patch_accepts_multihop_fields() -> None:
    req = RagasRegressionCasePatchRequest(
        reasoning_hops=["hop-1", "hop-2"],
        evidence_chain=[{"document_id": str(uuid4()), "chunk_id": str(uuid4())}],
    )
    assert req.reasoning_hops == ["hop-1", "hop-2"]
    assert len(req.evidence_chain or []) == 1


def test_regression_bundle_item_keeps_multihop_fields() -> None:
    item = RagasRegressionCaseBundleItem(
        question="q",
        reference_sources=[{"document_id": str(uuid4()), "chunk_id": str(uuid4())}],
        reasoning_hops=["a", "b"],
        evidence_chain=[{"document_id": str(uuid4()), "chunk_id": str(uuid4())}],
    )
    assert item.reasoning_hops == ["a", "b"]
    assert len(item.evidence_chain) == 1
