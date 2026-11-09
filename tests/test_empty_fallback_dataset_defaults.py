import pytest

from app.api.schemas.chat import ChatRAGConfig
from app.services.rag_defaults import merge_rag_config_with_dataset_defaults


@pytest.mark.parametrize("defaults", [{"fusion_strategy": False}, {"retrieval_contract_mode": "corrupt"}])
def test_invalid_effective_dataset_defaults_remain_errors(defaults: dict) -> None:
    with pytest.raises(ValueError):
        merge_rag_config_with_dataset_defaults(
            rag_config=ChatRAGConfig(), request_fields_set=set(), raw_dataset_defaults=defaults
        )


@pytest.mark.parametrize("defaults", [False, 0, []])
def test_invalid_dataset_default_containers_are_not_omitted(defaults: object) -> None:
    with pytest.raises(TypeError):
        merge_rag_config_with_dataset_defaults(
            rag_config=ChatRAGConfig(), request_fields_set=set(), raw_dataset_defaults=defaults
        )


def test_explicit_request_override_does_not_discard_other_dataset_defaults() -> None:
    request = ChatRAGConfig(top_k=12, fusion_strategy="weighted")
    result, applied = merge_rag_config_with_dataset_defaults(
        rag_config=request,
        request_fields_set={"fusion_strategy"},
        raw_dataset_defaults={"fusion_strategy": False, "top_k": 7},
    )
    assert result.fusion_strategy == "weighted"
    assert result.top_k == 7
    assert applied == ["top_k"]


@pytest.mark.parametrize("defaults", [None, {}])
def test_genuinely_absent_dataset_overrides_keep_the_request(defaults: object) -> None:
    request = ChatRAGConfig(top_k=12)
    result, applied = merge_rag_config_with_dataset_defaults(
        rag_config=request, request_fields_set=set(), raw_dataset_defaults=defaults
    )
    assert result is request
    assert applied == []
