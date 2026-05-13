from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_catalog_route_is_split_from_connectors_router() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_catalog.py")

    assert "connectors_catalog" in connectors_source
    assert "router.routes.extend(connectors_catalog.router.routes)" in connectors_source

    assert '@router.get("",' not in connectors_source
    assert '@router.get("")' in split_source


def test_connectors_router_still_exposes_catalog_route() -> None:
    from app.api.v1.connectors import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("", ("GET",)) in routes


def test_validate_route_is_split_from_connectors_router() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_validation.py")

    assert "connectors_catalog" in connectors_source
    assert "connectors_validation" in connectors_source
    assert "router.routes.extend(connectors_validation.router.routes)" in connectors_source

    assert '@router.post("/validate"' not in connectors_source
    assert '@router.post("/validate"' in split_source


def test_connectors_router_still_exposes_validate_route() -> None:
    from app.api.v1.connectors import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/validate", ("POST",)) in routes


def test_run_routes_are_split_from_connectors_router() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_runs.py")

    assert "connectors_runs" in connectors_source
    assert "router.routes.extend(connectors_runs.router.routes)" in connectors_source

    split_route_decorators = (
        '@router.post("/runs"',
        '@router.get("/runs"',
        '@router.get("/runs/{run_id}"',
        '@router.post("/runs/{run_id}/retry-failed"',
        '@router.post("/runs/{run_id}/resume"',
        '@router.post("/runs/{run_id}/cancel"',
    )
    for decorator in split_route_decorators:
        assert decorator not in connectors_source
        assert decorator in split_source


def test_connectors_router_still_exposes_run_routes() -> None:
    from app.api.v1.connectors import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/runs", ("POST",)) in routes
    assert ("/runs", ("GET",)) in routes
    assert ("/runs/{run_id}", ("GET",)) in routes
    assert ("/runs/{run_id}/retry-failed", ("POST",)) in routes
    assert ("/runs/{run_id}/resume", ("POST",)) in routes
    assert ("/runs/{run_id}/cancel", ("POST",)) in routes


def test_config_routes_are_split_from_connectors_router() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_configs.py")

    assert "connectors_configs" in connectors_source
    assert "router.routes.extend(connectors_configs.router.routes)" in connectors_source

    split_route_decorators = (
        '@router.get("/configs"',
        '@router.post("/configs"',
        '@router.put("/configs/{config_id}"',
        '@router.delete("/configs/{config_id}"',
        '@router.post("/configs/{config_id}/run"',
        '@router.post("/configs/{config_id}/reconcile"',
    )
    for decorator in split_route_decorators:
        assert decorator not in connectors_source
        assert decorator in split_source


def test_connectors_router_still_exposes_config_routes() -> None:
    from app.api.v1.connectors import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/configs", ("GET",)) in routes
    assert ("/configs", ("POST",)) in routes
    assert ("/configs/{config_id}", ("PUT",)) in routes
    assert ("/configs/{config_id}", ("DELETE",)) in routes
    assert ("/configs/{config_id}/run", ("POST",)) in routes
    assert ("/configs/{config_id}/reconcile", ("POST",)) in routes


def test_scheduled_tick_route_is_split_from_connectors_router() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_schedules.py")

    assert "connectors_schedules" in connectors_source
    assert "router.routes.extend(connectors_schedules.router.routes)" in connectors_source

    assert '@router.post("/scheduled/tick"' not in connectors_source
    assert '@router.post("/scheduled/tick"' in split_source


def test_connectors_router_still_exposes_scheduled_tick_route() -> None:
    from app.api.v1.connectors import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/scheduled/tick", ("POST",)) in routes


def test_confluence_helper_cluster_is_split_from_connectors_module() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_confluence.py")

    assert "connectors_confluence" in connectors_source
    assert "_build_confluence_space_run_settings = connectors_confluence._build_confluence_space_run_settings" in connectors_source
    assert "_fetch_confluence_space_listing_page = connectors_confluence._fetch_confluence_space_listing_page" in connectors_source
    assert "def _delta_sync_confluence_documents_acl_by_page_id(" in connectors_source
    assert "return connectors_confluence._delta_sync_confluence_documents_acl_by_page_id(" in connectors_source

    assert "def _build_confluence_space_run_settings(" not in connectors_source
    assert "def _fetch_confluence_space_listing_page(" not in connectors_source

    assert "def _build_confluence_space_run_settings(" in split_source
    assert "async def _fetch_confluence_space_listing_page(" in split_source
    assert "def _delta_sync_confluence_documents_acl_by_page_id(" in split_source


