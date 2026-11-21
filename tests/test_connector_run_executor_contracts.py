import asyncio
import os
import subprocess
import sys
from uuid import uuid4

import pytest

from app.services.connectors import executor as connector_run_executor


@pytest.mark.parametrize(
    ("connector_id", "executor_name"),
    [
        ("url_batch", "_execute_url_batch"),
        ("web_crawl", "_execute_web_crawl"),
        ("minio_bucket", "_execute_minio_bucket"),
        ("confluence_space", "_execute_confluence_space"),
        ("jira_project", "_execute_jira_project"),
        ("mysql_catalog", "_execute_db_catalog"),
        ("sqlserver_catalog", "_execute_db_catalog"),
    ],
)
def test_connector_executor_resolves_direct_service_operation(connector_id, executor_name) -> None:
    assert connector_run_executor._resolve_connector_executor(connector_id) is getattr(
        connector_run_executor, executor_name
    )


@pytest.mark.parametrize("connector_id", ["unsupported_connector", "github_repo", "drive_files"])
def test_unsupported_connector_executor_keeps_false_contract(connector_id: str) -> None:
    result = asyncio.run(
        connector_run_executor.execute_connector_run(
            connector_id=connector_id,
            run_id=uuid4(),
            tenant_id=uuid4(),
            requested_by="operator",
        )
    )
    assert result is False


def test_configured_source_acl_mapping_uses_tenant_group_allowlist() -> None:
    from app.services.connectors.document_access import resolve_configured_source_access

    group_id = uuid4()
    access, mapped = resolve_configured_source_access(
        source_system="confluence",
        source_acl_config={
            "mode": "inherit",
            "group_mappings": [
                {
                    "source": {"system": "confluence", "kind": "group", "id": "platform"},
                    "group_id": str(group_id),
                }
            ],
            "fallback_mode": "partial_members",
        },
        principal_keys=["confluence:group:platform"],
    )

    assert access == {"mode": "partial_members", "partial_group_list": [str(group_id)]}
    assert mapped == {group_id}


def test_confluence_executor_uses_explicit_source_acl_group_mapping() -> None:
    from app.services.connectors.execution import confluence

    group_id = uuid4()
    access, mapped, fallback = confluence._resolve_confluence_acl_access_from_principals(
        object(),
        tenant_id=uuid4(),
        ext_ids=["confluence:group:space-readers"],
        settings_map={
            "source_acl": {
                "mode": "inherit",
                "fallback_mode": "only_me",
                "group_mappings": [
                    {
                        "source": {"system": "confluence", "kind": "group", "id": "space-readers"},
                        "group_id": str(group_id),
                    }
                ],
            },
            "source_acl_fallback_mode": "only_me",
        },
    )

    assert access == {"mode": "partial_members", "partial_group_list": [str(group_id)]}
    assert mapped == {group_id}
    assert fallback is False


def test_jira_executor_uses_explicit_source_acl_group_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.connectors.execution import jira

    group_id = uuid4()
    monkeypatch.setattr(jira, "_delta_sync_jira_documents_acl_by_issue_url", lambda *_args, **_kwargs: 0)
    effective_access, _provenance, updated = jira._resolve_jira_issue_acl(
        object(),
        tenant_id=uuid4(),
        run_id=uuid4(),
        requested_by="operator",
        run=type("RunFixture", (), {"dataset_id": uuid4()})(),
        issue={"fields": {"security": {"id": "10001"}}},
        issue_info={"issue_url": "https://jira.example/browse/ABC-1"},
        settings_map={
            "base_url": "https://jira.example",
            "project_key": "ABC",
            "enable_source_acl": True,
            "include_comments": False,
            "max_comments_per_issue": 0,
            "source_acl_mode": "inherit",
            "source_acl_fallback_mode": "only_me",
            "source_acl": {
                "mode": "inherit",
                "fallback_mode": "only_me",
                "group_mappings": [
                    {
                        "source": {"system": "jira", "kind": "policy", "id": "security-level/10001"},
                        "group_id": str(group_id),
                    }
                ],
            },
        },
    )

    assert effective_access == {"mode": "partial_members", "partial_group_list": [str(group_id)]}
    assert updated == 0


def test_connector_execution_modules_import_without_connector_api_facade() -> None:
    code = """
import importlib
import importlib.abc
import sys

blocked = ("app.api.v1.connectors", "app.api.v1.connectors_")

class NoConnectorApi(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == prefix or (prefix.endswith("_") and fullname.startswith(prefix)) for prefix in blocked):
            raise AssertionError(f"connector service imported API module: {fullname}")

sys.meta_path.insert(0, NoConnectorApi())
modules = (
    "url_batch", "web_crawl", "minio_bucket",
    "confluence", "jira", "db_catalog",
)
for name in modules:
    module = importlib.import_module(f"app.services.connectors.execution.{name}")
    assert callable(module.execute)
assert importlib.import_module("app.services.connectors.executor")._resolve_connector_executor("url_batch")
for module_name in (
    "app.services.connectors.runs",
    "app.services.connectors.configs",
    "app.services.connectors.schedules",
):
    importlib.import_module(module_name)
assert not any(name == "app.api.v1.connectors" or name.startswith("app.api.v1.connectors_") for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
