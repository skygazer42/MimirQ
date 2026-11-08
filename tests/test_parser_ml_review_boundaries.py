import copy
import io
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response, UploadFile
from pydantic import ValidationError


@pytest.mark.parametrize("backend", ["tcadp", "TCADP Parser"])
def test_settings_parser_write_rejects_retired_value_while_shared_read_stays_available(backend):
    from app.api.schemas.settings import RAGConfig, UpdateSettingsRequest

    saved = RAGConfig(default_parser_backend=backend)
    assert saved.default_parser_backend == backend
    with pytest.raises(ValidationError, match="retired"):
        UpdateSettingsRequest(rag=saved)


def _policy(backend, *, enabled=True):
    from app.api.schemas.ingestion_policy import IngestionPolicy

    return IngestionPolicy(
        rules=[
            {
                "id": "pdf",
                "name": "PDF",
                "enabled": enabled,
                "match": {"extensions": [".pdf"]},
                "parser_backend": backend,
            }
        ]
    )


class _DB:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1

    def refresh(self, _obj):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["tcadp", "TCADP Parser"])
@pytest.mark.parametrize("operation", ["put", "import", "rollback", "config-bundle"])
async def test_actual_policy_activation_rejects_retired_selection_before_any_mutation(operation, backend, monkeypatch):
    from app.api.schemas.dataset import DatasetConfigBundle
    from app.api.schemas.ingestion_policy import IngestionPolicyRollbackRequest
    from app.api.v1 import datasets as routes
    from app.core.model_execution import RetiredModelProviderError

    policy = _policy(backend)
    metadata = {"preserved": True, "ingestion_policy_versions": [{"id": "old", "policy": policy.model_dump()}]}
    dataset = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), dataset_metadata=metadata)
    db = _DB()
    monkeypatch.setattr(routes.dataset_service, "get_dataset", lambda *_args: dataset)
    monkeypatch.setattr(routes.dataset_service, "assert_dataset_writable", lambda *_args: None)
    before = copy.deepcopy(metadata)
    args = {"tenant_id": dataset.tenant_id, "account_id": "member", "db": db}
    with pytest.raises(RetiredModelProviderError, match="retired"):
        if operation == "put":
            routes.put_dataset_ingestion_policy(dataset.id, policy, **args)
        elif operation == "import":
            file = UploadFile(filename="policy.json", file=io.BytesIO(json.dumps(policy.model_dump()).encode()))
            await routes.import_dataset_ingestion_policy(dataset.id, file, replace=True, **args)
        elif operation == "rollback":
            routes.rollback_dataset_ingestion_policy(
                dataset.id, IngestionPolicyRollbackRequest(version_id="old"), **args
            )
        else:
            routes._apply_policy_bundle_metadata(metadata, DatasetConfigBundle(ingestion_policy=policy), replace=False)
    assert db.commits == 0
    assert dataset.dataset_metadata == before
    assert metadata == before


def test_historical_policy_reads_exports_and_explicit_rule_deactivation_remain_available(monkeypatch):
    from app.api.v1 import datasets as routes
    from app.services.ingestion_policy import export_policy_json, parse_ingestion_policy_from_metadata

    policy = _policy("tcadp")
    saved = parse_ingestion_policy_from_metadata({"ingestion_policy": policy.model_dump()})
    assert saved is not None and saved.rules[0].parser_backend == "tcadp"
    assert json.loads(export_policy_json(saved))["rules"][0]["parser_backend"] == "tcadp"
    dataset = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), dataset_metadata={})
    db = _DB()
    monkeypatch.setattr(routes.dataset_service, "get_dataset", lambda *_args: dataset)
    monkeypatch.setattr(routes.dataset_service, "assert_dataset_writable", lambda *_args: None)
    routes.put_dataset_ingestion_policy(
        dataset.id, _policy("tcadp", enabled=False), tenant_id=dataset.tenant_id, account_id="member", db=db
    )
    assert dataset.dataset_metadata["ingestion_policy"]["rules"][0]["enabled"] is False
    assert db.commits == 1


