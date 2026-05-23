#!/usr/bin/env python3
"""Audit dataset-scoped vs document-scoped KG graph responses on a live API."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def ensure_repo_root_on_sys_path(script_path: str | Path) -> str:
    repo_root = str(Path(script_path).resolve().parents[1])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    return repo_root


try:
    from scripts.remote_real_pdf_chain import (
        DEFAULT_TENANT_ID,
        LiveApi,
        ok_status,
        perform_cleanup,
        record_step,
        snippet,
    )
except ModuleNotFoundError:
    ensure_repo_root_on_sys_path(__file__)
    from scripts.remote_real_pdf_chain import (
        DEFAULT_TENANT_ID,
        LiveApi,
        ok_status,
        perform_cleanup,
        record_step,
        snippet,
    )


def build_repeated_query(key: str, values: list[str]) -> str:
    parts = [f"{key}={value}" for value in values if str(value or "").strip()]
    return "&".join(parts)


def summarize_graph_response(body: Any) -> dict[str, Any]:
    nodes = body.get("nodes") if isinstance(body, dict) else []
    links = body.get("links") if isinstance(body, dict) else []
    stats = body.get("stats") if isinstance(body, dict) else {}
    return {
        "node_count": len(nodes) if isinstance(nodes, list) else 0,
        "link_count": len(links) if isinstance(links, list) else 0,
        "stats": stats if isinstance(stats, dict) else {},
    }


def compare_scope_counts(
    *,
    dataset_stats: dict[str, Any],
    document_stats: dict[str, Any],
    dataset_graph: dict[str, Any],
    document_graph: dict[str, Any],
) -> dict[str, Any]:
    return {
        "dataset_stats": dataset_stats,
        "document_stats": document_stats,
        "dataset_graph": dataset_graph,
        "document_graph": document_graph,
        "stats_match": dataset_stats == document_stats,
        "graph_match": dataset_graph == document_graph,
    }


def _poll_document_until_completed(
    api: LiveApi,
    *,
    document_id: str,
    steps: list[dict[str, Any]],
    timeout: int,
) -> None:
    deadline = time.time() + int(timeout)
    while time.time() < deadline:
        status, body, elapsed = api.json("GET", f"/api/v1/documents/{document_id}", timeout=timeout)
        doc_status = str((body or {}).get("status") or "")
        record_step(steps, "poll_document", status, body, elapsed, document_id=document_id, doc_status=doc_status)
        if not ok_status(status):
            raise RuntimeError(f"document poll failed: {snippet(body)}")
        if doc_status.lower() == "completed":
            return
        if doc_status.lower() in {"failed", "quarantined", "cancelled"}:
            raise RuntimeError(f"document terminal status={doc_status}: {snippet(body)}")
        time.sleep(2)
    raise RuntimeError(f"document did not complete: {document_id}")


def _list_items(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        return []
    items = body.get("items")
    if isinstance(items, list):
        return [row for row in items if isinstance(row, dict)]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit dataset-scoped vs document-scoped KG graph responses.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default="demo")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--poll-timeout", type=int, default=180)
    parser.add_argument("--delete-dataset-after", action="store_true")
    args = parser.parse_args()

    run_id = time.strftime("%Y%m%d-%H%M%S")
    artifact_dir = Path(args.artifact_dir or f"artifacts/graph-scope-audit/{run_id}").resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    fixture_dir = artifact_dir / "fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)

    api = LiveApi(args.base_url, args.tenant_id, args.account_id, args.user_id, args.timeout)
    steps: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"ok": False, "artifact_dir": str(artifact_dir), "base_url": args.base_url}

    dataset_id = ""
    document_ids: list[str] = []
    try:
        status, body, elapsed = api.json(
            "POST",
            "/api/v1/datasets/",
            payload={
                "name": f"Graph Scope Audit {run_id}",
                "description": "Audit graph dataset scope against explicit document_ids",
                "default_parser_backend": "basic",
                "default_chunk_strategy": "langchain_recursive",
            },
            timeout=args.timeout,
        )
        record_step(steps, "create_dataset", status, body, elapsed)
        if not ok_status(status):
            raise RuntimeError(f"create_dataset failed: {snippet(body)}")
        dataset_id = str((body or {}).get("id") or (body or {}).get("dataset_id") or "")
        if not dataset_id:
            raise RuntimeError(f"create_dataset missing id: {snippet(body)}")
        summary["dataset_id"] = dataset_id

        fixtures = [
            {
                "filename": "atlas-acquisition.md",
                "content": "# Atlas Acquisition\n\nAtlas Systems acquired Beacon Labs. Mira Chen led the integration workstream.\n",
            },
            {
                "filename": "orion-migration.md",
                "content": "# Orion Migration\n\nMira Chen coordinated the Orion billing service migration with Beacon Labs engineers.\n",
            },
        ]
        for fixture in fixtures:
            file_path = fixture_dir / fixture["filename"]
            file_path.write_text(fixture["content"], encoding="utf-8")
            status, body, elapsed = api.multipart(
                "POST",
                "/api/v1/documents/upload",
                fields={
                    "dataset_id": dataset_id,
                    "parser_backend": "basic",
                    "chunk_strategy": "langchain_recursive",
                    "governance_enabled": "true",
                    "chunk_vector_enabled": "true",
                    "bm25_index_enabled": "true",
                    "kg_enabled": "false",
                    "event_vector_enabled": "false",
                    "entity_vector_enabled": "false",
                },
                file_path=file_path,
                timeout=args.timeout,
            )
            record_step(steps, "upload_document", status, body, elapsed, filename=fixture["filename"])
            if not ok_status(status):
                raise RuntimeError(f"upload_document failed: {fixture['filename']} {snippet(body)}")
            document_id = str((body or {}).get("id") or (body or {}).get("document_id") or "")
            if not document_id:
                raise RuntimeError(f"upload_document missing id: {snippet(body)}")
            document_ids.append(document_id)

        summary["document_ids"] = document_ids

        for document_id in document_ids:
            _poll_document_until_completed(api, document_id=document_id, steps=steps, timeout=args.poll_timeout)

        for document_id in document_ids:
            status, body, elapsed = api.json(
                "POST",
                (
                    f"/api/v1/kg/documents/{document_id}/extract"
                    "?replace_existing=true&extract_relations=false&extract_skills=false"
                    "&extraction_backend=heuristic"
                ),
                timeout=args.timeout,
            )
            record_step(steps, "extract_kg", status, body, elapsed, document_id=document_id)
            if not ok_status(status):
                raise RuntimeError(f"kg extract failed: {document_id} {snippet(body)}")

        document_ids_query = build_repeated_query("document_ids", document_ids)
        queries = {
            "dataset_stats": f"/api/v1/kg/stats?dataset_id={dataset_id}",
            "document_stats": f"/api/v1/kg/stats?{document_ids_query}",
            "dataset_graph": (
                f"/api/v1/kg/graph?dataset_id={dataset_id}"
                "&include_entity_links=true&min_shared_events=1&max_events=200&max_entities=400&max_links=2000"
            ),
            "document_graph": (
                f"/api/v1/kg/graph?{document_ids_query}"
                "&include_entity_links=true&min_shared_events=1&max_events=200&max_entities=400&max_links=2000"
            ),
            "unscoped_stats": "/api/v1/kg/stats",
            "list_documents": f"/api/v1/documents/?dataset_id={dataset_id}&limit=50",
        }

        results: dict[str, Any] = {}
        for name, path in queries.items():
            status, body, elapsed = api.json("GET", path, timeout=min(int(args.timeout), 300))
            record_step(steps, name, status, body, elapsed)
            if not ok_status(status):
                raise RuntimeError(f"{name} failed: {snippet(body)}")
            results[name] = body

        dataset_stats = results["dataset_stats"] if isinstance(results["dataset_stats"], dict) else {}
        document_stats = results["document_stats"] if isinstance(results["document_stats"], dict) else {}
        dataset_graph = summarize_graph_response(results["dataset_graph"])
        document_graph = summarize_graph_response(results["document_graph"])
        comparison = compare_scope_counts(
            dataset_stats=dataset_stats,
            document_stats=document_stats,
            dataset_graph=dataset_graph,
            document_graph=document_graph,
        )

        items = _list_items(results["list_documents"])
        summary.update(
            {
                "dataset_stats": dataset_stats,
                "document_stats": document_stats,
                "unscoped_stats": results["unscoped_stats"],
                "dataset_graph": dataset_graph,
                "document_graph": document_graph,
                "comparison": comparison,
                "list_documents_count": len(items),
                "list_document_ids": [
                    str((row or {}).get("id") or (row or {}).get("document_id") or "") for row in items
                ],
            }
        )
        if not comparison["stats_match"] or not comparison["graph_match"]:
            raise RuntimeError(f"graph scope mismatch: {json.dumps(comparison, ensure_ascii=False)}")
        summary["ok"] = True
    finally:
        if dataset_id and document_ids:
            try:
                summary["cleanup"] = perform_cleanup(
                    api=api,
                    steps=steps,
                    dataset_id=dataset_id,
                    document_id=document_ids[0],
                    cleanup_mode="purge_dataset",
                    delete_dataset_after=bool(args.delete_dataset_after),
                    timeout=args.timeout,
                )
            except Exception as exc:  # pragma: no cover - best effort reporting
                summary["cleanup_error"] = str(exc)

    report = {"summary": summary, "steps": steps}
    (artifact_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(str(artifact_dir / "report.json"))
    return 0 if bool(summary.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
