#!/usr/bin/env python3
"""Verify table-store dataset table endpoints against a live API."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


def ensure_repo_root_on_sys_path(script_path: str | Path) -> str:
    repo_root = str(Path(script_path).resolve().parents[1])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    return repo_root


try:
    from scripts.remote_kb_boundary_matrix import LiveApi, ensure_success, record_step, wait_for_document_completed
except ModuleNotFoundError:
    ensure_repo_root_on_sys_path(__file__)
    from scripts.remote_kb_boundary_matrix import (  # type: ignore[no-redef]
        LiveApi,
        ensure_success,
        record_step,
        wait_for_document_completed,
    )


DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"


def validate_table_store_probe(
    *,
    table_list_body: Any,
    table_detail_body: Any,
    table_preview_body: Any,
    table_query_body: Any,
) -> list[str]:
    failures: list[str] = []

    list_items = []
    if isinstance(table_list_body, dict) and isinstance(table_list_body.get("items"), list):
        list_items = [item for item in table_list_body["items"] if isinstance(item, dict)]
    if not list_items:
        failures.append("table_list expected non-empty items")
        return failures

    first = list_items[0]
    if int(first.get("row_count") or 0) < 1:
        failures.append(f"table_list.row_count expected>=1 actual={int(first.get('row_count') or 0)}")
    if int(first.get("col_count") or 0) < 1:
        failures.append(f"table_list.col_count expected>=1 actual={int(first.get('col_count') or 0)}")

    detail = table_detail_body if isinstance(table_detail_body, dict) else {}
    detail_columns = detail.get("columns")
    if not isinstance(detail_columns, list) or len(detail_columns) < 3:
        failures.append(f"table_detail.columns expected>=3 actual={detail_columns!r}")
    else:
        names = {str(item.get("name") or "") for item in detail_columns if isinstance(item, dict)}
        for required in ("region", "amount", "status"):
            if required not in names:
                failures.append(f"table_detail missing column={required} actual={sorted(names)!r}")

    sample_rows = detail.get("sample_rows")
    if not isinstance(sample_rows, list) or not sample_rows:
        failures.append(f"table_detail.sample_rows expected non-empty actual={sample_rows!r}")
    else:
        first_row = sample_rows[0] if isinstance(sample_rows[0], dict) else {}
        if str(first_row.get("region") or "") != "APAC":
            failures.append(f"table_detail.sample_rows[0].region expected=APAC actual={first_row.get('region')!r}")
        if str(first_row.get("status") or "") != "review":
            failures.append(f"table_detail.sample_rows[0].status expected=review actual={first_row.get('status')!r}")

    for name, body in (("preview", table_preview_body), ("query", table_query_body)):
        payload = body if isinstance(body, dict) else {}
        columns = payload.get("columns")
        rows = payload.get("rows")
        if not isinstance(columns, list) or columns[:3] != ["region", "amount", "status"]:
            failures.append(f"{name}.columns expected=['region','amount','status'] actual={columns!r}")
        if not isinstance(rows, list) or len(rows) < 2:
            failures.append(f"{name}.rows expected>=2 actual={rows!r}")
            continue
        first_row = rows[0] if isinstance(rows[0], list) else []
        if len(first_row) < 3:
            failures.append(f"{name}.rows[0] expected len>=3 actual={first_row!r}")
            continue
        if str(first_row[0]) != "APAC":
            failures.append(f"{name}.rows[0][0] expected=APAC actual={first_row[0]!r}")
        if str(first_row[2]) != "review":
            failures.append(f"{name}.rows[0][2] expected=review actual={first_row[2]!r}")

    return failures


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
    parser = argparse.ArgumentParser(description="Run a live table-store endpoint probe.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default="demo")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--poll-timeout", type=int, default=300)
    args = parser.parse_args(argv)

    run_id = time.strftime("%Y%m%d-%H%M%S")
    artifact_dir = Path(args.artifact_dir or f"artifacts/table-store-probe/{run_id}").resolve()
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
                "name": f"Table Store Probe {run_id}",
                "description": "Disposable dataset for table-store endpoint probing.",
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
                    "table_store_enabled": True,
                    "table_store_auto_route": False,
                },
            },
        )
        record_step(steps, "dataset:create", resp)
        ensure_success("dataset:create", resp)
        dataset_id = str((resp.body or {}).get("id") or (resp.body or {}).get("dataset_id") or "")
        summary["dataset_id"] = dataset_id

        with tempfile.TemporaryDirectory(prefix="table-store-probe-") as td:
            csv_path = Path(td) / "sample.csv"
            csv_path.write_text(
                "region,amount,status\n"
                "APAC,1200,review\n"
                "EMEA,800,done\n",
                encoding="utf-8",
            )

            resp = api.multipart(
                "POST",
                "/api/v1/documents/upload",
                fields={
                    "dataset_id": dataset_id,
                    "parser_backend": "basic",
                    "chunk_strategy": "langchain_recursive",
                },
                file_path=csv_path,
            )
            record_step(steps, "document:upload", resp)
            ensure_success("document:upload", resp)
            document_id = str((resp.body or {}).get("id") or (resp.body or {}).get("document_id") or "")
            summary["document_id"] = document_id

            final_doc = wait_for_document_completed(
                api,
                steps=steps,
                filename=csv_path.name,
                document_id=document_id,
                poll_timeout=max(30, int(args.poll_timeout)),
            )
            summary["document_status"] = final_doc.get("status")

            list_resp = api.json("GET", f"/api/v1/datasets/{dataset_id}/tables?skip=0&limit=200")
            record_step(steps, "tables:list", list_resp)
            ensure_success("tables:list", list_resp)
            list_body = list_resp.body if isinstance(list_resp.body, dict) else {}
            items = list_body.get("items") if isinstance(list_body.get("items"), list) else []
            table_id = str((items[0] or {}).get("table_id") or "")
            if not table_id:
                raise RuntimeError("tables:list missing table_id")
            summary["table_id"] = table_id

            detail_resp = api.json(
                "GET",
                f"/api/v1/datasets/{dataset_id}/tables/{table_id}?include_columns=true&include_sample_rows=true",
            )
            record_step(steps, "tables:detail", detail_resp)
            ensure_success("tables:detail", detail_resp)

            preview_resp = api.json(
                "GET",
                f"/api/v1/datasets/{dataset_id}/tables/{table_id}/preview?limit=20",
            )
            record_step(steps, "tables:preview", preview_resp)
            ensure_success("tables:preview", preview_resp)

            query_resp = api.json(
                "POST",
                f"/api/v1/datasets/{dataset_id}/tables/{table_id}/query",
                payload={"sql": 'SELECT * FROM "sheet_0" LIMIT 5'},
            )
            record_step(steps, "tables:query", query_resp)
            ensure_success("tables:query", query_resp)

            failures = validate_table_store_probe(
                table_list_body=list_body,
                table_detail_body=detail_resp.body,
                table_preview_body=preview_resp.body,
                table_query_body=query_resp.body,
            )
            summary["failures"] = failures
            summary["ok"] = not failures

        summary["cleanup"] = cleanup_dataset(api, steps=steps, dataset_id=dataset_id)
        return_code = 0 if summary["ok"] else 1
    except Exception as exc:  # noqa: BLE001
        summary["ok"] = False
        summary["error"] = str(exc)
        return_code = 1
    finally:
        if dataset_id and "cleanup" not in summary:
            try:
                summary["cleanup"] = cleanup_dataset(api, steps=steps, dataset_id=dataset_id)
            except Exception:
                pass
        report = {
            "schema": "mimirq.table_store_probe.v1",
            "summary": summary,
            "steps": steps,
        }
        (artifact_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
