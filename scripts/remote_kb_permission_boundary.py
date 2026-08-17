#!/usr/bin/env python3
"""Verify permission-sensitive knowledge-base boundaries against a live API."""

import argparse
import json
import sys
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"


def ensure_repo_root_on_sys_path(script_path: str | Path) -> str:
    repo_root = str(Path(script_path).resolve().parents[1])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    return repo_root


@dataclass(frozen=True)
class RuntimeDeps:
    live_api_cls: Any
    citation_document_ids_fn: Any
    ensure_success_fn: Any
    evaluate_boundary_case_fn: Any
    exported_document_ids_fn: Any
    make_fixture_files_fn: Any
    parsed_text_from_response_fn: Any
    record_step_fn: Any
    response_text_from_body_fn: Any
    wait_for_document_completed_fn: Any
    force_member_role_via_docker_fn: Any


@lru_cache(maxsize=1)
def get_runtime_deps() -> RuntimeDeps:
    ensure_repo_root_on_sys_path(__file__)
    from scripts.remote_kb_boundary_matrix import (
        LiveApi,
        citation_document_ids,
        ensure_success,
        evaluate_boundary_case,
        exported_document_ids,
        make_fixture_files,
        parsed_text_from_response,
        record_step,
        response_text_from_body,
        wait_for_document_completed,
    )
    from scripts.remote_permission_matrix import force_member_role_via_docker

    return RuntimeDeps(
        live_api_cls=LiveApi,
        citation_document_ids_fn=citation_document_ids,
        ensure_success_fn=ensure_success,
        evaluate_boundary_case_fn=evaluate_boundary_case,
        exported_document_ids_fn=exported_document_ids,
        make_fixture_files_fn=make_fixture_files,
        parsed_text_from_response_fn=parsed_text_from_response,
        record_step_fn=record_step,
        response_text_from_body_fn=response_text_from_body,
        wait_for_document_completed_fn=wait_for_document_completed,
        force_member_role_via_docker_fn=force_member_role_via_docker,
    )


def build_live_api(*args: Any) -> Any:
    return get_runtime_deps().live_api_cls(*args)


def citation_document_ids(body: Any) -> list[str]:
    return get_runtime_deps().citation_document_ids_fn(body)


def ensure_success(name: str, resp: Any) -> None:
    get_runtime_deps().ensure_success_fn(name, resp)


def evaluate_boundary_case(
    case: dict[str, Any],
    *,
    citation_doc_ids: list[str],
    citation_count: int,
    response_text: str,
) -> list[str]:
    return get_runtime_deps().evaluate_boundary_case_fn(
        case,
        citation_doc_ids=citation_doc_ids,
        citation_count=citation_count,
        response_text=response_text,
    )


def exported_document_ids(body: Any) -> list[str]:
    return get_runtime_deps().exported_document_ids_fn(body)


def make_fixture_files(path: Path) -> dict[str, Path]:
    return get_runtime_deps().make_fixture_files_fn(path)


def parsed_text_from_response(body: Any) -> str:
    return get_runtime_deps().parsed_text_from_response_fn(body)


def record_step(steps: list[dict[str, Any]], name: str, resp: Any, **extra: Any) -> None:
    get_runtime_deps().record_step_fn(steps, name, resp, **extra)


def response_text_from_body(body: Any) -> str:
    return get_runtime_deps().response_text_from_body_fn(body)


def wait_for_document_completed(
    api: Any,
    *,
    steps: list[dict[str, Any]],
    filename: str,
    document_id: str,
    poll_timeout: int,
) -> dict[str, Any]:
    return get_runtime_deps().wait_for_document_completed_fn(
        api,
        steps=steps,
        filename=filename,
        document_id=document_id,
        poll_timeout=poll_timeout,
    )


def force_member_role_via_docker(**kwargs: Any) -> tuple[bool, str]:
    return get_runtime_deps().force_member_role_via_docker_fn(**kwargs)


def evaluate_http_expectation(
    name: str,
    status: int,
    expected_statuses: list[int],
) -> list[str]:
    allowed = {int(item) for item in (expected_statuses or [])}
    if int(status) in allowed:
        return []
    return [f"{name}: expected_statuses={sorted(allowed)} actual={int(status)}"]


def evaluate_permission_scope_case(
    case: dict[str, Any],
    *,
    citation_doc_ids: list[str],
    citation_count: int,
    response_text: str,
) -> list[str]:
    return evaluate_boundary_case(
        case,
        citation_doc_ids=citation_doc_ids,
        citation_count=citation_count,
        response_text=response_text,
    )


def group_id_from_body(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    return str(body.get("id") or body.get("group_id") or "").strip()


def group_member_ids_from_body(body: Any) -> list[str]:
    if not isinstance(body, dict):
        return []
    rows = body.get("items")
    if not isinstance(rows, list):
        return []
    out: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get("user_id") or "").strip()
        if text:
            out.append(text)
    return out


def _normalized_text_list(values: Any) -> list[str]:
    return [text for item in (values or []) if (text := str(item).strip())]