@pytest.mark.parametrize(
    "selection",
    [
        {"default_parser_backend": "tcadp"},
        {"default_parser_backend": "TCADP Parser"},
        {"rag_defaults": {"reranker_provider": "ltr"}},
    ],
)
def test_config_bundle_validates_effective_parser_and_reranker_before_any_metadata_change(selection):
    from app.api.schemas.dataset import DatasetConfigBundle
    from app.api.v1 import datasets as routes
    from app.core.model_execution import RetiredModelProviderError

    metadata = {"preserved": True}
    with pytest.raises(RetiredModelProviderError, match="retired"):
        routes._apply_config_import_metadata(metadata, DatasetConfigBundle(**selection), replace=False)
    assert metadata == {"preserved": True}


def test_policy_metadata_writer_rejects_retired_enabled_rule():
    from app.core.model_execution import RetiredModelProviderError
    from app.services.ingestion_policy import policy_to_metadata

    with pytest.raises(RetiredModelProviderError, match="retired"):
        policy_to_metadata(_policy("tcadp"))


@pytest.mark.parametrize(
    "kind,expected", [("RetiredModelProviderError", 400), ("ValueError", 400), ("RuntimeError", 500)]
)
def test_production_document_preview_unwraps_retirement_as_actionable_input_error(kind, expected, monkeypatch):
    from app.api.v1 import document_preview as routes
    from app.parsing.subprocess_runner import SubprocessWorkerError

    monkeypatch.setattr(routes, "is_production_env", lambda: True)
    error = SubprocessWorkerError("parser provider tcadp has been retired", details={"type": kind})
    with pytest.raises(HTTPException) as caught:
        routes._raise_preview_http_exception(error)
    assert caught.value.status_code == expected
    if expected == 400:
        assert "retired" in str(caught.value.detail)
    else:
        assert caught.value.detail == "Failed to parse document"


@pytest.mark.asyncio
@pytest.mark.parametrize("flow", ["chunk", "pipeline-parse", "pipeline-ingestion"])
async def test_actual_preview_handlers_preserve_serialized_retirement_message(flow, monkeypatch, tmp_path):
    from app.api.v1 import document_chunk_preview as chunks
    from app.api.v1 import pipeline
    from app.parsing.subprocess_runner import SubprocessWorkerError

    tenant, dataset_id = uuid4(), uuid4()

    async def retired(**_kwargs):
        raise SubprocessWorkerError(
            "parser provider tcadp has been retired", details={"type": "RetiredModelProviderError"}
        )

    async def save(file, path, **_kwargs):
        path.write_bytes(await file.read())

    async def connected():
        return False

    request = SimpleNamespace(is_disconnected=connected)
    file = UploadFile(filename="preview.pdf", file=io.BytesIO(b"PDF fixture"))
    monkeypatch.setattr(chunks, "_execute_preview_chunking", retired)
    monkeypatch.setattr(pipeline, "run_subprocess_worker", retired)
    monkeypatch.setattr(pipeline, "save_upload_file", save)
    monkeypatch.setattr(pipeline.settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline.dataset_service, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(pipeline.dataset_service, "get_dataset", lambda *_args: SimpleNamespace(dataset_metadata={}))
    monkeypatch.setattr(pipeline.dataset_service, "assert_dataset_readable", lambda *_args: None)
    args = {"tenant_id": tenant, "account_id": "member", "db": object()}
    with pytest.raises(HTTPException) as caught:
        if flow == "chunk":
            await chunks.preview_chunking(request, Response(), file, SimpleNamespace(), **args)
        elif flow == "pipeline-parse":
            await pipeline.parse_preview(request, file, parser_backend="tcadp", **args)
        else:
            await pipeline.ingestion_preview(request, file, dataset_id, parser_backend="tcadp", **args)
    assert caught.value.status_code == 400
    assert "retired" in str(caught.value.detail)