def test_confluence_run_shell_delegates_to_split_module() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_confluence.py")

    assert "async def _execute_confluence_space_run(" in connectors_source
    assert "return await connectors_confluence._execute_confluence_space_run(" in connectors_source
    assert "_process_confluence_space_page_batch = connectors_confluence._process_confluence_space_page_batch" in connectors_source
    assert "_soft_delete_missing_confluence_pages = connectors_confluence._soft_delete_missing_confluence_pages" in connectors_source
    assert "async def _execute_confluence_space_run(" in split_source


def test_jira_helper_cluster_is_split_from_connectors_module() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_jira.py")

    assert "connectors_jira" in connectors_source
    assert "_soft_disable_jira_documents_missing_from_full_sync = connectors_jira._soft_disable_jira_documents_missing_from_full_sync" in connectors_source
    assert "_jira_api_base_url = connectors_jira._jira_api_base_url" in connectors_source
    assert "_jira_render_issue_html = connectors_jira._jira_render_issue_html" in connectors_source
    assert "_build_jira_project_run_settings = connectors_jira._build_jira_project_run_settings" in connectors_source
    assert "_build_jira_project_search_jql = connectors_jira._build_jira_project_search_jql" in connectors_source

    assert "def _soft_disable_jira_documents_missing_from_full_sync(" not in connectors_source
    assert "def _jira_api_base_url(" not in connectors_source
    assert "def _jira_render_issue_html(" not in connectors_source
    assert "def _build_jira_project_run_settings(" not in connectors_source
    assert "def _build_jira_project_search_jql(" not in connectors_source

    assert "def _soft_disable_jira_documents_missing_from_full_sync(" in split_source
    assert "def _jira_api_base_url(" in split_source
    assert "def _jira_render_issue_html(" in split_source
    assert "def _build_jira_project_run_settings(" in split_source
    assert "def _build_jira_project_search_jql(" in split_source


def test_jira_issue_processing_cluster_is_split_from_connectors_module() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_jira.py")

    assert "_process_jira_project_issue = connectors_jira._process_jira_project_issue" in connectors_source
    assert "async def _process_jira_project_issue(" not in connectors_source
    assert "async def _process_jira_project_issue(" in split_source


def test_jira_artifact_runtime_cluster_is_split_from_connectors_module() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_jira.py")

    assert "_jira_attachment_limits = connectors_jira._jira_attachment_limits" in connectors_source
    assert "_ingest_jira_issue_linked_artifacts = connectors_jira._ingest_jira_issue_linked_artifacts" in connectors_source
    assert "_ingest_jira_issue_attachments = connectors_jira._ingest_jira_issue_attachments" in connectors_source
    assert "_initialize_jira_project_run_stats = connectors_jira._initialize_jira_project_run_stats" in connectors_source

    split_defs = (
        "def _jira_attachment_limits(",
        "async def _ingest_jira_issue_linked_artifacts(",
        "async def _ingest_jira_issue_attachments(",
        "def _initialize_jira_project_run_stats(",
    )
    for definition in split_defs:
        assert definition not in connectors_source
        assert definition in split_source


def test_github_repo_runtime_cluster_is_split_from_connectors_module() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_github_repo.py")

    assert "connectors_github_repo" in connectors_source
    assert "_build_github_repo_run_settings = connectors_github_repo._build_github_repo_run_settings" in connectors_source
    assert "_fetch_github_repo_listing_and_acl_keys = connectors_github_repo._fetch_github_repo_listing_and_acl_keys" in connectors_source
    assert "_execute_github_repo_run = connectors_github_repo._execute_github_repo_run" in connectors_source

    split_defs = (
        "def _build_github_repo_run_settings(",
        "async def _fetch_github_repo_listing_and_acl_keys(",
        "async def _execute_github_repo_run(",
    )
    for definition in split_defs:
        assert definition not in connectors_source
        assert definition in split_source


