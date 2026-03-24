from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4


def test_dataset_config_bundle_accepts_workflow_layout() -> None:
    from app.api.schemas.dataset import DatasetConfigBundle

    bundle = DatasetConfigBundle(
        workflow_layout={
            "schema": "mimirq.workflow_layout.v1",
            "nodes": [{"id": "retrieve", "x": 120, "y": 80}],
            "edges": [],
        }
    )

    assert bundle.workflow_layout is not None
    assert bundle.workflow_layout["schema"] == "mimirq.workflow_layout.v1"


def test_build_dataset_config_bundle_preserves_workflow_layout_metadata() -> None:
    from app.api.v1.datasets import _build_dataset_config_bundle

    bundle = _build_dataset_config_bundle(
        SimpleNamespace(
            dataset_metadata={
                "workflow_layout": {
                    "schema": "mimirq.workflow_layout.v1",
                    "nodes": [{"id": "retrieve", "x": 120, "y": 80}],
                    "edges": [],
                }
            }
        )
    )

    assert bundle.workflow_layout is not None
    assert bundle.workflow_layout["nodes"][0]["id"] == "retrieve"


def test_import_dataset_config_preserves_workflow_layout_metadata(monkeypatch) -> None:
    from app.api.schemas.dataset import DatasetConfigBundle, DatasetConfigImportRequest
    from app.api.v1.datasets import import_dataset_config
    from app.models.dataset import DatasetPermissionEnum

    tenant_id = uuid4()
    dataset_id = uuid4()
    dataset = SimpleNamespace(
        id=dataset_id,
        tenant_id=tenant_id,
        name="Dataset",
        description=None,
        permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
        owner_id="owner",
        dataset_metadata={},
    )

    class _DB:
        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

    monkeypatch.setattr("app.api.v1.datasets.DatasetService.ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr("app.api.v1.datasets.DatasetService.get_dataset", lambda *_a, **_k: dataset, raising=True)
    monkeypatch.setattr("app.api.v1.datasets.DatasetService.assert_dataset_writable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr("app.api.v1.datasets.audit_log_event", lambda *_a, **_k: None, raising=True)

    import_dataset_config(
        dataset_id=dataset_id,
        payload=DatasetConfigImportRequest(
            config=DatasetConfigBundle(
                workflow_layout={
                    "schema": "mimirq.workflow_layout.v1",
                    "nodes": [{"id": "retrieve", "x": 120, "y": 80}],
                    "edges": [],
                }
            ),
            replace=False,
        ),
        tenant_id=tenant_id,
        account_id="user",
        db=_DB(),
    )

    assert dataset.dataset_metadata["workflow_layout"]["schema"] == "mimirq.workflow_layout.v1"