def document_access_summary(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {
            "mode": "",
            "owner_id": None,
            "partial_member_list": [],
            "partial_group_list": [],
        }
    return {
        "mode": str(body.get("mode") or "").strip().lower(),
        "owner_id": str(body.get("owner_id") or "").strip() or None,
        "partial_member_list": _normalized_text_list(body.get("partial_member_list")),
        "partial_group_list": _normalized_text_list(body.get("partial_group_list")),
    }


def _response_id(resp: Any, *keys: str) -> str:
    body = resp.body if hasattr(resp, "body") else None
    if not isinstance(body, dict):
        return ""
    for key in keys:
        value = str(body.get(key) or "").strip()
        if value:
            return value
    return ""


def create_dataset(
    api: Any,
    *,
    steps: list[dict[str, Any]],
    name: str,
    permission: str,
    partial_member_list: list[str] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "name": name,
        "description": f"KB permission boundary dataset: {name}",
        "permission": permission,
        "default_parser_backend": "auto",
        "default_chunk_strategy": "langchain_recursive",
        "pipeline": {
            "governance_enabled": True,
            "persist_parsed_content": True,
            "persist_parsed_content_max_chars": 200000,
            "chunk_size": 1200,
            "chunk_overlap": 120,
            "chunk_vector_enabled": True,
            "bm25_index_enabled": True,
            "kg_enabled": False,
            "event_vector_enabled": False,
            "entity_vector_enabled": False,
        },
        "rag_defaults": {
            "top_k": 4,
            "score_threshold": 0.0,
            "retrieval_mode": "keyword",
            "enable_reranker": False,
            "enable_multi_query": False,
            "enable_hyde": False,
            "enable_query_decomposition": False,
        },
    }
    if partial_member_list is not None:
        payload["partial_member_list"] = list(partial_member_list)
    resp = api.json("POST", "/api/v1/datasets/", payload=payload)
    record_step(steps, f"create_dataset:{name}", resp)
    ensure_success(f"create_dataset:{name}", resp)
    dataset_id = _response_id(resp, "id", "dataset_id")
    if not dataset_id:
        raise RuntimeError(f"create_dataset:{name} missing dataset id")
    return dataset_id


def _chunk_count_from_body(body: Any) -> int:
    if not isinstance(body, dict):
        return 0
    rows = body.get("items") or body.get("chunks") or []
    return len(rows)


def upload_fixture(
    api: Any,
    *,
    steps: list[dict[str, Any]],
    dataset_id: str,
    label: str,
    file_path: Path,
    poll_timeout: int,
) -> dict[str, Any]:
    fields = {
        "dataset_id": dataset_id,
        "parser_backend": "auto",
        "chunk_strategy": "langchain_recursive",
        "governance_enabled": "true",
        "chunk_vector_enabled": "true",
        "bm25_index_enabled": "true",
        "kg_enabled": "false",
        "event_vector_enabled": "false",
        "entity_vector_enabled": "false",
    }
    resp = api.multipart(
        "POST",
        "/api/v1/documents/upload",
        fields=fields,
        file_path=file_path,
    )
    record_step(steps, f"upload:{label}", resp)
    ensure_success(f"upload:{label}", resp)
    document_id = _response_id(resp, "id", "document_id")
    if not document_id:
        raise RuntimeError(f"upload:{label} missing document id")

    detail = wait_for_document_completed(
        api,
        steps=steps,
        filename=label,
        document_id=document_id,
        poll_timeout=poll_timeout,
    )
    chunks_resp = api.json("GET", f"/api/v1/documents/{document_id}/chunks?limit=200")
    record_step(steps, f"chunks:{label}", chunks_resp)
    ensure_success(f"chunks:{label}", chunks_resp)
    parsed_resp = api.json(
        "GET",
        f"/api/v1/documents/{document_id}/parsed-content?max_chars=8000",
    )
    parsed_chars = len(parsed_text_from_response(parsed_resp.body))
    record_step(steps, f"parsed:{label}", parsed_resp, parsed_chars=parsed_chars)
    ensure_success(f"parsed:{label}", parsed_resp)
    return {
        "document_id": document_id,
        "status": str(detail.get("status") or "").lower(),
        "chunk_count": _chunk_count_from_body(chunks_resp.body),
        "parsed_chars": parsed_chars,
    }


def cleanup_dataset(
    api: Any,
    *,
    steps: list[dict[str, Any]],
    dataset_id: str,
) -> dict[str, Any]:
    summary: dict[str, Any] = {"dataset_id": dataset_id}
    resp = api.json(
        "POST",
        f"/api/v1/datasets/{dataset_id}/purge?dry_run=false&max_delete=1000",
        payload={},
    )
    record_step(steps, f"cleanup:purge:{dataset_id}", resp)
    if 200 <= resp.status < 300:
        deleted = 0
        if isinstance(resp.body, dict):
            deleted = int((resp.body or {}).get("deleted") or 0)
        summary["purge_deleted"] = deleted
    resp = api.json("DELETE", f"/api/v1/datasets/{dataset_id}")
    record_step(steps, f"cleanup:delete_dataset:{dataset_id}", resp)
    summary["delete_dataset_status"] = int(resp.status)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run permission-sensitive KB boundary verification against a live API."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--admin-account-id", default="demo")
    parser.add_argument("--admin-user-id", default="demo")
    parser.add_argument("--outsider-account-id", default="outsider")
    parser.add_argument("--outsider-user-id", default="outsider")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--poll-timeout", type=int, default=300)
    parser.add_argument("--postgres-container", default="docker-mimirq-postgres-1")
    return parser


def build_artifact_dir(args: argparse.Namespace, run_id: str) -> Path:
    if args.artifact_dir:
        artifact_dir = Path(args.artifact_dir)
    else:
        artifact_dir = Path(f"artifacts/kb-permission-boundary/{run_id}")
    return artifact_dir.resolve()


def build_summary(args: argparse.Namespace, artifact_dir: Path) -> dict[str, Any]:
    return {
        "ok": False,
        "artifact_dir": str(artifact_dir),
        "base_url": args.base_url,
        "normalization": {},
        "group": {},
        "datasets": {},
        "http_checks": [],
        "retrieve_checks": [],
        "chat_checks": [],
    }


