def test_db_catalog_router_has_expected_paths():
    from app.api.v1 import db_catalog

    paths = {getattr(r, "path", "") for r in getattr(db_catalog, "router").routes}
    assert "/{dataset_id}/db-catalog/tables" in paths
    assert "/{dataset_id}/db-catalog/tables/{table_id}" in paths
    assert "/{dataset_id}/db-catalog/profiles" in paths

