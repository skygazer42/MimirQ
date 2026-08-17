"""
Connector API (enterprise ingestion framework).

This is a minimal v1 implementation focused on:
- URL batch ingestion as the first connector
- Run tracking (status/stats/error)
"""

import importlib
import sys
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.api.v1 import (
    connectors_acl,
    connectors_artifacts,
    connectors_catalog,
    connectors_common,
    connectors_confluence,
    connectors_db_catalog,
    connectors_drive_files,
    connectors_external,
    connectors_github_plan,
    connectors_github_repo,
    connectors_jira,
    connectors_minio_bucket,
    connectors_state,
    connectors_url_batch,
    connectors_validation,
    connectors_web_crawl,
    connectors_web_crawl_plan,
)
from app.api.v1.connectors_validation import validate_connector_config as validate_connector_config
from app.api.v1.documents import (
    _ingest_url_upload_request as _ingest_url_upload_request,
)
from app.api.v1.documents import (
    _resolve_writable_dataset as _resolve_writable_dataset,
)
from app.core.config import settings as settings
from app.core.database import SessionLocal as SessionLocal
from app.core.secrets import (
    decrypt_connector_config_secrets as decrypt_connector_config_secrets,
)
from app.core.secrets import (
    encrypt_connector_config_secrets as encrypt_connector_config_secrets,
)
from app.services.audit_log_service import audit_log_event as audit_log_event
from app.services.connector_reconcile_service import (
    plan_connector_reconcile as plan_connector_reconcile,
)
from app.services.connector_reconcile_service import (
    resolve_connector_reconcile_source_refs as resolve_connector_reconcile_source_refs,
)
from app.services.connector_registry import get_connector_definition as get_connector_definition
from app.services.connector_sync_state import (
    build_persisted_state as build_persisted_state,
)
from app.services.connector_sync_state import (
    get_resume_cursor as get_resume_cursor,
)
from app.services.connector_sync_state import (
    normalize_source_manifest as normalize_source_manifest,
)
from app.services.dataset_service import DatasetService as DatasetService
from app.tasks.queue import enqueue_connector_run as enqueue_connector_run
from app.tasks.queue import get_queue as get_queue

_THIS_MODULE = sys.modules[__name__]
connectors_acl._leader_module = _THIS_MODULE
connectors_artifacts._leader_module = _THIS_MODULE
connectors_confluence._leader_module = _THIS_MODULE
connectors_state._leader_module = _THIS_MODULE
connectors_drive_files._leader_module = _THIS_MODULE
connectors_github_repo._leader_module = _THIS_MODULE
connectors_jira._leader_module = _THIS_MODULE
connectors_minio_bucket._leader_module = _THIS_MODULE
connectors_web_crawl._leader_module = _THIS_MODULE

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

_router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
_router.routes.extend(connectors_catalog.router.routes)
_router.routes.extend(connectors_validation.router.routes)
_DB_CONNECTOR_IDS = {"mysql_catalog", "sqlserver_catalog"}
URL_SHA256_PREFIX = "url_sha256:"
CONNECTOR_CONFIG_NOT_FOUND_DETAIL = "Connector config not found"
JIRA_UPDATED_SOURCE = "connector:jira:updated"
UNSUPPORTED_CONNECTOR_ID_DETAIL = "Unsupported connector_id"
URL_INGEST_DISABLED_DETAIL = "URL ingestion is disabled"
CONNECTOR_RUN_NOT_FOUND_DETAIL = "Connector run not found"