def build_rag_config() -> dict[str, Any]:
    return {
        "top_k": 4,
        "score_threshold": 0.0,
        "retrieval_mode": "keyword",
        "enable_reranker": False,
        "enable_multi_query": False,
        "enable_hyde": False,
        "enable_query_decomposition": False,
    }


def build_retrieve_payload(
    query: str,
    *,
    rag_config: dict[str, Any],
    dataset_id: str | None = None,
    document_ids: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"query": query, "rag_config": rag_config}
    if dataset_id is not None:
        payload["dataset_id"] = dataset_id
    if document_ids is not None:
        payload["document_ids"] = document_ids
    return payload


def build_chat_payload(
    message: str,
    *,
    rag_config: dict[str, Any],
    dataset_id: str | None = None,
    document_ids: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "message": message,
        "stream": False,
        "rag_config": {**rag_config, "answer_mode": "extractive", "max_tokens": 300},
    }
    if dataset_id is not None:
        payload["dataset_id"] = dataset_id
    if document_ids is not None:
        payload["document_ids"] = document_ids
    return payload


def citation_count_from_body(body: Any) -> int:
    if not isinstance(body, dict):
        return 0
    return len((body or {}).get("citations") or [])


def append_check_result(
    checks: list[dict[str, Any]],
    *,
    name: str,
    resp: Any,
    failures: list[str],
) -> None:
    checks.append(
        {
            "name": name,
            "status_code": resp.status,
            "ok": not failures,
            "failures": failures,
        }
    )
    if failures:
        raise RuntimeError(f"{name} failed: {failures}")


def run_inventory_check(
    api: Any,
    *,
    steps: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    name: str,
    path: str,
    expected_statuses: list[int],
    expected_document_ids: list[str] | None = None,
    sort_document_ids: bool = False,
    include_expected_in_failure: bool = False,
) -> None:
    resp = api.json("GET", path)
    record_step(steps, name, resp)
    failures = evaluate_http_expectation(name, resp.status, expected_statuses)
    if expected_document_ids is not None:
        actual_ids = exported_document_ids(resp.body)
        wanted_ids = expected_document_ids
        if sort_document_ids:
            actual_ids = sorted(actual_ids)
            wanted_ids = sorted(wanted_ids)
        if actual_ids != wanted_ids:
            detail = f"{name}: actual_document_ids={actual_ids}"
            if include_expected_in_failure:
                detail += f" expected={wanted_ids}"
            failures.append(detail)
    append_check_result(checks, name=name, resp=resp, failures=failures)


def run_permission_check(
    api: Any,
    *,
    steps: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    name: str,
    endpoint: str,
    payload: dict[str, Any],
    expected_statuses: list[int],
    case: dict[str, Any] | None = None,
) -> None:
    resp = api.json("POST", endpoint, payload=payload)
    record_step(steps, name, resp)
    failures = evaluate_http_expectation(name, resp.status, expected_statuses)
    if case is not None:
        failures.extend(
            evaluate_permission_scope_case(
                case,
                citation_doc_ids=citation_document_ids(resp.body),
                citation_count=citation_count_from_body(resp.body),
                response_text=response_text_from_body(resp.body),
            )
        )
    append_check_result(checks, name=name, resp=resp, failures=failures)


def verify_health(admin_api: Any, *, steps: list[dict[str, Any]]) -> None:
    resp = admin_api.json("GET", "/api/v1/health")
    record_step(steps, "health", resp)
    ensure_success("health", resp)


