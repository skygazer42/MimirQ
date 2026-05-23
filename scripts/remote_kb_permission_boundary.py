#!/usr/bin/env python3
"""Verify permission-sensitive knowledge-base boundaries against a live API."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"


def ensure_repo_root_on_sys_path(script_path: str | Path) -> str:
    repo_root = str(Path(script_path).resolve().parents[1])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    return repo_root


try:
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
except ModuleNotFoundError:
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


def evaluate_http_expectation(name: str, status: int, expected_statuses: list[int]) -> list[str]:
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


def create_dataset(
    api: LiveApi,
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
    dataset_id = str((resp.body or {}).get("id") or (resp.body or {}).get("dataset_id") or "")
    if not dataset_id:
        raise RuntimeError(f"create_dataset:{name} missing dataset id")
    return dataset_id


def upload_fixture(
    api: LiveApi,
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
    resp = api.multipart("POST", "/api/v1/documents/upload", fields=fields, file_path=file_path)
    record_step(steps, f"upload:{label}", resp)
    ensure_success(f"upload:{label}", resp)
    document_id = str((resp.body or {}).get("id") or (resp.body or {}).get("document_id") or "")
    if not document_id:
        raise RuntimeError(f"upload:{label} missing document id")

    detail = wait_for_document_completed(api, steps=steps, filename=label, document_id=document_id, poll_timeout=poll_timeout)
    chunks_resp = api.json("GET", f"/api/v1/documents/{document_id}/chunks?limit=200")
    record_step(steps, f"chunks:{label}", chunks_resp)
    ensure_success(f"chunks:{label}", chunks_resp)
    parsed_resp = api.json("GET", f"/api/v1/documents/{document_id}/parsed-content?max_chars=8000")
    record_step(steps, f"parsed:{label}", parsed_resp, parsed_chars=len(parsed_text_from_response(parsed_resp.body)))
    ensure_success(f"parsed:{label}", parsed_resp)
    return {
        "document_id": document_id,
        "status": str(detail.get("status") or "").lower(),
        "chunk_count": len((chunks_resp.body or {}).get("items") or (chunks_resp.body or {}).get("chunks") or []) if isinstance(chunks_resp.body, dict) else 0,
        "parsed_chars": len(parsed_text_from_response(parsed_resp.body)),
    }


def cleanup_dataset(api: LiveApi, *, steps: list[dict[str, Any]], dataset_id: str) -> dict[str, Any]:
    summary: dict[str, Any] = {"dataset_id": dataset_id}
    resp = api.json("POST", f"/api/v1/datasets/{dataset_id}/purge?dry_run=false&max_delete=1000", payload={})
    record_step(steps, f"cleanup:purge:{dataset_id}", resp)
    if 200 <= resp.status < 300:
        summary["purge_deleted"] = int((resp.body or {}).get("deleted") or 0) if isinstance(resp.body, dict) else 0
    resp = api.json("DELETE", f"/api/v1/datasets/{dataset_id}")
    record_step(steps, f"cleanup:delete_dataset:{dataset_id}", resp)
    summary["delete_dataset_status"] = int(resp.status)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run permission-sensitive KB boundary verification against a live API.")
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
    args = parser.parse_args()

    run_id = time.strftime("%Y%m%d-%H%M%S")
    artifact_dir = Path(args.artifact_dir or f"artifacts/kb-permission-boundary/{run_id}").resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    fixtures = make_fixture_files(artifact_dir / "fixtures")

    admin_api = LiveApi(args.base_url, args.tenant_id, args.admin_account_id, args.admin_user_id, args.timeout)
    outsider_api = LiveApi(args.base_url, args.tenant_id, args.outsider_account_id, args.outsider_user_id, args.timeout)

    steps: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
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

    dataset_ids: list[str] = []
    group_id = ""

    try:
        resp = admin_api.json("GET", "/api/v1/health")
        record_step(steps, "health", resp)
        ensure_success("health", resp)

        # Trigger dev bootstrap for outsider, then pin it to viewer so later deny checks are meaningful.
        resp = outsider_api.json("GET", "/api/v1/datasets/?limit=1")
        record_step(steps, "outsider_bootstrap", resp)
        forced_ok, forced_output = force_member_role_via_docker(
            tenant_id=str(args.tenant_id),
            account_id=str(args.outsider_account_id),
            role="viewer",
            postgres_container=str(args.postgres_container),
            timeout=min(int(args.timeout), 60),
        )
        summary["normalization"] = {"viewer_role_forced": bool(forced_ok), "detail": forced_output}
        if not forced_ok:
            raise RuntimeError(f"failed to normalize outsider role: {forced_output}")

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
        group_member_ids = group_member_ids_from_body(resp.body)
        if str(args.outsider_account_id) not in group_member_ids:
            raise RuntimeError(f"outsider missing from group membership: {group_member_ids}")
        summary["group"] = {"group_id": group_id, "member_ids": group_member_ids}

        shared_dataset_id = create_dataset(
            admin_api,
            steps=steps,
            name=f"KB Perm Shared {run_id}",
            permission="partial_members",
            partial_member_list=[str(args.admin_account_id), str(args.outsider_account_id)],
        )
        group_dataset_id = create_dataset(
            admin_api,
            steps=steps,
            name=f"KB Perm Group {run_id}",
            permission="partial_members",
            partial_member_list=[str(args.admin_account_id)],
        )
        private_dataset_id = create_dataset(
            admin_api,
            steps=steps,
            name=f"KB Perm Private {run_id}",
            permission="only_me",
        )
        dataset_ids.extend([shared_dataset_id, group_dataset_id, private_dataset_id])

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

        shared_doc = upload_fixture(
            admin_api,
            steps=steps,
            dataset_id=shared_dataset_id,
            label="shared_alpha",
            file_path=fixtures["alpha-handbook.md"],
            poll_timeout=args.poll_timeout,
        )
        private_doc = upload_fixture(
            admin_api,
            steps=steps,
            dataset_id=private_dataset_id,
            label="private_beta",
            file_path=fixtures["beta-runbook.md"],
            poll_timeout=args.poll_timeout,
        )
        group_fixture = artifact_dir / "fixtures" / "group-handbook.md"
        group_fixture.write_text(
            "# Group Shared Handbook\n\n"
            "Token GROUP-LANTERN belongs only to the group-shared dataset.\n\n"
            "Owner: Gina Harbor.\n",
            encoding="utf-8",
        )
        group_doc = upload_fixture(
            admin_api,
            steps=steps,
            dataset_id=group_dataset_id,
            label="group_shared",
            file_path=group_fixture,
            poll_timeout=args.poll_timeout,
        )
        summary["datasets"] = {
            "shared": {"dataset_id": shared_dataset_id, **shared_doc},
            "group_shared": {"dataset_id": group_dataset_id, **group_doc},
            "private": {"dataset_id": private_dataset_id, **private_doc},
        }

        # Shared/private export.
        resp = outsider_api.json("GET", f"/api/v1/documents/?dataset_id={shared_dataset_id}&limit=20")
        record_step(steps, "outsider_shared_inventory", resp)
        failures = evaluate_http_expectation("outsider_shared_inventory", resp.status, [200])
        export_ids = exported_document_ids(resp.body)
        if export_ids != [shared_doc["document_id"]]:
            failures.append(f"outsider_shared_inventory: actual_document_ids={export_ids}")
        summary["http_checks"].append({"name": "outsider_shared_inventory", "status_code": resp.status, "ok": not failures, "failures": failures})
        if failures:
            raise RuntimeError(f"outsider_shared_inventory failed: {failures}")

        resp = outsider_api.json("GET", f"/api/v1/documents/?dataset_id={private_dataset_id}&limit=20")
        record_step(steps, "outsider_private_inventory", resp)
        failures = evaluate_http_expectation("outsider_private_inventory", resp.status, [403])
        summary["http_checks"].append({"name": "outsider_private_inventory", "status_code": resp.status, "ok": not failures, "failures": failures})
        if failures:
            raise RuntimeError(f"outsider_private_inventory failed: {failures}")

        resp = outsider_api.json("GET", f"/api/v1/documents/?dataset_id={group_dataset_id}&limit=20")
        record_step(steps, "outsider_group_inventory", resp)
        failures = evaluate_http_expectation("outsider_group_inventory", resp.status, [200])
        export_ids = exported_document_ids(resp.body)
        if export_ids != [group_doc["document_id"]]:
            failures.append(f"outsider_group_inventory: actual_document_ids={export_ids}")
        summary["http_checks"].append({"name": "outsider_group_inventory", "status_code": resp.status, "ok": not failures, "failures": failures})
        if failures:
            raise RuntimeError(f"outsider_group_inventory failed: {failures}")

        rag_config = {
            "top_k": 4,
            "score_threshold": 0.0,
            "retrieval_mode": "keyword",
            "enable_reranker": False,
            "enable_multi_query": False,
            "enable_hyde": False,
            "enable_query_decomposition": False,
        }

        admin_private_payload = {
            "query": "Who owns token BETA-QUARTZ?",
            "dataset_id": private_dataset_id,
            "rag_config": rag_config,
        }
        resp = admin_api.json("POST", "/api/v1/rag/retrieve-preview", payload=admin_private_payload)
        record_step(steps, "admin_private_retrieve", resp)
        failures = evaluate_http_expectation("admin_private_retrieve", resp.status, [200])
        failures.extend(
            evaluate_permission_scope_case(
                {
                    "name": "admin_private_retrieve",
                    "allowed_document_ids": [private_doc["document_id"]],
                    "expected_document_ids": [private_doc["document_id"]],
                    "expected_terms": ["BETA-QUARTZ"],
                    "min_citations": 1,
                },
                citation_doc_ids=citation_document_ids(resp.body),
                citation_count=len((resp.body or {}).get("citations") or []) if isinstance(resp.body, dict) else 0,
                response_text=response_text_from_body(resp.body),
            )
        )
        summary["http_checks"].append({"name": "admin_private_retrieve", "status_code": resp.status, "ok": not failures, "failures": failures})
        if failures:
            raise RuntimeError(f"admin_private_retrieve failed: {failures}")

        outsider_shared_payload = {
            "query": "Who owns token ALOE-COMET?",
            "dataset_id": shared_dataset_id,
            "rag_config": rag_config,
        }
        resp = outsider_api.json("POST", "/api/v1/rag/retrieve-preview", payload=outsider_shared_payload)
        record_step(steps, "outsider_shared_retrieve", resp)
        failures = evaluate_http_expectation("outsider_shared_retrieve", resp.status, [200])
        failures.extend(
            evaluate_permission_scope_case(
                {
                    "name": "outsider_shared_retrieve",
                    "allowed_document_ids": [shared_doc["document_id"]],
                    "expected_document_ids": [shared_doc["document_id"]],
                    "expected_terms": ["ALOE-COMET"],
                    "forbidden_terms": ["BETA-QUARTZ", "Bob Quartz"],
                    "min_citations": 1,
                },
                citation_doc_ids=citation_document_ids(resp.body),
                citation_count=len((resp.body or {}).get("citations") or []) if isinstance(resp.body, dict) else 0,
                response_text=response_text_from_body(resp.body),
            )
        )
        summary["retrieve_checks"].append({"name": "outsider_shared_retrieve", "status_code": resp.status, "ok": not failures, "failures": failures})
        if failures:
            raise RuntimeError(f"outsider_shared_retrieve failed: {failures}")

        resp = outsider_api.json(
            "POST",
            "/api/v1/rag/retrieve-preview",
            payload={"query": "Who owns token GROUP-LANTERN?", "dataset_id": group_dataset_id, "rag_config": rag_config},
        )
        record_step(steps, "outsider_group_retrieve", resp)
        failures = evaluate_http_expectation("outsider_group_retrieve", resp.status, [200])
        failures.extend(
            evaluate_permission_scope_case(
                {
                    "name": "outsider_group_retrieve",
                    "allowed_document_ids": [group_doc["document_id"]],
                    "expected_document_ids": [group_doc["document_id"]],
                    "expected_terms": ["GROUP-LANTERN"],
                    "forbidden_terms": ["BETA-QUARTZ", "ALOE-COMET"],
                    "min_citations": 1,
                },
                citation_doc_ids=citation_document_ids(resp.body),
                citation_count=len((resp.body or {}).get("citations") or []) if isinstance(resp.body, dict) else 0,
                response_text=response_text_from_body(resp.body),
            )
        )
        summary["retrieve_checks"].append({"name": "outsider_group_retrieve", "status_code": resp.status, "ok": not failures, "failures": failures})
        if failures:
            raise RuntimeError(f"outsider_group_retrieve failed: {failures}")

        resp = outsider_api.json(
            "POST",
            "/api/v1/rag/retrieve-preview",
            payload={"query": "Who owns token BETA-QUARTZ?", "dataset_id": private_dataset_id, "rag_config": rag_config},
        )
        record_step(steps, "outsider_private_retrieve", resp)
        failures = evaluate_http_expectation("outsider_private_retrieve", resp.status, [403])
        summary["retrieve_checks"].append({"name": "outsider_private_retrieve", "status_code": resp.status, "ok": not failures, "failures": failures})
        if failures:
            raise RuntimeError(f"outsider_private_retrieve failed: {failures}")

        mixed_payload = {
            "query": "Who owns token ALOE-COMET?",
            "document_ids": [shared_doc["document_id"], private_doc["document_id"]],
            "rag_config": rag_config,
        }
        resp = outsider_api.json("POST", "/api/v1/rag/retrieve-preview", payload=mixed_payload)
        record_step(steps, "outsider_mixed_scope_retrieve", resp)
        failures = evaluate_http_expectation("outsider_mixed_scope_retrieve", resp.status, [200])
        failures.extend(
            evaluate_permission_scope_case(
                {
                    "name": "outsider_mixed_scope_shared_query",
                    "allowed_document_ids": [shared_doc["document_id"]],
                    "expected_document_ids": [shared_doc["document_id"]],
                    "expected_terms": ["ALOE-COMET"],
                    "forbidden_terms": ["BETA-QUARTZ", "Bob Quartz"],
                    "min_citations": 1,
                },
                citation_doc_ids=citation_document_ids(resp.body),
                citation_count=len((resp.body or {}).get("citations") or []) if isinstance(resp.body, dict) else 0,
                response_text=response_text_from_body(resp.body),
            )
        )
        summary["retrieve_checks"].append({"name": "outsider_mixed_scope_retrieve", "status_code": resp.status, "ok": not failures, "failures": failures})
        if failures:
            raise RuntimeError(f"outsider_mixed_scope_retrieve failed: {failures}")

        resp = outsider_api.json(
            "POST",
            "/api/v1/rag/retrieve-preview",
            payload={
                "query": "Who owns token GROUP-LANTERN?",
                "document_ids": [group_doc["document_id"], private_doc["document_id"]],
                "rag_config": rag_config,
            },
        )
        record_step(steps, "outsider_group_mixed_scope_retrieve", resp)
        failures = evaluate_http_expectation("outsider_group_mixed_scope_retrieve", resp.status, [200])
        failures.extend(
            evaluate_permission_scope_case(
                {
                    "name": "outsider_group_mixed_scope_retrieve",
                    "allowed_document_ids": [group_doc["document_id"]],
                    "expected_document_ids": [group_doc["document_id"]],
                    "expected_terms": ["GROUP-LANTERN"],
                    "forbidden_terms": ["BETA-QUARTZ", "ALOE-COMET"],
                    "min_citations": 1,
                },
                citation_doc_ids=citation_document_ids(resp.body),
                citation_count=len((resp.body or {}).get("citations") or []) if isinstance(resp.body, dict) else 0,
                response_text=response_text_from_body(resp.body),
            )
        )
        summary["retrieve_checks"].append({"name": "outsider_group_mixed_scope_retrieve", "status_code": resp.status, "ok": not failures, "failures": failures})
        if failures:
            raise RuntimeError(f"outsider_group_mixed_scope_retrieve failed: {failures}")

        shared_chat_payload = {
            "message": "Who owns token ALOE-COMET?",
            "dataset_id": shared_dataset_id,
            "stream": False,
            "rag_config": {**rag_config, "answer_mode": "extractive", "max_tokens": 300},
        }
        resp = outsider_api.json("POST", "/api/v1/chat", payload=shared_chat_payload)
        record_step(steps, "outsider_shared_chat", resp)
        failures = evaluate_http_expectation("outsider_shared_chat", resp.status, [200])
        failures.extend(
            evaluate_permission_scope_case(
                {
                    "name": "outsider_shared_chat",
                    "allowed_document_ids": [shared_doc["document_id"]],
                    "expected_document_ids": [shared_doc["document_id"]],
                    "expected_terms": ["ALOE-COMET"],
                    "forbidden_terms": ["BETA-QUARTZ", "Bob Quartz"],
                    "min_citations": 1,
                },
                citation_doc_ids=citation_document_ids(resp.body),
                citation_count=len((resp.body or {}).get("citations") or []) if isinstance(resp.body, dict) else 0,
                response_text=response_text_from_body(resp.body),
            )
        )
        summary["chat_checks"].append({"name": "outsider_shared_chat", "status_code": resp.status, "ok": not failures, "failures": failures})
        if failures:
            raise RuntimeError(f"outsider_shared_chat failed: {failures}")

        resp = outsider_api.json(
            "POST",
            "/api/v1/chat",
            payload={
                "message": "Who owns token GROUP-LANTERN?",
                "dataset_id": group_dataset_id,
                "stream": False,
                "rag_config": {**rag_config, "answer_mode": "extractive", "max_tokens": 300},
            },
        )
        record_step(steps, "outsider_group_chat", resp)
        failures = evaluate_http_expectation("outsider_group_chat", resp.status, [200])
        failures.extend(
            evaluate_permission_scope_case(
                {
                    "name": "outsider_group_chat",
                    "allowed_document_ids": [group_doc["document_id"]],
                    "expected_document_ids": [group_doc["document_id"]],
                    "expected_terms": ["GROUP-LANTERN"],
                    "forbidden_terms": ["BETA-QUARTZ", "ALOE-COMET"],
                    "min_citations": 1,
                },
                citation_doc_ids=citation_document_ids(resp.body),
                citation_count=len((resp.body or {}).get("citations") or []) if isinstance(resp.body, dict) else 0,
                response_text=response_text_from_body(resp.body),
            )
        )
        summary["chat_checks"].append({"name": "outsider_group_chat", "status_code": resp.status, "ok": not failures, "failures": failures})
        if failures:
            raise RuntimeError(f"outsider_group_chat failed: {failures}")

        resp = outsider_api.json(
            "POST",
            "/api/v1/chat",
            payload={
                "message": "Who owns token BETA-QUARTZ?",
                "dataset_id": private_dataset_id,
                "stream": False,
                "rag_config": {**rag_config, "answer_mode": "extractive", "max_tokens": 300},
            },
        )
        record_step(steps, "outsider_private_chat", resp)
        failures = evaluate_http_expectation("outsider_private_chat", resp.status, [403])
        summary["chat_checks"].append({"name": "outsider_private_chat", "status_code": resp.status, "ok": not failures, "failures": failures})
        if failures:
            raise RuntimeError(f"outsider_private_chat failed: {failures}")

        resp = outsider_api.json(
            "POST",
            "/api/v1/chat",
            payload={
                "message": "Who owns token ALOE-COMET?",
                "document_ids": [shared_doc["document_id"], private_doc["document_id"]],
                "stream": False,
                "rag_config": {**rag_config, "answer_mode": "extractive", "max_tokens": 300},
            },
        )
        record_step(steps, "outsider_mixed_scope_chat", resp)
        failures = evaluate_http_expectation("outsider_mixed_scope_chat", resp.status, [200])
        failures.extend(
            evaluate_permission_scope_case(
                {
                    "name": "outsider_mixed_scope_chat",
                    "allowed_document_ids": [shared_doc["document_id"]],
                    "expected_document_ids": [shared_doc["document_id"]],
                    "expected_terms": ["ALOE-COMET"],
                    "forbidden_terms": ["BETA-QUARTZ", "Bob Quartz"],
                    "min_citations": 1,
                },
                citation_doc_ids=citation_document_ids(resp.body),
                citation_count=len((resp.body or {}).get("citations") or []) if isinstance(resp.body, dict) else 0,
                response_text=response_text_from_body(resp.body),
            )
        )
        summary["chat_checks"].append({"name": "outsider_mixed_scope_chat", "status_code": resp.status, "ok": not failures, "failures": failures})
        if failures:
            raise RuntimeError(f"outsider_mixed_scope_chat failed: {failures}")

        resp = outsider_api.json(
            "POST",
            "/api/v1/chat",
            payload={
                "message": "Who owns token GROUP-LANTERN?",
                "document_ids": [group_doc["document_id"], private_doc["document_id"]],
                "stream": False,
                "rag_config": {**rag_config, "answer_mode": "extractive", "max_tokens": 300},
            },
        )
        record_step(steps, "outsider_group_mixed_scope_chat", resp)
        failures = evaluate_http_expectation("outsider_group_mixed_scope_chat", resp.status, [200])
        failures.extend(
            evaluate_permission_scope_case(
                {
                    "name": "outsider_group_mixed_scope_chat",
                    "allowed_document_ids": [group_doc["document_id"]],
                    "expected_document_ids": [group_doc["document_id"]],
                    "expected_terms": ["GROUP-LANTERN"],
                    "forbidden_terms": ["BETA-QUARTZ", "ALOE-COMET"],
                    "min_citations": 1,
                },
                citation_doc_ids=citation_document_ids(resp.body),
                citation_count=len((resp.body or {}).get("citations") or []) if isinstance(resp.body, dict) else 0,
                response_text=response_text_from_body(resp.body),
            )
        )
        summary["chat_checks"].append({"name": "outsider_group_mixed_scope_chat", "status_code": resp.status, "ok": not failures, "failures": failures})
        if failures:
            raise RuntimeError(f"outsider_group_mixed_scope_chat failed: {failures}")

        cleanup = {
            "shared": cleanup_dataset(admin_api, steps=steps, dataset_id=shared_dataset_id),
            "group_shared": cleanup_dataset(admin_api, steps=steps, dataset_id=group_dataset_id),
            "private": cleanup_dataset(admin_api, steps=steps, dataset_id=private_dataset_id),
        }
        if group_id:
            resp = admin_api.json("DELETE", f"/api/v1/groups/{group_id}")
            record_step(steps, "cleanup:delete_group", resp)
            cleanup["group"] = {"group_id": group_id, "delete_group_status": int(resp.status)}
        summary["cleanup"] = cleanup
        summary["ok"] = True
        return_code = 0
    except Exception as exc:  # noqa: BLE001
        summary["ok"] = False
        summary["error"] = str(exc)
        return_code = 1
    finally:
        report = {"summary": summary, "steps": steps}
        (artifact_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
