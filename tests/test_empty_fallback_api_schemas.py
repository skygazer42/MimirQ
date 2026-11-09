from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.schemas.chat import ChatRAGConfig
from app.api.schemas.regression import RagasRegressionRunCreateRequest


@pytest.mark.parametrize("value", [0, False, [], {}])
def test_fusion_selectors_do_not_turn_invalid_values_into_omitted_overrides(value) -> None:
    with pytest.raises(ValidationError):
        ChatRAGConfig(fusion_strategy=value)
    with pytest.raises(ValidationError):
        RagasRegressionRunCreateRequest(dataset_id=uuid4(), fusion_strategy=value)


@pytest.mark.parametrize("value", [0, False, [], {}])
def test_sparse_selector_does_not_turn_invalid_values_into_inheritance(value) -> None:
    with pytest.raises(ValidationError):
        RagasRegressionRunCreateRequest(dataset_id=uuid4(), sparse_retrieval_provider=value)


def test_valid_optional_blank_and_alias_selectors_keep_their_contract() -> None:
    assert ChatRAGConfig(fusion_strategy="  ").fusion_strategy is None
    assert ChatRAGConfig(fusion_strategy=" RRF ").fusion_strategy == "rrf"
    assert (
        RagasRegressionRunCreateRequest(dataset_id=uuid4(), sparse_retrieval_provider="  ").sparse_retrieval_provider
        is None
    )