_get_db_catalog_run = connectors_db_catalog._get_db_catalog_run
_mark_db_catalog_run_running = connectors_db_catalog._mark_db_catalog_run_running
_db_catalog_connector_config_id = connectors_db_catalog._db_catalog_connector_config_id
_build_db_catalog_run_context = connectors_db_catalog._build_db_catalog_run_context
_run_db_catalog_sync = connectors_db_catalog._run_db_catalog_sync
_emit_db_catalog_sync_completed = connectors_db_catalog._emit_db_catalog_sync_completed
_emit_db_catalog_schema_doc_completed = connectors_db_catalog._emit_db_catalog_schema_doc_completed
_attach_db_catalog_schema_doc = connectors_db_catalog._attach_db_catalog_schema_doc
_db_catalog_row_sync_settings = connectors_db_catalog._db_catalog_row_sync_settings
_attach_db_catalog_row_sync = connectors_db_catalog._attach_db_catalog_row_sync
_nested_diff_count = connectors_db_catalog._nested_diff_count
_db_catalog_schema_diff_counts = connectors_db_catalog._db_catalog_schema_diff_counts
_emit_db_catalog_completion_audit = connectors_db_catalog._emit_db_catalog_completion_audit
_finalize_db_catalog_run_success = connectors_db_catalog._finalize_db_catalog_run_success
_emit_db_catalog_sync_failed = connectors_db_catalog._emit_db_catalog_sync_failed
_emit_db_catalog_failure_audit = connectors_db_catalog._emit_db_catalog_failure_audit
_mark_db_catalog_run_failed = connectors_db_catalog._mark_db_catalog_run_failed
_execute_db_catalog_run = connectors_db_catalog._execute_db_catalog_run
_safe_error_str = connectors_common._safe_error_str
_connector_error_code_from_message = connectors_common._connector_error_code_from_message
_classify_connector_error = connectors_common._classify_connector_error
_append_unique_limited = connectors_common._append_unique_limited
_stats_list = connectors_common._stats_list
_get_or_create_error_group = connectors_common._get_or_create_error_group
_append_connector_error = connectors_common._append_connector_error
_finalize_connector_stats = connectors_common._finalize_connector_stats
_connector_run_completion_status = connectors_common._connector_run_completion_status
_connector_config_id_from_run = connectors_common._connector_config_id_from_run
_build_auth_headers = connectors_external._build_auth_headers
_build_basic_auth_header = connectors_external._build_basic_auth_header
_is_http_or_https_url = connectors_external._is_http_or_https_url
_is_link_href_allowed = connectors_external._is_link_href_allowed
_extract_drive_file_id = connectors_external._extract_drive_file_id
_drive_direct_download_url = connectors_external._drive_direct_download_url
_drive_source_ref = connectors_external._drive_source_ref
_drive_fallback_sync_token = connectors_external._drive_fallback_sync_token
_drive_fetch_file_sync_token = connectors_external._drive_fetch_file_sync_token
_drive_group_principal_key = connectors_external._drive_group_principal_key
_drive_permission_external_ids_and_anyone = connectors_external._drive_permission_external_ids_and_anyone
_drive_fetch_file_permissions = connectors_external._drive_fetch_file_permissions
_github_raw_url = connectors_external._github_raw_url
_github_team_principal_key = connectors_external._github_team_principal_key
_parse_link_header_next = connectors_external._parse_link_header_next
_github_team_principal_key_from_repo_team_item = connectors_external._github_team_principal_key_from_repo_team_item
_github_fetch_repo_team_principal_keys = connectors_external._github_fetch_repo_team_principal_keys
_resolve_tenant_group_ids_by_external_id = connectors_external._resolve_tenant_group_ids_by_external_id
_unknown_tenant_groups = connectors_state._unknown_tenant_groups
_normalize_doc_access_mode = connectors_state._normalize_doc_access_mode
_fetch_connector_run_acl_summaries = connectors_state._fetch_connector_run_acl_summaries
_run_out = connectors_state._run_out
_config_out = connectors_state._config_out
_schedule_elapsed_seconds = connectors_state._schedule_elapsed_seconds
_schedule_positive_int = connectors_state._schedule_positive_int
_schedule_interval_from_parts = connectors_state._schedule_interval_from_parts
_schedule_interval_seconds = connectors_state._schedule_interval_seconds
_schedule_due = connectors_state._schedule_due
_sync_connector_config_from_run = connectors_state._sync_connector_config_from_run
_apply_document_access_from_config = connectors_acl._apply_document_access_from_config
_delta_sync_connector_documents_acl_by_source_url = connectors_acl._delta_sync_connector_documents_acl_by_source_url
_soft_disable_connector_documents_by_source_url = connectors_acl._soft_disable_connector_documents_by_source_url
_soft_disable_connector_documents_by_source_ref = connectors_acl._soft_disable_connector_documents_by_source_ref
_delta_sync_jira_documents_acl_by_issue_url = connectors_acl._delta_sync_jira_documents_acl_by_issue_url
_soft_disable_jira_attachment_documents_missing_from_issue = (
    connectors_acl._soft_disable_jira_attachment_documents_missing_from_issue
)
_soft_disable_jira_linked_artifact_documents_missing_from_issue = (
    connectors_acl._soft_disable_jira_linked_artifact_documents_missing_from_issue
)
_apply_connector_identity_metadata = connectors_artifacts._apply_connector_identity_metadata
_normalize_connector_string_list = connectors_artifacts._normalize_connector_string_list
_normalize_connector_principal_list = connectors_artifacts._normalize_connector_principal_list
_db_row_sidecar_file_path = connectors_artifacts._db_row_sidecar_file_path
_db_row_sidecar_filename = connectors_artifacts._db_row_sidecar_filename
_build_db_row_source_manifest = connectors_artifacts._build_db_row_source_manifest
_upsert_db_row_sidecar_document = connectors_artifacts._upsert_db_row_sidecar_document
_get_url_batch_run = connectors_url_batch._get_url_batch_run
_mark_url_batch_run_running = connectors_url_batch._mark_url_batch_run_running
_build_url_batch_run_settings = connectors_url_batch._build_url_batch_run_settings
_url_batch_processed_refs = connectors_url_batch._url_batch_processed_refs
_url_batch_document_ids = connectors_url_batch._url_batch_document_ids
_build_url_batch_run_state = connectors_url_batch._build_url_batch_run_state
_url_batch_run_cancelled = connectors_url_batch._url_batch_run_cancelled
_ingest_url_batch_url = connectors_url_batch._ingest_url_batch_url
_persist_url_batch_progress = connectors_url_batch._persist_url_batch_progress
_process_url_batch_urls = connectors_url_batch._process_url_batch_urls
_finalize_cancelled_url_batch_run = connectors_url_batch._finalize_cancelled_url_batch_run
_finalize_url_batch_run_success = connectors_url_batch._finalize_url_batch_run_success
_mark_url_batch_run_failed = connectors_url_batch._mark_url_batch_run_failed
_execute_url_batch_run = connectors_url_batch._execute_url_batch_run
_github_repo_path_is_included = connectors_github_plan._github_repo_path_is_included
_github_repo_listed_files_and_observed_paths = connectors_github_plan._github_repo_listed_files_and_observed_paths
_github_repo_delta_files = connectors_github_plan._github_repo_delta_files
_build_github_repo_execution_plan = connectors_github_plan._build_github_repo_execution_plan
_initialize_github_repo_run_stats = connectors_github_plan._initialize_github_repo_run_stats
_get_github_repo_run = connectors_github_repo._get_github_repo_run
_mark_github_repo_run_running = connectors_github_repo._mark_github_repo_run_running
_normalize_github_include_set = connectors_github_repo._normalize_github_include_set
_build_github_repo_run_settings = connectors_github_repo._build_github_repo_run_settings
_fetch_github_repo_listing_and_acl_keys = connectors_github_repo._fetch_github_repo_listing_and_acl_keys
_build_github_repo_source_acl_context = connectors_github_repo._build_github_repo_source_acl_context
_github_repo_run_cancelled = connectors_github_repo._github_repo_run_cancelled
_github_repo_effective_access = connectors_github_repo._github_repo_effective_access
_apply_github_repo_source_acl_delta_sync = connectors_github_repo._apply_github_repo_source_acl_delta_sync
_ingest_github_repo_file = connectors_github_repo._ingest_github_repo_file
_persist_github_repo_progress = connectors_github_repo._persist_github_repo_progress
_github_repo_apply_processed_file_success = connectors_github_repo._github_repo_apply_processed_file_success
_process_github_repo_files = connectors_github_repo._process_github_repo_files
_finalize_cancelled_github_repo_run = connectors_github_repo._finalize_cancelled_github_repo_run
_reconcile_removed_github_repo_paths = connectors_github_repo._reconcile_removed_github_repo_paths
_emit_github_repo_source_acl_delta_sync_audit = connectors_github_repo._emit_github_repo_source_acl_delta_sync_audit
_finalize_github_repo_run_success = connectors_github_repo._finalize_github_repo_run_success
_mark_github_repo_run_failed = connectors_github_repo._mark_github_repo_run_failed
_execute_github_repo_run = connectors_github_repo._execute_github_repo_run
_get_drive_files_run = connectors_drive_files._get_drive_files_run
_mark_drive_files_run_running = connectors_drive_files._mark_drive_files_run_running
_build_drive_files_run_settings = connectors_drive_files._build_drive_files_run_settings
_discover_drive_sources = connectors_drive_files._discover_drive_sources
_build_drive_files_execution_plan = connectors_drive_files._build_drive_files_execution_plan
_initialize_drive_files_run_stats = connectors_drive_files._initialize_drive_files_run_stats
_drive_files_run_cancelled = connectors_drive_files._drive_files_run_cancelled
_resolve_drive_source_acl = connectors_drive_files._resolve_drive_source_acl
_ingest_drive_file_source = connectors_drive_files._ingest_drive_file_source
_persist_drive_files_progress = connectors_drive_files._persist_drive_files_progress
_process_drive_files_sources = connectors_drive_files._process_drive_files_sources
_finalize_cancelled_drive_files_run = connectors_drive_files._finalize_cancelled_drive_files_run
_reconcile_removed_drive_sources = connectors_drive_files._reconcile_removed_drive_sources
_emit_drive_files_source_acl_delta_sync_audit = connectors_drive_files._emit_drive_files_source_acl_delta_sync_audit
_finalize_drive_files_run_success = connectors_drive_files._finalize_drive_files_run_success
_mark_drive_files_run_failed = connectors_drive_files._mark_drive_files_run_failed
_execute_drive_files_run = connectors_drive_files._execute_drive_files_run
_get_minio_bucket_run = connectors_minio_bucket._get_minio_bucket_run
_mark_minio_bucket_run_running = connectors_minio_bucket._mark_minio_bucket_run_running
_normalize_minio_include_set = connectors_minio_bucket._normalize_minio_include_set
_minio_connector_config_id = connectors_minio_bucket._minio_connector_config_id
_minio_source_scope_hash = connectors_minio_bucket._minio_source_scope_hash
_minio_object_token = connectors_minio_bucket._minio_object_token
_build_minio_bucket_run_settings = connectors_minio_bucket._build_minio_bucket_run_settings
_list_minio_bucket_objects = connectors_minio_bucket._list_minio_bucket_objects
_minio_object_name_is_included = connectors_minio_bucket._minio_object_name_is_included
_build_minio_bucket_execution_plan = connectors_minio_bucket._build_minio_bucket_execution_plan
_initialize_minio_bucket_run_stats = connectors_minio_bucket._initialize_minio_bucket_run_stats
_minio_bucket_run_cancelled = connectors_minio_bucket._minio_bucket_run_cancelled
_ingest_minio_bucket_object = connectors_minio_bucket._ingest_minio_bucket_object
_persist_minio_bucket_progress = connectors_minio_bucket._persist_minio_bucket_progress
_process_minio_bucket_objects = connectors_minio_bucket._process_minio_bucket_objects
_finalize_cancelled_minio_bucket_run = connectors_minio_bucket._finalize_cancelled_minio_bucket_run
_reconcile_removed_minio_bucket_paths = connectors_minio_bucket._reconcile_removed_minio_bucket_paths
_finalize_minio_bucket_run_success = connectors_minio_bucket._finalize_minio_bucket_run_success
_mark_minio_bucket_run_failed = connectors_minio_bucket._mark_minio_bucket_run_failed
_execute_minio_bucket_run = connectors_minio_bucket._execute_minio_bucket_run
_confluence_api_base_url = connectors_confluence._confluence_api_base_url
_confluence_request = connectors_confluence._confluence_request
_confluence_join_webui = connectors_confluence._confluence_join_webui
_confluence_extract_last_modified = connectors_confluence._confluence_extract_last_modified
_should_skip_timestamp_boundary_item = connectors_confluence._should_skip_timestamp_boundary_item
_advance_timestamp_boundary = connectors_confluence._advance_timestamp_boundary
_confluence_group_principal_key = connectors_confluence._confluence_group_principal_key
_confluence_parse_read_restriction_groups = connectors_confluence._confluence_parse_read_restriction_groups
_confluence_ingest_method = connectors_confluence._confluence_ingest_method
_confluence_attachment_limits = connectors_confluence._confluence_attachment_limits
_confluence_attachment_download_url = connectors_confluence._confluence_attachment_download_url
_confluence_extract_attachments = connectors_confluence._confluence_extract_attachments
_confluence_attachment_connector_metadata = connectors_confluence._confluence_attachment_connector_metadata
_normalize_connector_sync_mode = connectors_confluence._normalize_connector_sync_mode
_resolve_connector_effective_mode = connectors_confluence._resolve_connector_effective_mode
_confluence_source_acl_settings = connectors_confluence._confluence_source_acl_settings
_build_confluence_space_run_settings = connectors_confluence._build_confluence_space_run_settings
_build_confluence_space_search_cql = connectors_confluence._build_confluence_space_search_cql
_initialize_confluence_space_run_stats = connectors_confluence._initialize_confluence_space_run_stats
_confluence_space_run_cancelled = connectors_confluence._confluence_space_run_cancelled
_initialize_confluence_space_progress = connectors_confluence._initialize_confluence_space_progress
_fetch_confluence_space_listing_page = connectors_confluence._fetch_confluence_space_listing_page
_parse_confluence_listing_page = connectors_confluence._parse_confluence_listing_page
_build_confluence_page_filename = connectors_confluence._build_confluence_page_filename
_resolve_confluence_page_acl = connectors_confluence._resolve_confluence_page_acl
_patch_confluence_page_document_metadata = connectors_confluence._patch_confluence_page_document_metadata
_ingest_confluence_page = connectors_confluence._ingest_confluence_page
_patch_confluence_attachment_document_metadata = connectors_confluence._patch_confluence_attachment_document_metadata
_ingest_single_confluence_attachment = connectors_confluence._ingest_single_confluence_attachment
_ingest_confluence_page_attachments = connectors_confluence._ingest_confluence_page_attachments
_persist_confluence_space_progress = connectors_confluence._persist_confluence_space_progress
_process_confluence_space_page_batch = connectors_confluence._process_confluence_space_page_batch
_probe_confluence_space_listing_complete = connectors_confluence._probe_confluence_space_listing_complete
_soft_delete_missing_confluence_pages = connectors_confluence._soft_delete_missing_confluence_pages
_finalize_cancelled_confluence_space_run = connectors_confluence._finalize_cancelled_confluence_space_run
_emit_confluence_source_acl_delta_sync_audit = connectors_confluence._emit_confluence_source_acl_delta_sync_audit
_finalize_confluence_space_run_success = connectors_confluence._finalize_confluence_space_run_success
_mark_confluence_space_run_failed = connectors_confluence._mark_confluence_space_run_failed
_jira_api_base_url = connectors_jira._jira_api_base_url
_jira_request = connectors_jira._jira_request
_jira_extract_issue_updated = connectors_jira._jira_extract_issue_updated
_jira_principal_value = connectors_jira._jira_principal_value
_jira_group_principal_key = connectors_jira._jira_group_principal_key
_jira_role_principal_key = connectors_jira._jira_role_principal_key
_jira_security_level_principal_key = connectors_jira._jira_security_level_principal_key
_jira_issue_acl_principal_keys = connectors_jira._jira_issue_acl_principal_keys
_jira_adf_to_text = connectors_jira._jira_adf_to_text
_jira_adf_is_doc = connectors_jira._jira_adf_is_doc
_jira_adf_text_node_html = connectors_jira._jira_adf_text_node_html
_jira_adf_render_child_nodes = connectors_jira._jira_adf_render_child_nodes
_jira_adf_node_html_paragraph = connectors_jira._jira_adf_node_html_paragraph
_jira_adf_node_html_heading = connectors_jira._jira_adf_node_html_heading
_jira_adf_node_html_blockquote = connectors_jira._jira_adf_node_html_blockquote
_jira_adf_node_html_hr = connectors_jira._jira_adf_node_html_hr
_jira_adf_node_html_bullet_list = connectors_jira._jira_adf_node_html_bullet_list
_jira_adf_node_html_ordered_list = connectors_jira._jira_adf_node_html_ordered_list
_jira_adf_node_html_list_item = connectors_jira._jira_adf_node_html_list_item
_jira_adf_node_html_code_block = connectors_jira._jira_adf_node_html_code_block
_jira_adf_node_html_table = connectors_jira._jira_adf_node_html_table
_jira_adf_node_html_table_row = connectors_jira._jira_adf_node_html_table_row
_jira_adf_node_html_table_cell = connectors_jira._jira_adf_node_html_table_cell
_jira_adf_node_html_table_header = connectors_jira._jira_adf_node_html_table_header
_jira_adf_node_html_inline_card = connectors_jira._jira_adf_node_html_inline_card
_jira_adf_node_html_mention = connectors_jira._jira_adf_node_html_mention
_jira_adf_node_html_emoji = connectors_jira._jira_adf_node_html_emoji
_JIRA_ADF_NODE_HTML_HANDLERS = connectors_jira._JIRA_ADF_NODE_HTML_HANDLERS
_jira_adf_node_to_html = connectors_jira._jira_adf_node_to_html
_jira_adf_to_html = connectors_jira._jira_adf_to_html
_jira_mapping_text = connectors_jira._jira_mapping_text
_jira_value_to_text = connectors_jira._jira_value_to_text
_jira_html_from_value = connectors_jira._jira_html_from_value
_jira_html_from_field = connectors_jira._jira_html_from_field
_jira_issue_url = connectors_jira._jira_issue_url
_soft_disable_jira_documents_missing_from_full_sync = (
    connectors_jira._soft_disable_jira_documents_missing_from_full_sync
)
_jira_jql_updated_after = connectors_jira._jira_jql_updated_after
_jira_issue_fields = connectors_jira._jira_issue_fields
_jira_issue_rendered_fields = connectors_jira._jira_issue_rendered_fields
_jira_issue_field_name = connectors_jira._jira_issue_field_name
_jira_issue_label_text = connectors_jira._jira_issue_label_text
_jira_comment_items = connectors_jira._jira_comment_items
_jira_rendered_comment_items = connectors_jira._jira_rendered_comment_items
_jira_rendered_comment_at = connectors_jira._jira_rendered_comment_at
_jira_comment_meta_html = connectors_jira._jira_comment_meta_html
_jira_render_issue_comment_article = connectors_jira._jira_render_issue_comment_article
_jira_render_issue_comment_articles = connectors_jira._jira_render_issue_comment_articles
_jira_render_custom_field_sections = connectors_jira._jira_render_custom_field_sections
_jira_render_issue_document_preamble = connectors_jira._jira_render_issue_document_preamble
_jira_render_issue_meta_paragraphs = connectors_jira._jira_render_issue_meta_paragraphs
_jira_render_issue_html = connectors_jira._jira_render_issue_html
_build_jira_project_run_settings = connectors_jira._build_jira_project_run_settings
_build_jira_project_search_jql = connectors_jira._build_jira_project_search_jql
_resolve_jira_issue_acl = connectors_jira._resolve_jira_issue_acl
_persist_jira_project_progress = connectors_jira._persist_jira_project_progress
_finalize_cancelled_jira_project_run = connectors_jira._finalize_cancelled_jira_project_run
_finalize_jira_project_run = connectors_jira._finalize_jira_project_run
_build_jira_issue_info = connectors_jira._build_jira_issue_info
_persist_jira_project_skipped_boundary_duplicates = connectors_jira._persist_jira_project_skipped_boundary_duplicates
_process_jira_project_issue = connectors_jira._process_jira_project_issue
_get_jira_project_run = connectors_jira._get_jira_project_run
_mark_jira_project_run_running = connectors_jira._mark_jira_project_run_running
_mark_jira_project_run_failed = connectors_jira._mark_jira_project_run_failed
_jira_attachment_limits = connectors_jira._jira_attachment_limits
_jira_linked_artifact_limits = connectors_jira._jira_linked_artifact_limits
_jira_extract_attachments = connectors_jira._jira_extract_attachments
_jira_extract_urls_from_text = connectors_jira._jira_extract_urls_from_text
_jira_extract_urls_from_adf = connectors_jira._jira_extract_urls_from_adf
_jira_extract_linked_artifact_urls = connectors_jira._jira_extract_linked_artifact_urls
_jira_attachment_connector_metadata = connectors_jira._jira_attachment_connector_metadata
_jira_linked_artifact_connector_metadata = connectors_jira._jira_linked_artifact_connector_metadata
_jira_should_send_auth_headers = connectors_jira._jira_should_send_auth_headers
_patch_jira_linked_artifact_document_metadata = connectors_jira._patch_jira_linked_artifact_document_metadata
_ingest_single_jira_linked_artifact = connectors_jira._ingest_single_jira_linked_artifact
_jira_project_run_cancelled = connectors_jira._jira_project_run_cancelled
_ingest_jira_issue_linked_artifacts = connectors_jira._ingest_jira_issue_linked_artifacts
_patch_jira_attachment_document_metadata = connectors_jira._patch_jira_attachment_document_metadata
_ingest_single_jira_attachment = connectors_jira._ingest_single_jira_attachment
_ingest_jira_issue_attachments = connectors_jira._ingest_jira_issue_attachments
_initialize_jira_project_run_stats = connectors_jira._initialize_jira_project_run_stats
_jira_project_search_params = connectors_jira._jira_project_search_params
_jira_project_parse_search_payload = connectors_jira._jira_project_parse_search_payload
_jira_project_fetch_issue_page = connectors_jira._jira_project_fetch_issue_page
_process_jira_project_issues = connectors_jira._process_jira_project_issues
_web_crawl_content_fingerprint = connectors_web_crawl_plan._web_crawl_content_fingerprint
_web_crawl_token_is_content_aware = connectors_web_crawl_plan._web_crawl_token_is_content_aware
_web_crawl_manifest_token_changed = connectors_web_crawl_plan._web_crawl_manifest_token_changed
_web_crawl_extract_token_part = connectors_web_crawl_plan._web_crawl_extract_token_part
_web_crawl_build_doc_sync_token = connectors_web_crawl_plan._web_crawl_build_doc_sync_token
_web_crawl_source_manifest = connectors_web_crawl_plan._web_crawl_source_manifest
_build_web_crawl_execution_plan = connectors_web_crawl_plan._build_web_crawl_execution_plan
_initialize_web_crawl_run_stats = connectors_web_crawl_plan._initialize_web_crawl_run_stats
_build_web_crawl_run_settings = connectors_web_crawl._build_web_crawl_run_settings
_get_web_crawl_run = connectors_web_crawl._get_web_crawl_run
_mark_web_crawl_run_running = connectors_web_crawl._mark_web_crawl_run_running
_web_crawl_run_cancelled = connectors_web_crawl._web_crawl_run_cancelled
_ingest_web_crawl_url = connectors_web_crawl._ingest_web_crawl_url
_persist_web_crawl_progress = connectors_web_crawl._persist_web_crawl_progress
_process_web_crawl_urls = connectors_web_crawl._process_web_crawl_urls
_finalize_cancelled_web_crawl_run = connectors_web_crawl._finalize_cancelled_web_crawl_run
_reconcile_removed_web_crawl_urls = connectors_web_crawl._reconcile_removed_web_crawl_urls
_finalize_web_crawl_run_success = connectors_web_crawl._finalize_web_crawl_run_success
_mark_web_crawl_run_failed = connectors_web_crawl._mark_web_crawl_run_failed


