#!/usr/bin/env python3
"""Probe the live KG quality report endpoint against a disposable dataset."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


def ensure_repo_root_on_sys_path(script_path: str | Path) -> str:
    import sys

    repo_root = str(Path(script_path).resolve().parents[1])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    return repo_root


try:
    from scripts.remote_kb_boundary_matrix import LiveApi, ensure_success, record_step, wait_for_document_completed
except ModuleNotFoundError:
    ensure_repo_root_on_sys_path(__file__)
    from scripts.remote_kb_boundary_matrix import LiveApi, ensure_success, record_step, wait_for_document_completed


DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"


def validate_quality_report(report: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    scope = report.get("scope") if isinstance(report.get("scope"), dict) else {}

    if int(summary.get("documents") or 0) < 1:
        failures.append(f"summary.documents expected>=1 actual={int(summary.get('documents') or 0)}")
    if int(summary.get("events") or 0) < 1:
        failures.append(f"summary.events expected>=1 actual={int(summary.get('events') or 0)}")
    if int(scope.get("documents_allowed") or 0) < 1:
        failures.append(
            f"scope.documents_allowed expected>=1 actual={int(scope.get('documents_allowed') or 0)}"
        )
    return failures


def write_report(report: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a live KG quality report probe.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default="demo")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--poll-timeout", type=int, default=300)
    args = parser.parse_args(argv)

    run_id = time.strftime("%Y%m%d-%H%M%S")
    artifact_dir = Path(args.artifact_dir or f"artifacts/kg-quality-report/{run_id}").resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    api = LiveApi(args.base_url, args.tenant_id, args.account_id, args.user_id, args.timeout)

    steps: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "ok": False,
        "artifact_dir": str(artifact_dir),
        "base_url": args.base_url,
        "dataset_id": "",
    }

    dataset_id = ""

    try:
        resp = api.json("GET", "/api/v1/health")
        record_step(steps, "health", resp)
        ensure_success("health", resp)

        resp = api.json(
            "POST",
            "/api/v1/datasets/",
            payload={
                "name": f"KG Quality Report {run_id}",
                "description": "Disposable dataset for KG quality report probing.",
                "permission": "all_team_members",
                "default_parser_backend": "auto",
                "default_chunk_strategy": "langchain_recursive",
                "pipeline": {
                    "governance_enabled": True,
                    "persist_parsed_content": True,
                    "persist_parsed_content_max_chars": 200000,
                    "chunk_size": 1000,
                    "chunk_overlap": 200,
                    "chunk_vector_enabled": True,
                    "bm25_index_enabled": True,
                    "kg_enabled": True,
                    "event_vector_enabled": False,
                    "entity_vector_enabled": False,
                },
            },
        )
        record_step(steps, "dataset:create", resp)
        ensure_success("dataset:create", resp)
        dataset_id = str((resp.body or {}).get("id") or "")
        summary["dataset_id"] = dataset_id

        markdown = (
            "# Atlas Acquisition\n\n"
            "Atlas Systems acquired Beacon Labs.\n"
            "Mira Chen led the integration workstream.\n\n"
            "The integration workstream was tracked as a named post-acquisition effort.\n"
        )
        sample_path = artifact_dir / f"kg-quality-{run_id}.md"
        sample_path.write_text(markdown, encoding="utf-8")
        resp = api.multipart(
            "POST",
            "/api/v1/documents/upload",
            fields={
                "dataset_id": dataset_id,
                "parser_backend": "basic",
                "chunk_strategy": "langchain_recursive",
            },
            file_path=sample_path,
        )
        record_step(steps, "document:upload", resp)
        ensure_success("document:upload", resp)
        document_id = str((resp.body or {}).get("id") or "")
        summary["document_id"] = document_id

        final_doc = wait_for_document_completed(
            api,
            steps=steps,
            filename=sample_path.name,
            document_id=document_id,
            poll_timeout=max(30, int(args.poll_timeout)),
        )
        summary["document_status"] = final_doc.get("status")
        summary["chunk_count"] = int(final_doc.get("chunk_count") or 0)

        resp = api.json(
            "POST",
            f"/api/v1/kg/documents/{document_id}/extract?replace_existing=true&extract_relations=false&extract_skills=false&extraction_backend=heuristic",
        )
        record_step(steps, "kg:extract", resp)
        ensure_success("kg:extract", resp)

        resp = api.json(
            "GET",
            f"/api/v1/evaluations/kg/quality/report?dataset_id={dataset_id}&document_limit=20",
        )
        record_step(steps, "kg:quality_report", resp)
        ensure_success("kg:quality_report", resp)
        report = resp.body if isinstance(resp.body, dict) else {}
        summary["report"] = report

        failures = validate_quality_report(report)
        summary["failures"] = failures
        summary["ok"] = not failures

        cleanup = cleanup_dataset(api, steps=steps, dataset_id=dataset_id)
        summary["cleanup"] = cleanup

        report_path = write_report(
            {
                "schema": "mimirq.kg_quality_report_probe.v1",
                **summary,
                "steps": steps,
            },
            artifact_dir,
        )
        print(report_path)
        return 0 if summary["ok"] else 1
    finally:
        if dataset_id and not summary.get("cleanup"):
            try:
                cleanup = cleanup_dataset(api, steps=steps, dataset_id=dataset_id)
                summary["cleanup"] = cleanup
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
