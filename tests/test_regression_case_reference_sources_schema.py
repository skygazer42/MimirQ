from uuid import uuid4

import pytest

from app.api.schemas.regression import RagasRegressionCaseCreateRequest


def test_case_create_requires_dataset_id():
    with pytest.raises(Exception):
        RagasRegressionCaseCreateRequest(
            question="q",
            dataset_id=None,  # type: ignore[arg-type]
            reference_sources=[{"document_id": str(uuid4()), "chunk_id": str(uuid4())}],
        )


def test_case_create_requires_reference_sources():
    with pytest.raises(Exception):
        RagasRegressionCaseCreateRequest(
            question="q",
            dataset_id=uuid4(),
            reference_sources=[],
        )


def test_reference_source_requires_doc_and_chunk():
    ds = uuid4()
    with pytest.raises(Exception):
        RagasRegressionCaseCreateRequest(
            question="q",
            dataset_id=ds,
            reference_sources=[{"document_id": str(uuid4())}],  # missing chunk_id
        )

    with pytest.raises(Exception):
        RagasRegressionCaseCreateRequest(
            question="q",
            dataset_id=ds,
            reference_sources=[{"chunk_id": str(uuid4())}],  # missing document_id
        )


def test_reference_source_accepts_optional_fields():
    ds = uuid4()
    req = RagasRegressionCaseCreateRequest(
        question="q",
        dataset_id=ds,
        reference_sources=[
            {
                "document_id": str(uuid4()),
                "chunk_id": str(uuid4()),
                "page_number": 3,
                "start_char": 10,
                "end_char": 42,
                "quote": "snippet",
                "label": "manual",
            }
        ],
    )
    assert str(req.dataset_id) == str(ds)
    assert len(req.reference_sources) == 1

