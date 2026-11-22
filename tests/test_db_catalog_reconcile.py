from types import SimpleNamespace

import pytest

from app.services.connectors.reconcile import plan_connector_reconcile, resolve_connector_reconcile_source_refs


@pytest.mark.parametrize("connector_id", ["mysql_catalog", "sqlserver_catalog"])
@pytest.mark.parametrize("legacy_sidecar_ref", [False, True])
def test_reconcile_keeps_the_sidecar_for_a_current_table_manifest(connector_id, legacy_sidecar_ref):
    config_id = "saved-config"
    identity = f"db_catalog_rows:{connector_id}"
    sidecar = SimpleNamespace(
        disabled_at=None,
        doc_metadata={
            "connector": {
                "connector_id": connector_id,
                "config_id": config_id,
                "source_ref": identity if legacy_sidecar_ref else f"{identity}:{config_id}",
            }
        },
    )
    desired_refs = resolve_connector_reconcile_source_refs(
        connector_id=connector_id,
        config={},
        state={"source_manifest": {"inventory.parts": "table-token", "inventory.stock": "other-table-token"}},
    )
    report = plan_connector_reconcile(
        connector_id=connector_id,
        config_id=config_id,
        dataset_id="dataset",
        documents=[sidecar],
        desired_source_refs=desired_refs,
        apply=True,
    )

    assert sidecar.disabled_at is None
    assert report["desired_source_refs"] == 1
    assert report["active_source_refs"] == 1
    assert report["stale_source_refs"] == 0
    assert report["missing_source_refs"] == 0
    assert report["disabled_documents"] == 0