def test_drive_files_runtime_cluster_is_split_from_connectors_module() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_drive_files.py")

    assert "connectors_drive_files" in connectors_source
    assert "_build_drive_files_run_settings = connectors_drive_files._build_drive_files_run_settings" in connectors_source
    assert "_process_drive_files_sources = connectors_drive_files._process_drive_files_sources" in connectors_source
    assert "_execute_drive_files_run = connectors_drive_files._execute_drive_files_run" in connectors_source

    split_defs = (
        "def _build_drive_files_run_settings(",
        "async def _process_drive_files_sources(",
        "async def _execute_drive_files_run(",
    )
    for definition in split_defs:
        assert definition not in connectors_source
        assert definition in split_source


def test_minio_bucket_runtime_cluster_is_split_from_connectors_module() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_minio_bucket.py")

    assert "connectors_minio_bucket" in connectors_source
    assert "_build_minio_bucket_run_settings = connectors_minio_bucket._build_minio_bucket_run_settings" in connectors_source
    assert "_process_minio_bucket_objects = connectors_minio_bucket._process_minio_bucket_objects" in connectors_source
    assert "_execute_minio_bucket_run = connectors_minio_bucket._execute_minio_bucket_run" in connectors_source

    split_defs = (
        "def _build_minio_bucket_run_settings(",
        "async def _process_minio_bucket_objects(",
        "async def _execute_minio_bucket_run(",
    )
    for definition in split_defs:
        assert definition not in connectors_source
        assert definition in split_source


def test_connector_common_helper_cluster_is_split_from_connectors_module() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_common.py")

    assert "connectors_common" in connectors_source
    assert "_safe_error_str = connectors_common._safe_error_str" in connectors_source
    assert "_append_connector_error = connectors_common._append_connector_error" in connectors_source
    assert "_finalize_connector_stats = connectors_common._finalize_connector_stats" in connectors_source
    assert "_connector_run_completion_status = connectors_common._connector_run_completion_status" in connectors_source

    split_defs = (
        "def _safe_error_str(",
        "def _connector_error_code_from_message(",
        "def _classify_connector_error(",
        "def _append_unique_limited(",
        "def _stats_list(",
        "def _get_or_create_error_group(",
        "def _append_connector_error(",
        "def _finalize_connector_stats(",
        "def _connector_run_completion_status(",
        "def _connector_config_id_from_run(",
    )
    for definition in split_defs:
        assert definition not in connectors_source
        assert definition in split_source


def test_connector_external_helper_cluster_is_split_from_connectors_module() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_external.py")

    assert "connectors_external" in connectors_source
    assert "_build_auth_headers = connectors_external._build_auth_headers" in connectors_source
    assert "_extract_drive_file_id = connectors_external._extract_drive_file_id" in connectors_source
    assert "_drive_fetch_file_permissions = connectors_external._drive_fetch_file_permissions" in connectors_source
    assert "_github_fetch_repo_team_principal_keys = connectors_external._github_fetch_repo_team_principal_keys" in connectors_source
    assert "_resolve_tenant_group_ids_by_external_id = connectors_external._resolve_tenant_group_ids_by_external_id" in connectors_source

    split_defs = (
        "def _build_auth_headers(",
        "def _build_basic_auth_header(",
        "def _is_http_or_https_url(",
        "def _is_link_href_allowed(",
        "def _extract_drive_file_id(",
        "def _drive_direct_download_url(",
        "def _drive_source_ref(",
        "def _drive_fallback_sync_token(",
        "async def _drive_fetch_file_sync_token(",
        "def _drive_group_principal_key(",
        "def _drive_permission_external_ids_and_anyone(",
        "async def _drive_fetch_file_permissions(",
        "def _github_raw_url(",
        "def _github_team_principal_key(",
        "def _parse_link_header_next(",
        "def _github_team_principal_key_from_repo_team_item(",
        "async def _github_fetch_repo_team_principal_keys(",
        "def _resolve_tenant_group_ids_by_external_id(",
    )
    for definition in split_defs:
        assert definition not in connectors_source
        assert definition in split_source


