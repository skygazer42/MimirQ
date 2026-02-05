from uuid import uuid4

import pytest

from app.api.schemas.regression import RagasRegressionCasePatchRequest


def test_patch_requires_at_least_one_field():
    with pytest.raises(Exception):
        RagasRegressionCasePatchRequest()


def test_patch_allows_clearing_expected_answer():
    req = RagasRegressionCasePatchRequest(expected_answer=None)
    assert req.expected_answer is None


def test_patch_rejects_empty_reference_sources_when_provided():
    with pytest.raises(Exception):
        RagasRegressionCasePatchRequest(reference_sources=[])


def test_patch_valid_reference_sources():
    req = RagasRegressionCasePatchRequest(
        reference_sources=[{"document_id": str(uuid4()), "chunk_id": str(uuid4())}]
    )
    assert len(req.reference_sources or []) == 1

