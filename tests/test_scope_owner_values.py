from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.pipeline_versions import get_active_pipeline_hash
from app.parsing.models.manifest import SmallModelManifest, SmallModelSpec
from app.parsing.models.runtime import SmallModelRuntime
from app.rag.retrieval.orchestration.kg_merge_boost import _resolve_kg_scope
from app.services import chat_scope


def test_kg_scope_keeps_a_supplied_empty_document_selection() -> None:
    dataset = uuid4()
    assert _resolve_kg_scope({"document_ids": [], "dataset_id": dataset}) == ([], None, [])
    assert _resolve_kg_scope({"document_ids": None, "dataset_id": dataset}) == (None, dataset, [])


def test_unselected_chat_scope_is_represented_at_its_owner() -> None:
    result = chat_scope._get_new_conversation_scope(
        db=object(),
        tenant_id=uuid4(),
        account_id="reader",
        request_document_ids=[],
        request_dataset_id=None,
        allow_open_scope=True,
        dataset_required_detail="dataset required",
        document_scope_mismatch_detail="mismatch",
    )
    assert result == (None, None)


def test_dataset_chat_scope_has_no_document_restriction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_scope.dataset_service, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(chat_scope.dataset_service, "get_dataset", lambda *_args: SimpleNamespace())
    monkeypatch.setattr(chat_scope.dataset_service, "assert_dataset_readable", lambda *_args: None)
    dataset = uuid4()
    assert chat_scope._resolve_requested_dataset_scope(
        db=object(), tenant_id=uuid4(), account_id="reader", request_dataset_id=dataset
    ) == (dataset, None)


@pytest.mark.parametrize("value", [0, False, [], {}])
def test_invalid_active_pipeline_metadata_is_not_treated_as_missing(value) -> None:
    with pytest.raises(AttributeError):
        get_active_pipeline_hash({"active_pipeline_hash": value, "pipeline_hash": "legacy"})


def test_explicit_model_version_is_not_replaced_by_revision_or_placeholder(tmp_path: Path) -> None:
    spec = SmallModelSpec(
        task="example",
        model_id="example",
        kind="onnx",
        path="missing-model",
        revision="revision",
        metadata={"version": ""},
        _base_dir=tmp_path,
    )
    manifest = SmallModelManifest(
        path=tmp_path / "manifest.yaml", tasks={"example": {"example": spec}}, defaults={"example": "example"}
    )
    status = SmallModelRuntime(manifest=manifest).resolve("example")
    assert status.available is False
    assert status.version == ""
    assert status.to_metadata()["version"] == ""