def normalize_outsider_role(
    outsider_api: Any,
    *,
    args: argparse.Namespace,
    steps: list[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    resp = outsider_api.json("GET", "/api/v1/datasets/?limit=1")
    record_step(steps, "outsider_bootstrap", resp)
    forced_ok, forced_output = force_member_role_via_docker(
        tenant_id=str(args.tenant_id),
        account_id=str(args.outsider_account_id),
        role="viewer",
        postgres_container=str(args.postgres_container),
        timeout=min(int(args.timeout), 60),
    )
    summary["normalization"] = {
        "viewer_role_forced": bool(forced_ok),
        "detail": forced_output,
    }
    if not forced_ok:
        raise RuntimeError(f"failed to normalize outsider role: {forced_output}")


def create_group(
    admin_api: Any,
    *,
    args: argparse.Namespace,
    run_id: str,
    steps: list[dict[str, Any]],
    summary: dict[str, Any],
) -> str:
    resp = admin_api.json(
        "POST",
        "/api/v1/groups/",
        payload={"name": f"kb-boundary-viewers-{run_id}"},
    )
    record_step(steps, "create_group", resp)
    ensure_success("create_group", resp)
    group_id = group_id_from_body(resp.body)
    if not group_id:
        raise RuntimeError("create_group missing group id")

    resp = admin_api.json(
        "POST",
        f"/api/v1/groups/{group_id}/members",
        payload={"member_ids": [str(args.outsider_account_id)]},
    )
    record_step(steps, "add_group_member", resp)
    ensure_success("add_group_member", resp)

    resp = admin_api.json("GET", f"/api/v1/groups/{group_id}/members?limit=50")
    record_step(steps, "list_group_members", resp)
    ensure_success("list_group_members", resp)
    member_ids = group_member_ids_from_body(resp.body)
    if str(args.outsider_account_id) not in member_ids:
        raise RuntimeError(f"outsider missing from group membership: {member_ids}")
    summary["group"] = {"group_id": group_id, "member_ids": member_ids}
    return group_id


def create_datasets_for_run(
    admin_api: Any,
    *,
    args: argparse.Namespace,
    run_id: str,
    steps: list[dict[str, Any]],
) -> dict[str, str]:
    shared_members = [str(args.admin_account_id), str(args.outsider_account_id)]
    return {
        "shared": create_dataset(
            admin_api,
            steps=steps,
            name=f"KB Perm Shared {run_id}",
            permission="partial_members",
            partial_member_list=shared_members,
        ),
        "group_shared": create_dataset(
            admin_api,
            steps=steps,
            name=f"KB Perm Group {run_id}",
            permission="partial_members",
            partial_member_list=[str(args.admin_account_id)],
        ),
        "doc_acl": create_dataset(
            admin_api,
            steps=steps,
            name=f"KB Perm Doc ACL {run_id}",
            permission="partial_members",
            partial_member_list=shared_members,
        ),
        "private": create_dataset(
            admin_api,
            steps=steps,
            name=f"KB Perm Private {run_id}",
            permission="only_me",
        ),
    }


def update_group_dataset_acl(
    admin_api: Any,
    *,
    args: argparse.Namespace,
    group_id: str,
    group_dataset_id: str,
    steps: list[dict[str, Any]],
) -> None:
    resp = admin_api.json(
        "PATCH",
        f"/api/v1/datasets/{group_dataset_id}",
        payload={
            "permission": "partial_members",
            "partial_member_list": [str(args.admin_account_id)],
            "partial_group_list": [group_id],
        },
    )
    record_step(steps, "update_group_dataset_acl", resp)
    ensure_success("update_group_dataset_acl", resp)


def write_fixture(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def upload_documents(
    admin_api: Any,
    *,
    artifact_dir: Path,
    fixtures: dict[str, Path],
    datasets: dict[str, str],
    steps: list[dict[str, Any]],
    poll_timeout: int,
) -> dict[str, dict[str, Any]]:
    uploaded = {
        "shared": upload_fixture(
            admin_api,
            steps=steps,
            dataset_id=datasets["shared"],
            label="shared_alpha",
            file_path=fixtures["alpha-handbook.md"],
            poll_timeout=poll_timeout,
        ),
        "private": upload_fixture(
            admin_api,
            steps=steps,
            dataset_id=datasets["private"],
            label="private_beta",
            file_path=fixtures["beta-runbook.md"],
            poll_timeout=poll_timeout,
        ),
        "group": upload_fixture(
            admin_api,
            steps=steps,
            dataset_id=datasets["group_shared"],
            label="group_shared",
            file_path=write_fixture(
                artifact_dir / "fixtures" / "group-handbook.md",
                "# Group Shared Handbook\n\n"
                "Token GROUP-LANTERN belongs only to the group-shared dataset.\n\n"
                "Owner: Gina Harbor.\n",
            ),
            poll_timeout=poll_timeout,
        ),
        "doc_visible": upload_fixture(
            admin_api,
            steps=steps,
            dataset_id=datasets["doc_acl"],
            label="doc_acl_visible",
            file_path=write_fixture(
                artifact_dir / "fixtures" / "doc-visible.md",
                "# Visible Document\n\nToken DOC-VISIBLE-SPARROW belongs only to the visible document.\n",
            ),
            poll_timeout=poll_timeout,
        ),
        "doc_private": upload_fixture(
            admin_api,
            steps=steps,
            dataset_id=datasets["doc_acl"],
            label="doc_acl_private",
            file_path=write_fixture(
                artifact_dir / "fixtures" / "doc-private.md",
                "# Private Document\n\nToken DOC-SECRET-KOALA belongs only to the private document.\n",
            ),
            poll_timeout=poll_timeout,
        ),
        "doc_group": upload_fixture(
            admin_api,
            steps=steps,
            dataset_id=datasets["doc_acl"],
            label="doc_acl_group",
            file_path=write_fixture(
                artifact_dir / "fixtures" / "doc-group.md",
                "# Group Document\n\nToken DOC-GROUP-LANTERN belongs only to the group-guarded document.\n",
            ),
            poll_timeout=poll_timeout,
        ),
    }
    return uploaded


def configure_document_access(
    admin_api: Any,
    *,
    args: argparse.Namespace,
    group_id: str,
    documents: dict[str, dict[str, Any]],
    steps: list[dict[str, Any]],
) -> None:
    resp = admin_api.json(
        "PUT",
        f"/api/v1/documents/{documents['doc_private']['document_id']}/access",
        payload={
            "mode": "partial_members",
            "partial_member_list": [str(args.admin_account_id)],
        },
    )
    record_step(steps, "doc_acl_private_set_access", resp)
    ensure_success("doc_acl_private_set_access", resp)
    private_access = document_access_summary(resp.body)
    expected_members = [str(args.admin_account_id)]
    if private_access["mode"] != "partial_members" or private_access["partial_member_list"] != expected_members:
        raise RuntimeError(f"doc private access mismatch: {private_access}")

    resp = admin_api.json(
        "PUT",
        f"/api/v1/documents/{documents['doc_group']['document_id']}/access",
        payload={"mode": "partial_members", "partial_group_list": [group_id]},
    )
    record_step(steps, "doc_acl_group_set_access", resp)
    ensure_success("doc_acl_group_set_access", resp)
    group_access = document_access_summary(resp.body)
    if group_access["mode"] != "partial_members" or group_access["partial_group_list"] != [group_id]:
        raise RuntimeError(f"doc group access mismatch: {group_access}")


def update_dataset_summary(
    summary: dict[str, Any],
    *,
    datasets: dict[str, str],
    documents: dict[str, dict[str, Any]],
) -> None:
    summary["datasets"] = {
        "shared": {"dataset_id": datasets["shared"], **documents["shared"]},
        "group_shared": {"dataset_id": datasets["group_shared"], **documents["group"]},
        "doc_acl": {
            "dataset_id": datasets["doc_acl"],
            "visible_document_id": documents["doc_visible"]["document_id"],
            "private_document_id": documents["doc_private"]["document_id"],
            "group_document_id": documents["doc_group"]["document_id"],
        },
        "private": {"dataset_id": datasets["private"], **documents["private"]},
    }


def run_inventory_checks(
    outsider_api: Any,
    *,
    datasets: dict[str, str],
    documents: dict[str, dict[str, Any]],
    steps: list[dict[str, Any]],
    http_checks: list[dict[str, Any]],
) -> None:
    scenarios = [
        {
            "name": "outsider_shared_inventory",
            "path": f"/api/v1/documents/?dataset_id={datasets['shared']}&limit=20",
            "expected_statuses": [200],
            "expected_document_ids": [documents["shared"]["document_id"]],
            "sort_document_ids": False,
            "include_expected_in_failure": False,
        },
        {
            "name": "outsider_private_inventory",
            "path": f"/api/v1/documents/?dataset_id={datasets['private']}&limit=20",
            "expected_statuses": [403],
            "expected_document_ids": None,
            "sort_document_ids": False,
            "include_expected_in_failure": False,
        },
        {
            "name": "outsider_group_inventory",
            "path": f"/api/v1/documents/?dataset_id={datasets['group_shared']}&limit=20",
            "expected_statuses": [200],
            "expected_document_ids": [documents["group"]["document_id"]],
            "sort_document_ids": False,
            "include_expected_in_failure": False,
        },
        {
            "name": "outsider_doc_acl_inventory",
            "path": f"/api/v1/documents/?dataset_id={datasets['doc_acl']}&limit=20",
            "expected_statuses": [200],
            "expected_document_ids": [
                documents["doc_visible"]["document_id"],
                documents["doc_group"]["document_id"],
            ],
            "sort_document_ids": True,
            "include_expected_in_failure": True,
        },
    ]
    for scenario in scenarios:
        run_inventory_check(
            outsider_api,
            steps=steps,
            checks=http_checks,
            name=scenario["name"],
            path=scenario["path"],
            expected_statuses=scenario["expected_statuses"],
            expected_document_ids=scenario["expected_document_ids"],
            sort_document_ids=scenario["sort_document_ids"],
            include_expected_in_failure=scenario["include_expected_in_failure"],
        )


def run_retrieve_checks(
    admin_api: Any,
    outsider_api: Any,
    *,
    datasets: dict[str, str],
    documents: dict[str, dict[str, Any]],
    rag_config: dict[str, Any],
    steps: list[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    endpoint = "/api/v1/rag/retrieve-preview"
    scenarios = [
        {
            "api": admin_api,
            "checks": summary["http_checks"],
            "name": "admin_private_retrieve",
            "payload": build_retrieve_payload(
                "Who owns token BETA-QUARTZ?",
                dataset_id=datasets["private"],
                rag_config=rag_config,
            ),
            "expected_statuses": [200],
            "case": {
                "name": "admin_private_retrieve",
                "allowed_document_ids": [documents["private"]["document_id"]],
                "expected_document_ids": [documents["private"]["document_id"]],
                "expected_terms": ["BETA-QUARTZ"],
                "min_citations": 1,
            },
        },
        {
            "api": outsider_api,
            "checks": summary["retrieve_checks"],
            "name": "outsider_shared_retrieve",
            "payload": build_retrieve_payload(
                "Who owns token ALOE-COMET?",
                dataset_id=datasets["shared"],
                rag_config=rag_config,
            ),
            "expected_statuses": [200],
            "case": {
                "name": "outsider_shared_retrieve",
                "allowed_document_ids": [documents["shared"]["document_id"]],
                "expected_document_ids": [documents["shared"]["document_id"]],
                "expected_terms": ["ALOE-COMET"],
                "forbidden_terms": ["BETA-QUARTZ", "Bob Quartz"],
                "min_citations": 1,
            },
        },
        {
            "api": outsider_api,
            "checks": summary["retrieve_checks"],
            "name": "outsider_group_retrieve",
            "payload": build_retrieve_payload(
                "Who owns token GROUP-LANTERN?",
                dataset_id=datasets["group_shared"],
                rag_config=rag_config,
            ),
            "expected_statuses": [200],
            "case": {
                "name": "outsider_group_retrieve",
                "allowed_document_ids": [documents["group"]["document_id"]],
                "expected_document_ids": [documents["group"]["document_id"]],
                "expected_terms": ["GROUP-LANTERN"],
                "forbidden_terms": ["BETA-QUARTZ", "ALOE-COMET"],
                "min_citations": 1,
            },
        },
        {
            "api": outsider_api,
            "checks": summary["retrieve_checks"],
            "name": "outsider_private_retrieve",
            "payload": build_retrieve_payload(
                "Who owns token BETA-QUARTZ?",
                dataset_id=datasets["private"],
                rag_config=rag_config,
            ),
            "expected_statuses": [403],
            "case": None,
        },
        {
            "api": outsider_api,
            "checks": summary["retrieve_checks"],
            "name": "outsider_mixed_scope_retrieve",
            "payload": build_retrieve_payload(
                "Who owns token ALOE-COMET?",
                document_ids=[
                    documents["shared"]["document_id"],
                    documents["private"]["document_id"],
                ],
                rag_config=rag_config,
            ),
            "expected_statuses": [200],
            "case": {
                "name": "outsider_mixed_scope_shared_query",
                "allowed_document_ids": [documents["shared"]["document_id"]],
                "expected_document_ids": [documents["shared"]["document_id"]],
                "expected_terms": ["ALOE-COMET"],
                "forbidden_terms": ["BETA-QUARTZ", "Bob Quartz"],
                "min_citations": 1,
            },
        },
        {
            "api": outsider_api,
            "checks": summary["retrieve_checks"],
            "name": "outsider_group_mixed_scope_retrieve",
            "payload": build_retrieve_payload(
                "Who owns token GROUP-LANTERN?",
                document_ids=[
                    documents["group"]["document_id"],
                    documents["private"]["document_id"],
                ],
                rag_config=rag_config,
            ),
            "expected_statuses": [200],
            "case": {
                "name": "outsider_group_mixed_scope_retrieve",
                "allowed_document_ids": [documents["group"]["document_id"]],
                "expected_document_ids": [documents["group"]["document_id"]],
                "expected_terms": ["GROUP-LANTERN"],
                "forbidden_terms": ["BETA-QUARTZ", "ALOE-COMET"],
                "min_citations": 1,
            },
        },
        {
            "api": outsider_api,
            "checks": summary["retrieve_checks"],
            "name": "outsider_doc_acl_visible_retrieve",
            "payload": build_retrieve_payload(
                "Who owns token DOC-VISIBLE-SPARROW?",
                dataset_id=datasets["doc_acl"],
                rag_config=rag_config,
            ),
            "expected_statuses": [200],
            "case": {
                "name": "outsider_doc_acl_visible_retrieve",
                "allowed_document_ids": [
                    documents["doc_visible"]["document_id"],
                    documents["doc_group"]["document_id"],
                ],
                "required_document_ids": [documents["doc_visible"]["document_id"]],
                "expected_terms": ["DOC-VISIBLE-SPARROW"],
                "forbidden_terms": ["DOC-SECRET-KOALA"],
                "min_citations": 1,
            },
        },
        {
            "api": outsider_api,
            "checks": summary["retrieve_checks"],
            "name": "outsider_doc_acl_group_retrieve",
            "payload": build_retrieve_payload(
                "Who owns token DOC-GROUP-LANTERN?",
                dataset_id=datasets["doc_acl"],
                rag_config=rag_config,
            ),
            "expected_statuses": [200],
            "case": {
                "name": "outsider_doc_acl_group_retrieve",
                "allowed_document_ids": [
                    documents["doc_visible"]["document_id"],
                    documents["doc_group"]["document_id"],
                ],
                "required_document_ids": [documents["doc_group"]["document_id"]],
                "expected_terms": ["DOC-GROUP-LANTERN"],
                "forbidden_terms": ["DOC-SECRET-KOALA"],
                "min_citations": 1,
            },
        },
        {
            "api": outsider_api,
            "checks": summary["retrieve_checks"],
            "name": "outsider_doc_acl_private_retrieve",
            "payload": build_retrieve_payload(
                "Who owns token DOC-SECRET-KOALA?",
                dataset_id=datasets["doc_acl"],
                rag_config=rag_config,
            ),
            "expected_statuses": [200],
            "case": {
                "name": "outsider_doc_acl_private_retrieve",
                "allowed_document_ids": [
                    documents["doc_visible"]["document_id"],
                    documents["doc_group"]["document_id"],
                ],
                "forbidden_terms": ["DOC-SECRET-KOALA"],
            },
        },
        {
            "api": outsider_api,
            "checks": summary["retrieve_checks"],
            "name": "outsider_doc_acl_visible_mixed_scope_retrieve",
            "payload": build_retrieve_payload(
                "Who owns token DOC-VISIBLE-SPARROW?",
                document_ids=[
                    documents["doc_visible"]["document_id"],
                    documents["doc_private"]["document_id"],
                ],
                rag_config=rag_config,
            ),
            "expected_statuses": [200],
            "case": {
                "name": "outsider_doc_acl_visible_mixed_scope_retrieve",
                "allowed_document_ids": [documents["doc_visible"]["document_id"]],
                "expected_document_ids": [documents["doc_visible"]["document_id"]],
                "expected_terms": ["DOC-VISIBLE-SPARROW"],
                "forbidden_terms": ["DOC-SECRET-KOALA"],
                "min_citations": 1,
            },
        },
        {
            "api": outsider_api,
            "checks": summary["retrieve_checks"],
            "name": "outsider_doc_acl_group_mixed_scope_retrieve",
            "payload": build_retrieve_payload(
                "Who owns token DOC-GROUP-LANTERN?",
                document_ids=[
                    documents["doc_group"]["document_id"],
                    documents["doc_private"]["document_id"],
                ],
                rag_config=rag_config,
            ),
            "expected_statuses": [200],
            "case": {
                "name": "outsider_doc_acl_group_mixed_scope_retrieve",
                "allowed_document_ids": [documents["doc_group"]["document_id"]],
                "expected_document_ids": [documents["doc_group"]["document_id"]],
                "expected_terms": ["DOC-GROUP-LANTERN"],
                "forbidden_terms": ["DOC-SECRET-KOALA"],
                "min_citations": 1,
            },
        },
        {
            "api": outsider_api,
            "checks": summary["retrieve_checks"],
            "name": "outsider_doc_acl_private_direct_retrieve",
            "payload": build_retrieve_payload(
                "Who owns token DOC-SECRET-KOALA?",
                document_ids=[documents["doc_private"]["document_id"]],
                rag_config=rag_config,
            ),
            "expected_statuses": [403],
            "case": None,
        },
    ]
    for scenario in scenarios:
        run_permission_check(
            scenario["api"],
            steps=steps,
            checks=scenario["checks"],
            name=scenario["name"],
            endpoint=endpoint,
            payload=scenario["payload"],
            expected_statuses=scenario["expected_statuses"],
            case=scenario["case"],
        )


def run_chat_checks(
    outsider_api: Any,
    *,
    datasets: dict[str, str],
    documents: dict[str, dict[str, Any]],
    rag_config: dict[str, Any],
    steps: list[dict[str, Any]],
    chat_checks: list[dict[str, Any]],
) -> None:
    endpoint = "/api/v1/chat"
    scenarios = [
        {
            "name": "outsider_shared_chat",
            "payload": build_chat_payload(
                "Who owns token ALOE-COMET?",
                dataset_id=datasets["shared"],
                rag_config=rag_config,
            ),
            "expected_statuses": [200],
            "case": {
                "name": "outsider_shared_chat",
                "allowed_document_ids": [documents["shared"]["document_id"]],
                "expected_document_ids": [documents["shared"]["document_id"]],
                "expected_terms": ["ALOE-COMET"],
                "forbidden_terms": ["BETA-QUARTZ", "Bob Quartz"],
                "min_citations": 1,
            },
        },
        {
            "name": "outsider_group_chat",
            "payload": build_chat_payload(
                "Who owns token GROUP-LANTERN?",
                dataset_id=datasets["group_shared"],
                rag_config=rag_config,
            ),
            "expected_statuses": [200],
            "case": {
                "name": "outsider_group_chat",
                "allowed_document_ids": [documents["group"]["document_id"]],
                "expected_document_ids": [documents["group"]["document_id"]],
                "expected_terms": ["GROUP-LANTERN"],
                "forbidden_terms": ["BETA-QUARTZ", "ALOE-COMET"],
                "min_citations": 1,
            },
        },
        {
            "name": "outsider_private_chat",
            "payload": build_chat_payload(
                "Who owns token BETA-QUARTZ?",
                dataset_id=datasets["private"],
                rag_config=rag_config,
            ),
            "expected_statuses": [403],
            "case": None,
        },
        {
            "name": "outsider_mixed_scope_chat",
            "payload": build_chat_payload(
                "Who owns token ALOE-COMET?",
                document_ids=[
                    documents["shared"]["document_id"],
                    documents["private"]["document_id"],
                ],
                rag_config=rag_config,
            ),
            "expected_statuses": [200],
            "case": {
                "name": "outsider_mixed_scope_chat",
                "allowed_document_ids": [documents["shared"]["document_id"]],
                "expected_document_ids": [documents["shared"]["document_id"]],
                "expected_terms": ["ALOE-COMET"],
                "forbidden_terms": ["BETA-QUARTZ", "Bob Quartz"],
                "min_citations": 1,
            },
        },
        {
            "name": "outsider_group_mixed_scope_chat",
            "payload": build_chat_payload(
                "Who owns token GROUP-LANTERN?",
                document_ids=[
                    documents["group"]["document_id"],
                    documents["private"]["document_id"],
                ],
                rag_config=rag_config,
            ),
            "expected_statuses": [200],
            "case": {
                "name": "outsider_group_mixed_scope_chat",
                "allowed_document_ids": [documents["group"]["document_id"]],
                "expected_document_ids": [documents["group"]["document_id"]],
                "expected_terms": ["GROUP-LANTERN"],
                "forbidden_terms": ["BETA-QUARTZ", "ALOE-COMET"],
                "min_citations": 1,
            },
        },
        {
            "name": "outsider_doc_acl_visible_chat",
            "payload": build_chat_payload(
                "Who owns token DOC-VISIBLE-SPARROW?",
                dataset_id=datasets["doc_acl"],
                rag_config=rag_config,
            ),
            "expected_statuses": [200],
            "case": {
                "name": "outsider_doc_acl_visible_chat",
                "allowed_document_ids": [
                    documents["doc_visible"]["document_id"],
                    documents["doc_group"]["document_id"],
                ],
                "required_document_ids": [documents["doc_visible"]["document_id"]],
                "expected_terms": ["DOC-VISIBLE-SPARROW"],
                "forbidden_terms": ["DOC-SECRET-KOALA"],
                "min_citations": 1,
            },
        },
        {
            "name": "outsider_doc_acl_group_chat",
            "payload": build_chat_payload(
                "Who owns token DOC-GROUP-LANTERN?",
                dataset_id=datasets["doc_acl"],
                rag_config=rag_config,
            ),
            "expected_statuses": [200],
            "case": {
                "name": "outsider_doc_acl_group_chat",
                "allowed_document_ids": [
                    documents["doc_visible"]["document_id"],
                    documents["doc_group"]["document_id"],
                ],
                "required_document_ids": [documents["doc_group"]["document_id"]],
                "expected_terms": ["DOC-GROUP-LANTERN"],
                "forbidden_terms": ["DOC-SECRET-KOALA"],
                "min_citations": 1,
            },
        },
        {
            "name": "outsider_doc_acl_private_chat",
            "payload": build_chat_payload(
                "Who owns token DOC-SECRET-KOALA?",
                dataset_id=datasets["doc_acl"],
                rag_config=rag_config,
            ),
            "expected_statuses": [200],
            "case": {
                "name": "outsider_doc_acl_private_chat",
                "allowed_document_ids": [
                    documents["doc_visible"]["document_id"],
                    documents["doc_group"]["document_id"],
                ],
                "forbidden_terms": ["DOC-SECRET-KOALA"],
            },
        },
        {
            "name": "outsider_doc_acl_visible_mixed_scope_chat",
            "payload": build_chat_payload(
                "Who owns token DOC-VISIBLE-SPARROW?",
                document_ids=[
                    documents["doc_visible"]["document_id"],
                    documents["doc_private"]["document_id"],
                ],
                rag_config=rag_config,
            ),
            "expected_statuses": [200],
            "case": {
                "name": "outsider_doc_acl_visible_mixed_scope_chat",
                "allowed_document_ids": [documents["doc_visible"]["document_id"]],
                "expected_document_ids": [documents["doc_visible"]["document_id"]],
                "expected_terms": ["DOC-VISIBLE-SPARROW"],
                "forbidden_terms": ["DOC-SECRET-KOALA"],
                "min_citations": 1,
            },
        },
        {
            "name": "outsider_doc_acl_group_mixed_scope_chat",
            "payload": build_chat_payload(
                "Who owns token DOC-GROUP-LANTERN?",
                document_ids=[
                    documents["doc_group"]["document_id"],
                    documents["doc_private"]["document_id"],
                ],
                rag_config=rag_config,
            ),
            "expected_statuses": [200],
            "case": {
                "name": "outsider_doc_acl_group_mixed_scope_chat",
                "allowed_document_ids": [documents["doc_group"]["document_id"]],
                "expected_document_ids": [documents["doc_group"]["document_id"]],
                "expected_terms": ["DOC-GROUP-LANTERN"],
                "forbidden_terms": ["DOC-SECRET-KOALA"],
                "min_citations": 1,
            },
        },
        {
            "name": "outsider_doc_acl_private_direct_chat",
            "payload": build_chat_payload(
                "Who owns token DOC-SECRET-KOALA?",
                document_ids=[documents["doc_private"]["document_id"]],
                rag_config=rag_config,
            ),
            "expected_statuses": [403],
            "case": None,
        },
    ]
    for scenario in scenarios:
        run_permission_check(
            outsider_api,
            steps=steps,
            checks=chat_checks,
            name=scenario["name"],
            endpoint=endpoint,
            payload=scenario["payload"],
            expected_statuses=scenario["expected_statuses"],
            case=scenario["case"],
        )


def build_cleanup_summary(
    admin_api: Any,
    *,
    datasets: dict[str, str],
    group_id: str,
    steps: list[dict[str, Any]],
) -> dict[str, Any]:
    cleanup = {
        "shared": cleanup_dataset(admin_api, steps=steps, dataset_id=datasets["shared"]),
        "group_shared": cleanup_dataset(admin_api, steps=steps, dataset_id=datasets["group_shared"]),
        "doc_acl": cleanup_dataset(admin_api, steps=steps, dataset_id=datasets["doc_acl"]),
        "private": cleanup_dataset(admin_api, steps=steps, dataset_id=datasets["private"]),
    }
    if group_id:
        resp = admin_api.json("DELETE", f"/api/v1/groups/{group_id}")
        record_step(steps, "cleanup:delete_group", resp)
        cleanup["group"] = {"group_id": group_id, "delete_group_status": int(resp.status)}
    return cleanup


def write_report(artifact_dir: Path, *, summary: dict[str, Any], steps: list[dict[str, Any]]) -> None:
    report = {"summary": summary, "steps": steps}
    report_path = artifact_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def run_boundary_verification(
    args: argparse.Namespace,
    *,
    artifact_dir: Path,
    run_id: str,
    summary: dict[str, Any],
    steps: list[dict[str, Any]],
) -> int:
    fixtures = make_fixture_files(artifact_dir / "fixtures")
    admin_api = build_live_api(
        args.base_url,
        args.tenant_id,
        args.admin_account_id,
        args.admin_user_id,
        args.timeout,
    )
    outsider_api = build_live_api(
        args.base_url,
        args.tenant_id,
        args.outsider_account_id,
        args.outsider_user_id,
        args.timeout,
    )
    group_id = ""

    try:
        verify_health(admin_api, steps=steps)
        normalize_outsider_role(outsider_api, args=args, steps=steps, summary=summary)
        group_id = create_group(
            admin_api,
            args=args,
            run_id=run_id,
            steps=steps,
            summary=summary,
        )
        datasets = create_datasets_for_run(admin_api, args=args, run_id=run_id, steps=steps)
        update_group_dataset_acl(
            admin_api,
            args=args,
            group_id=group_id,
            group_dataset_id=datasets["group_shared"],
            steps=steps,
        )
        documents = upload_documents(
            admin_api,
            artifact_dir=artifact_dir,
            fixtures=fixtures,
            datasets=datasets,
            steps=steps,
            poll_timeout=args.poll_timeout,
        )
        configure_document_access(
            admin_api,
            args=args,
            group_id=group_id,
            documents=documents,
            steps=steps,
        )
        update_dataset_summary(summary, datasets=datasets, documents=documents)
        run_inventory_checks(
            outsider_api,
            datasets=datasets,
            documents=documents,
            steps=steps,
            http_checks=summary["http_checks"],
        )
        rag_config = build_rag_config()
        run_retrieve_checks(
            admin_api,
            outsider_api,
            datasets=datasets,
            documents=documents,
            rag_config=rag_config,
            steps=steps,
            summary=summary,
        )
        run_chat_checks(
            outsider_api,
            datasets=datasets,
            documents=documents,
            rag_config=rag_config,
            steps=steps,
            chat_checks=summary["chat_checks"],
        )
        summary["cleanup"] = build_cleanup_summary(
            admin_api,
            datasets=datasets,
            group_id=group_id,
            steps=steps,
        )
        summary["ok"] = True
        return 0
    except Exception as exc:
        summary["ok"] = False
        summary["error"] = str(exc)
        return 1
    finally:
        write_report(artifact_dir, summary=summary, steps=steps)


def main() -> int:
    args = build_parser().parse_args()
    run_id = time.strftime("%Y%m%d-%H%M%S")
    artifact_dir = build_artifact_dir(args, run_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    steps: list[dict[str, Any]] = []
    summary = build_summary(args, artifact_dir)
    return_code = run_boundary_verification(
        args,
        artifact_dir=artifact_dir,
        run_id=run_id,
        summary=summary,
        steps=steps,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