def _now() -> datetime:
    return datetime.now(UTC)


async def _execute_web_crawl_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    connectors_web_crawl._leader_module = _THIS_MODULE
    return await connectors_web_crawl._execute_web_crawl_run(
        run_id=run_id,
        tenant_id=tenant_id,
        requested_by=requested_by,
    )


def _delta_sync_confluence_documents_acl_by_page_id(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    base_url: str,
    space_key: str,
    page_id: str,
    requested_by: str,
    access: dict | None,
    acl_provenance: dict | None,
    max_docs_scan: int = 5000,
) -> int:
    connectors_confluence._leader_module = _THIS_MODULE
    return connectors_confluence._delta_sync_confluence_documents_acl_by_page_id(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        base_url=base_url,
        space_key=space_key,
        page_id=page_id,
        requested_by=requested_by,
        access=access,
        acl_provenance=acl_provenance,
        max_docs_scan=max_docs_scan,
    )


async def _execute_jira_project_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    connectors_jira._leader_module = _THIS_MODULE
    return await connectors_jira._execute_jira_project_run(
        run_id=run_id,
        tenant_id=tenant_id,
        requested_by=requested_by,
    )


async def _execute_confluence_space_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    connectors_confluence._leader_module = _THIS_MODULE
    return await connectors_confluence._execute_confluence_space_run(
        run_id=run_id,
        tenant_id=tenant_id,
        requested_by=requested_by,
    )


