from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.schemas.documents.document import DocumentPipelineOptions
from app.api.schemas.documents.ingestion import PipelineOptionOverrides
from app.api.schemas.sources.policy import IngestionPolicy, IngestionRule
from app.models.datasets.records import Dataset
from app.services.documents import ingestion_policy as ingestion_plan


@pytest.mark.parametrize(("origin", "expected_size"), [("file", 600), ("external", 450)])
def test_rule_and_profile_precedence_preserves_each_existing_ingestion_contract(monkeypatch, origin, expected_size):
    rule = IngestionRule(
        id="rule", name="Rule", governance_profile_ref="builtin:test", pipeline_patch={"chunk_size": 450}
    )
    policy = IngestionPolicy(rules=[rule])
    dataset = Dataset(dataset_metadata={"ingestion_policy": policy.model_dump()})
    monkeypatch.setattr(
        ingestion_plan,
        "resolve_governance_profile_ref",
        lambda **kwargs: SimpleNamespace(pipeline_patch={"chunk_size": 600}, regex_rules=[]),
    )
    request = DocumentPipelineOptions(chunk_overlap=0, chunk_vector_enabled=False)
    if origin == "file":
        result = ingestion_plan.resolve_upload_pipeline(
            db=object(),
            tenant_id=uuid4(),
            dataset_meta=dataset.dataset_metadata,
            policy=policy,
            filename="source.txt",
            file_ext=".txt",
            pipeline_parsed=request,
            pipeline_overrides=PipelineOptionOverrides(),
            defaults=ingestion_plan.select_upload_defaults(
                parser_backend="auto",
                chunk_strategy="langchain_recursive",
                dataset_default_pb=None,
                dataset_default_cs=None,
            ),
        )
    else:
        result = ingestion_plan.resolve_document_ingestion_policy(
            db=object(),
            tenant_id=uuid4(),
            dataset=dataset,
            filename="source.txt",
            file_ext=".txt",
            requested_parser_backend="auto",
            requested_chunk_strategy="langchain_recursive",
            pipeline=request,
            source_url="https://example.com/source.txt",
        )
    assert result.pipeline_options.chunk_size == expected_size
    assert result.pipeline_options.chunk_overlap == 0
    assert result.pipeline_options.chunk_vector_enabled is False


def test_file_default_selection_and_external_auto_keep_their_existing_meaning(monkeypatch):
    monkeypatch.setattr(ingestion_plan.settings, "DEFAULT_PARSER_BACKEND", "auto")
    monkeypatch.setattr(ingestion_plan.settings, "DEFAULT_CHUNK_STRATEGY", "langchain_recursive")
    file_defaults = ingestion_plan.select_upload_defaults(
        parser_backend="auto",
        chunk_strategy="langchain_recursive",
        dataset_default_pb="unstructured",
        dataset_default_cs=None,
    )
    external = ingestion_plan.resolve_document_ingestion_policy(
        db=object(),
        tenant_id=uuid4(),
        dataset=Dataset(dataset_metadata={"default_parser_backend": "unstructured"}),
        filename="source.txt",
        file_ext=".txt",
        requested_parser_backend="auto",
        requested_chunk_strategy="langchain_recursive",
        pipeline=None,
        source_url=None,
    )
    assert file_defaults.parser_backend_base == "unstructured"
    assert external.parser_backend_choice == "auto"
