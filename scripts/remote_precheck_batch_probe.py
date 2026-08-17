#!/usr/bin/env python3
# ruff: noqa: E402, I001
"""Verify upload-batch precheck flow against a live API."""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import requests


def ensure_repo_root_on_sys_path(script_path: str | Path) -> str:
    repo_root = str(Path(script_path).resolve().parents[1])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    return repo_root


ensure_repo_root_on_sys_path(__file__)

from scripts.remote_kb_boundary_matrix import LiveApi, ensure_success, record_step


DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"


def evaluate_precheck_summary(summary_body: Any, samples_body: Any) -> list[str]:
    failures: list[str] = []
    summary = summary_body if isinstance(summary_body, dict) else {}
    samples = samples_body if isinstance(samples_body, dict) else {}

    total_files = int(summary.get("total_files") or 0)
    if total_files < 1:
        failures.append(f"total_files expected>=1 actual={total_files}")

    by_file_type = summary.get("by_file_type")
    if not isinstance(by_file_type, dict) or int(by_file_type.get("md") or 0) < 1:
        failures.append(f"by_file_type.md expected>=1 actual={by_file_type!r}")

    findings = summary.get("findings")
    short_text_count = None
    if isinstance(findings, list):
        for item in findings:
            if isinstance(item, dict) and str(item.get("key") or "") == "short_text":
                short_text_count = int(item.get("count") or 0)
                break
    if short_text_count is None or short_text_count < 1:
        failures.append(f"short_text finding expected>=1 actual={short_text_count!r}")

    representative = samples.get("representative")
    if not isinstance(representative, list) or not representative:
        failures.append("representative sample expected non-empty")
    else:
        first = representative[0] if isinstance(representative[0], dict) else {}
        text_chars = int(first.get("text_characters") or 0)
        if text_chars < 1:
            failures.append(f"representative.text_characters expected>=1 actual={text_chars}")
        findings_list = first.get("findings")
        if not isinstance(findings_list, list) or "short_text" not in findings_list:
            failures.append(f"representative.findings expected short_text actual={findings_list!r}")

    return failures


def cleanup_dataset(api: LiveApi, *, steps: list[dict[str, Any]], dataset_id: str) -> dict[str, Any]:
    summary: dict[str, Any] = {"dataset_id": dataset_id}
    resp = api.json("DELETE", f"/api/v1/datasets/{dataset_id}")
    record_step(steps, f"cleanup:delete_dataset:{dataset_id}", resp)
    summary["delete_dataset_status"] = int(resp.status)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run batch precheck verification against a live API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default="demo")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    run_id = time.strftime("%Y%m%d-%H%M%S")
    artifact_dir = Path(args.artifact_dir or f"artifacts/precheck-batch/{run_id}").resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    api = LiveApi(args.base_url, args.tenant_id, args.account_id, args.user_id, args.timeout)

    steps: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "ok": False,
        "artifact_dir": str(artifact_dir),
        "base_url": args.base_url,
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
                "name": f"Precheck Batch Probe {run_id}",
                "description": "Disposable dataset for precheck batch probe.",
                "permission": "all_team_members",
                "default_parser_backend": "basic",
                "default_chunk_strategy": "langchain_recursive",
                "pipeline": {
                    "governance_enabled": True,
                    "persist_parsed_content": True,
                    "persist_parsed_content_max_chars": 200000,
                    "chunk_size": 1000,
                    "chunk_overlap": 200,
                    "chunk_vector_enabled": True,
                    "bm25_index_enabled": True,
                    "kg_enabled": False,
                    "event_vector_enabled": False,
                    "entity_vector_enabled": False,
                },
            },
        )
        record_step(steps, "create_dataset", resp)
        ensure_success("create_dataset", resp)
        dataset_id = str((resp.body or {}).get("id") or (resp.body or {}).get("dataset_id") or "")
        if not dataset_id:
            raise RuntimeError("create_dataset missing dataset id")
        summary["dataset_id"] = dataset_id

        with tempfile.TemporaryDirectory(prefix="precheck-batch-") as td:
            doc_path = Path(td) / "sample.md"
            doc_path.write_text(
                "# Precheck Batch\n\nToken PRECHECK-BATCH belongs only to this file.\n",
                encoding="utf-8",
            )

            with doc_path.open("rb") as fh:
                response = requests.post(
                    f"{args.base_url.rstrip('/')}/api/v1/documents/upload-batch",
                    headers={
                        "X-Tenant-ID": args.tenant_id,
                        "X-Account-ID": args.account_id,
                        "X-User-ID": args.user_id,
                    },
                    files=[("files", (doc_path.name, fh, "text/markdown"))],
                    data={
                        "dataset_id": dataset_id,
                        "parser_backend": "basic",
                        "chunk_strategy": "langchain_recursive",
                        "precheck_only": "true",
                    },
                    timeout=args.timeout,
                )

            upload_body: Any
            try:
                upload_body = response.json()
            except Exception:
                upload_body = response.text
            upload_resp = type(
                "UploadResp", (), {"status": int(response.status_code), "body": upload_body, "elapsed_sec": 0.0}
            )()
            record_step(steps, "upload_batch_precheck", upload_resp)  # type: ignore[arg-type]
            if not (200 <= response.status_code < 300):
                raise RuntimeError(f"upload_batch_precheck failed: {response.status_code}: {upload_body}")

            scan_run_id = str((upload_body or {}).get("precheck_scan_run_id") or "")
            if not scan_run_id:
                raise RuntimeError("upload_batch_precheck missing precheck_scan_run_id")
            summary["scan_run_id"] = scan_run_id

            latest_run_body: dict[str, Any] = {}
            for _ in range(40):
                run_resp = api.json("GET", f"/api/v1/datasets/{dataset_id}/precheck/scan-runs/{scan_run_id}")
                record_step(steps, "poll_scan_run", run_resp)
                ensure_success("poll_scan_run", run_resp)
                latest_run_body = dict(run_resp.body or {})
                status = str(latest_run_body.get("status") or "").lower()
                if status in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(5)

            final_status = str(latest_run_body.get("status") or "").lower()
            summary["scan_status"] = final_status
            if final_status != "completed":
                raise RuntimeError(f"scan run did not complete: {latest_run_body}")

            summary_resp = api.json("GET", f"/api/v1/datasets/{dataset_id}/precheck/scan-runs/{scan_run_id}/summary")
            samples_resp = api.json(
                "GET", f"/api/v1/datasets/{dataset_id}/precheck/scan-runs/{scan_run_id}/samples?size=20"
            )
            record_step(steps, "summary", summary_resp)
            record_step(steps, "samples", samples_resp)
            ensure_success("summary", summary_resp)
            ensure_success("samples", samples_resp)

            failures = evaluate_precheck_summary(summary_resp.body, samples_resp.body)
            summary["summary_ok"] = not failures
            summary["summary_failures"] = failures
            if failures:
                raise RuntimeError(f"precheck summary validation failed: {failures}")

        summary["cleanup"] = cleanup_dataset(api, steps=steps, dataset_id=dataset_id)
        summary["ok"] = True
        return_code = 0
    except Exception as exc:  # noqa: BLE001
        summary["ok"] = False
        summary["error"] = str(exc)
        return_code = 1
    finally:
        if dataset_id and "cleanup" not in summary:
            summary["cleanup"] = cleanup_dataset(api, steps=steps, dataset_id=dataset_id)
        report = {"summary": summary, "steps": steps}
        (artifact_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