_ROUTE_MODULE_NAMES = (
    "app.api.v1.connectors_runs",
    "app.api.v1.connectors_configs",
    "app.api.v1.connectors_schedules",
)
_ROUTES_ASSEMBLED = False
_COMPAT_EXPORT_MODULES = {
    "cancel_connector_run": _ROUTE_MODULE_NAMES[0],
    "create_connector_run": _ROUTE_MODULE_NAMES[0],
    "get_connector_run": _ROUTE_MODULE_NAMES[0],
    "list_connector_runs": _ROUTE_MODULE_NAMES[0],
    "_build_retry_failed_run_config": _ROUTE_MODULE_NAMES[0],
    "_connector_run_has_abortable_task": _ROUTE_MODULE_NAMES[0],
    "_get_queue_or_none": _ROUTE_MODULE_NAMES[0],
    "_load_arq_job_class": _ROUTE_MODULE_NAMES[0],
    "resume_connector_run": _ROUTE_MODULE_NAMES[0],
    "retry_failed_connector_run": _ROUTE_MODULE_NAMES[0],
    "create_connector_config": _ROUTE_MODULE_NAMES[1],
    "delete_connector_config": _ROUTE_MODULE_NAMES[1],
    "list_connector_configs": _ROUTE_MODULE_NAMES[1],
    "reconcile_connector_config": _ROUTE_MODULE_NAMES[1],
    "run_connector_config": _ROUTE_MODULE_NAMES[1],
    "update_connector_config": _ROUTE_MODULE_NAMES[1],
    "scheduled_tick": _ROUTE_MODULE_NAMES[2],
}


def _assembled_router() -> APIRouter:
    global _ROUTES_ASSEMBLED
    if _ROUTES_ASSEMBLED:
        return _router

    connectors_runs = importlib.import_module(_ROUTE_MODULE_NAMES[0])
    connectors_configs = importlib.import_module(_ROUTE_MODULE_NAMES[1])
    connectors_schedules = importlib.import_module(_ROUTE_MODULE_NAMES[2])
    _router.routes.extend(connectors_runs.router.routes)
    _router.routes.extend(connectors_configs.router.routes)
    _router.routes.extend(connectors_schedules.router.routes)
    _ROUTES_ASSEMBLED = True
    return _router


def __getattr__(name: str):
    if name == "router":
        value = _assembled_router()
    elif module_name := _COMPAT_EXPORT_MODULES.get(name):
        value = getattr(importlib.import_module(module_name), name)
    elif name in {"connectors_runs", "connectors_configs", "connectors_schedules"}:
        value = importlib.import_module(f"app.api.v1.{name}")
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value