def test_connector_state_helper_cluster_is_split_from_connectors_module() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_state.py")

    assert "connectors_state" in connectors_source
    assert "_unknown_tenant_groups = connectors_state._unknown_tenant_groups" in connectors_source
    assert "_fetch_connector_run_acl_summaries = connectors_state._fetch_connector_run_acl_summaries" in connectors_source
    assert "_run_out = connectors_state._run_out" in connectors_source
    assert "_config_out = connectors_state._config_out" in connectors_source
    assert "_schedule_due = connectors_state._schedule_due" in connectors_source
    assert "_sync_connector_config_from_run = connectors_state._sync_connector_config_from_run" in connectors_source

    split_defs = (
        "def _unknown_tenant_groups(",
        "def _normalize_doc_access_mode(",
        "def _fetch_connector_run_acl_summaries(",
        "def _run_out(",
        "def _config_out(",
        "def _schedule_elapsed_seconds(",
        "def _schedule_positive_int(",
        "def _schedule_interval_from_parts(",
        "def _schedule_interval_seconds(",
        "def _schedule_due(",
        "def _sync_connector_config_from_run(",
    )
    for definition in split_defs:
        assert definition not in connectors_source
        assert definition in split_source


def test_connector_acl_helper_cluster_is_split_from_connectors_module() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_acl.py")

    assert "connectors_acl" in connectors_source
    assert "_apply_document_access_from_config = connectors_acl._apply_document_access_from_config" in connectors_source
    assert "_delta_sync_connector_documents_acl_by_source_url = connectors_acl._delta_sync_connector_documents_acl_by_source_url" in connectors_source
    assert "_soft_disable_connector_documents_by_source_ref = connectors_acl._soft_disable_connector_documents_by_source_ref" in connectors_source
    assert "_delta_sync_jira_documents_acl_by_issue_url = connectors_acl._delta_sync_jira_documents_acl_by_issue_url" in connectors_source
    assert "_soft_disable_jira_attachment_documents_missing_from_issue = connectors_acl._soft_disable_jira_attachment_documents_missing_from_issue" in connectors_source
    assert "_soft_disable_jira_linked_artifact_documents_missing_from_issue = connectors_acl._soft_disable_jira_linked_artifact_documents_missing_from_issue" in connectors_source

    split_defs = (
        "def _apply_document_access_from_config(",
        "def _delta_sync_connector_documents_acl_by_source_url(",
        "def _soft_disable_connector_documents_by_source_url(",
        "def _soft_disable_connector_documents_by_source_ref(",
        "def _delta_sync_jira_documents_acl_by_issue_url(",
        "def _soft_disable_jira_attachment_documents_missing_from_issue(",
        "def _soft_disable_jira_linked_artifact_documents_missing_from_issue(",
    )
    for definition in split_defs:
        assert definition not in connectors_source
        assert definition in split_source


def test_connector_artifact_helper_cluster_is_split_from_connectors_module() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_artifacts.py")

    assert "connectors_artifacts" in connectors_source
    assert "_apply_connector_identity_metadata = connectors_artifacts._apply_connector_identity_metadata" in connectors_source
    assert "_normalize_connector_string_list = connectors_artifacts._normalize_connector_string_list" in connectors_source
    assert "_db_row_sidecar_file_path = connectors_artifacts._db_row_sidecar_file_path" in connectors_source
    assert "_upsert_db_row_sidecar_document = connectors_artifacts._upsert_db_row_sidecar_document" in connectors_source

    split_defs = (
        "def _apply_connector_identity_metadata(",
        "def _normalize_connector_string_list(",
        "def _normalize_connector_principal_list(",
        "def _db_row_sidecar_file_path(",
        "def _db_row_sidecar_filename(",
        "def _build_db_row_source_manifest(",
        "def _upsert_db_row_sidecar_document(",
    )
    for definition in split_defs:
        assert definition not in connectors_source
        assert definition in split_source
