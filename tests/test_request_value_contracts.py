import pytest
from pydantic import ValidationError

from app.api.schemas.chat import ChatRAGConfig
from app.api.schemas.connector_acl import SourcePrincipal
from app.api.schemas.document import DocumentPipelineOptions, DocumentPipelineProvenance
from app.api.schemas.group import TenantGroupUpdateRequest


@pytest.mark.parametrize(
    "field", ["must_recall_expected_source_keys", "must_recall_required_anchor_fields", "industry_rules_rulesets"]
)
@pytest.mark.parametrize("provided", [[], None])
def test_chat_patch_keeps_explicit_empty_lists_distinct_from_missing(field: str, provided) -> None:
    config = ChatRAGConfig(retrieval_profile="fast", **{field: provided})

    patch = config.model_dump(exclude_none=True)

    if provided is None:
        assert field not in patch
    else:
        assert patch[field] == []


@pytest.mark.parametrize("field", ["fusion_budgets", "fusion_min_scores"])
@pytest.mark.parametrize("provided", [{}, None])
def test_chat_patch_keeps_explicit_empty_fusion_maps(field: str, provided) -> None:
    config = ChatRAGConfig(retrieval_profile="fast", **{field: provided})

    patch = config.model_dump(exclude_none=True)

    if provided is None:
        assert field not in patch
    else:
        assert patch[field] == {}


@pytest.mark.parametrize(
    "field", ["chunk_strategy_params", "governance_python_params", "chunk_python_params", "kg_python_params"]
)
@pytest.mark.parametrize("provided", [{}, None])
def test_pipeline_patch_keeps_explicit_empty_parameter_maps(field: str, provided) -> None:
    config = DocumentPipelineOptions(**{field: provided})

    patch = config.model_dump(exclude_none=True)

    if provided is None:
        assert field not in patch
    else:
        assert patch[field] == {}


def test_pipeline_patch_still_rejects_nested_python_parameters() -> None:
    with pytest.raises(ValidationError):
        DocumentPipelineOptions(governance_python_params={"nested": {}})


def test_group_update_allows_an_omitted_name() -> None:
    assert TenantGroupUpdateRequest().name is None


def test_principal_patch_keeps_an_explicit_empty_display_label() -> None:
    principal = SourcePrincipal(system="generic", kind="user", id="user-1", display="")

    assert principal.model_dump(exclude_none=True)["display"] == ""
    assert principal.key() == "generic:user:user-1"


@pytest.mark.parametrize(
    "field",
    ["pipeline_hash", "parser_backend", "parser_backend_requested", "chunk_strategy", "chunk_strategy_requested"],
)
def test_document_provenance_keeps_stored_empty_text(field: str) -> None:
    provenance = DocumentPipelineProvenance.from_metadata({field: ""})

    assert provenance.model_dump(exclude_none=True)[field] == ""


@pytest.mark.parametrize("field,value", [("pipeline_hash", False), ("parser_backend", 0)])
def test_document_provenance_exposes_invalid_stored_field_types(field: str, value) -> None:
    error_type = AttributeError if field == "pipeline_hash" else ValidationError
    with pytest.raises(error_type):
        DocumentPipelineProvenance.from_metadata({field: value})
