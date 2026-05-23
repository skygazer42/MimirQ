#!/usr/bin/env python3
"""Run a remote KG usefulness matrix against a live MimirQ API."""

from __future__ import annotations

import argparse
import json
import re
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


FIXTURES: list[dict[str, str]] = [
    {
        "filename": "atlas-acquisition.md",
        "content": (
            "# Atlas Acquisition\n\n"
            "Project Atlas acquired Blue Harbor on 2026-01-10.\n"
        ),
    },
    {
        "filename": "integration-lead.md",
        "content": (
            "# Integration Lead\n\n"
            "After the acquisition, Mira Chen led the Blue Harbor integration program.\n"
        ),
    },
    {
        "filename": "orion-migration.md",
        "content": (
            "# Migration Outcome\n\n"
            "The Blue Harbor integration program migrated the Orion billing service.\n"
        ),
    },
]

QUESTIONS: list[dict[str, Any]] = [
    {
        "question": "Who led the integration program that followed Project Atlas's acquisition of Blue Harbor?",
        "expected_answer": "Mira Chen",
        "evidence_filenames": ["atlas-acquisition.md", "integration-lead.md"],
    },
    {
        "question": "Which service was migrated by the program led by Mira Chen?",
        "expected_answer": "Orion billing service",
        "evidence_filenames": ["integration-lead.md", "orion-migration.md"],
    },
]


def write_fixture(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def contains_expected_text(text: str, expected: str) -> bool:
    return normalize_text(expected) in normalize_text(text)


def kg_search_clue_count(body: Any) -> int:
    if isinstance(body, dict):
        if isinstance(body.get("result"), dict):
            clues = body["result"].get("clues")
            if isinstance(clues, list):
                return len(clues)
        clues = body.get("clues")
        if isinstance(clues, list):
            return len(clues)
    return 0


def diagnostics_item_for_question(body: Any, question: str) -> dict[str, Any] | None:
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return None
    target = normalize_text(question)
    for item in items:
        if not isinstance(item, dict):
            continue
        if normalize_text(str(item.get("question") or "")) == target:
            return item
    return None


def chunk_list(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, dict):
        rows = body.get("items")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
        rows = body.get("chunks")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    if isinstance(body, list):
        return [row for row in body if isinstance(row, dict)]
    return []


def delete_regression_cases(
    api: LiveApi,
    *,
    case_ids: list[str],
    steps: list[dict[str, Any]],
    timeout: int,
) -> dict[str, Any]:
    deleted = 0
    for case_id in case_ids:
        status, body, elapsed = api.json("DELETE", f"/api/v1/evaluations/ragas/regression/cases/{case_id}", timeout=timeout)
        record_step(steps, "cleanup:delete_regression_case", status, body, elapsed, case_id=case_id)
        if ok_status(status) or int(status) == 204:
            deleted += 1
            continue
        raise RuntimeError(f"delete regression case failed: {case_id} {snippet(body)}")
    return {"deleted_regression_cases": deleted}


def poll_document_until_completed(
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
        record_step(steps, "poll_document", status, body, elapsed, doc_status=doc_status)
        if not ok_status(status):
            raise RuntimeError(f"document poll failed: {snippet(body)}")
        if doc_status.lower() == "completed":
            return
        if doc_status.lower() in {"failed", "quarantined", "cancelled"}:
            raise RuntimeError(f"document terminal status={doc_status}: {snippet(body)}")
        time.sleep(2)
    raise RuntimeError(f"document did not complete: {document_id}")


def poll_kg_diagnostics_run(
    api: LiveApi,
    *,
    run_id: str,
    steps: list[dict[str, Any]],
    timeout: int,
) -> dict[str, Any]:
    deadline = time.time() + int(timeout)
    while time.time() < deadline:
        status, body, elapsed = api.json(
            "GET",
            f"/api/v1/evaluations/kg/search/diagnostics/runs/{run_id}",
            timeout=timeout,
        )
        run = body.get("run") if isinstance(body, dict) and isinstance(body.get("run"), dict) else {}
        run_status = str(run.get("status") or "")
        record_step(steps, "poll_kg_diagnostics_run", status, body, elapsed, run_status=run_status)
        if not ok_status(status):
            raise RuntimeError(f"kg diagnostics run poll failed: {snippet(body)}")
        if run_status.lower() == "completed":
            return body if isinstance(body, dict) else {}
        if run_status.lower() == "failed":
            raise RuntimeError(f"kg diagnostics run failed: {snippet(body)}")
        time.sleep(2)
    raise RuntimeError(f"kg diagnostics run did not complete: {run_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a remote KG usefulness matrix on a live MimirQ API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default="demo")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--poll-timeout", type=int, default=1800)
    parser.add_argument("--delete-dataset-after", action="store_true")
    args = parser.parse_args()

    run_id = time.strftime("%Y%m%d-%H%M%S")
    artifact_dir = Path(args.artifact_dir or f"artifacts/kg-usefulness-matrix/{run_id}").resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    api = LiveApi(args.base_url, args.tenant_id, args.account_id, args.user_id, args.timeout)
    steps: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "ok": False,
        "artifact_dir": str(artifact_dir),
        "base_url": args.base_url,
    }

    dataset_id = ""
    document_rows: list[dict[str, str]] = []
    regression_case_ids: list[str] = []
    try:
        status, body, elapsed = api.json(
            "POST",
            "/api/v1/datasets/",
            payload={
                "name": f"KG Usefulness Matrix {run_id}",
                "description": "Remote KG usefulness verification dataset",
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

        fixture_dir = artifact_dir / "fixtures"
        for fixture in FIXTURES:
            file_path = fixture_dir / fixture["filename"]
            write_fixture(file_path, fixture["content"])
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
                raise RuntimeError(f"upload failed for {fixture['filename']}: {snippet(body)}")
            document_id = str((body or {}).get("id") or (body or {}).get("document_id") or "")
            if not document_id:
                raise RuntimeError(f"upload missing document_id for {fixture['filename']}")
            poll_document_until_completed(api, document_id=document_id, steps=steps, timeout=args.poll_timeout)

            status, body, elapsed = api.json("GET", f"/api/v1/documents/{document_id}/chunks?limit=2000", timeout=args.timeout)
            record_step(steps, "list_chunks", status, body, elapsed, document_id=document_id)
            if not ok_status(status):
                raise RuntimeError(f"chunk listing failed for {fixture['filename']}: {snippet(body)}")
            rows = chunk_list(body)
            if not rows:
                raise RuntimeError(f"no chunks returned for {fixture['filename']}")
            chunk_id = str(rows[0].get("id") or "")
            if not chunk_id:
                raise RuntimeError(f"first chunk missing id for {fixture['filename']}")
            document_rows.append({"filename": fixture["filename"], "document_id": document_id, "chunk_id": chunk_id})

        filename_to_row = {row["filename"]: row for row in document_rows}
        summary["documents"] = list(document_rows)

        # Extract KG up front for all documents to remove extraction work from diagnostics timing.
        for row in document_rows:
            status, body, elapsed = api.json(
                "POST",
                f"/api/v1/kg/documents/{row['document_id']}/extract?replace_existing=true&extract_relations=false&extract_skills=false&extraction_backend=heuristic",
                payload={},
                timeout=args.timeout,
            )
            record_step(steps, "kg_extract", status, body, elapsed, document_id=row["document_id"])
            if not ok_status(status):
                raise RuntimeError(f"kg extract failed for {row['filename']}: {snippet(body)}")

        case_rows: list[dict[str, Any]] = []
        for item in QUESTIONS:
            reference_sources = []
            for filename in item["evidence_filenames"]:
                row = filename_to_row[filename]
                reference_sources.append({"document_id": row["document_id"], "chunk_id": row["chunk_id"]})
            status, body, elapsed = api.json(
                "POST",
                "/api/v1/evaluations/ragas/regression/cases",
                payload={
                    "dataset_id": dataset_id,
                    "question": item["question"],
                    "expected_answer": item["expected_answer"],
                    "reference_sources": reference_sources,
                    "tags": ["kg_usefulness", "multi_hop"],
                    "document_ids": [filename_to_row[filename]["document_id"] for filename in item["evidence_filenames"]],
                },
                timeout=args.timeout,
            )
            record_step(steps, "create_regression_case", status, body, elapsed, question=item["question"])
            if not ok_status(status):
                raise RuntimeError(f"create regression case failed: {snippet(body)}")
            case_id = str((body or {}).get("id") or "")
            if not case_id:
                raise RuntimeError(f"regression case missing id: {snippet(body)}")
            regression_case_ids.append(case_id)
            case_rows.append({"question": item["question"], "expected_answer": item["expected_answer"], "case_id": case_id})
        summary["cases"] = list(case_rows)

        # Direct KG search + baseline/graph chat for each question.
        question_results: list[dict[str, Any]] = []
        for item in QUESTIONS:
            question = item["question"]
            expected_answer = item["expected_answer"]

            status, body, elapsed = api.json(
                "POST",
                "/api/v1/kg/search",
                payload={"query": question, "dataset_id": dataset_id},
                timeout=args.timeout,
            )
            clue_count = kg_search_clue_count(body)
            result_payload = body.get("result") if isinstance(body, dict) and isinstance(body.get("result"), dict) else {}
            event_count = len(result_payload.get("events") or []) if isinstance(result_payload, dict) else 0
            record_step(steps, "kg_search", status, body, elapsed, question=question, clue_count=clue_count, event_count=event_count)
            if not ok_status(status):
                raise RuntimeError(f"kg search failed: {snippet(body)}")
            if clue_count <= 0:
                raise RuntimeError(f"kg search returned no clues for usefulness question: {question}")

            chat_rows: dict[str, Any] = {}
            for label, use_graph in (("chat_baseline", False), ("chat_graph", True)):
                status, body, elapsed = api.json(
                    "POST",
                    "/api/v1/chat",
                    payload={
                        "message": question,
                        "dataset_id": dataset_id,
                        "stream": False,
                        "rag_config": {
                            "top_k": 4,
                            "score_threshold": 0.0,
                            "retrieval_mode": "hybrid",
                            "enable_reranker": False,
                            "enable_multi_query": False,
                            "enable_hyde": False,
                            "enable_query_decomposition": False,
                            "use_graph": use_graph,
                            "answer_mode": "extractive",
                        },
                    },
                    timeout=args.timeout,
                )
                answer = str((body or {}).get("content") or (body or {}).get("answer") or "")
                citation_count = len((body or {}).get("citations") or []) if isinstance(body, dict) else 0
                record_step(steps, label, status, body, elapsed, question=question, citation_count=citation_count, answer_preview=answer[:200])
                if not ok_status(status):
                    raise RuntimeError(f"{label} failed: {snippet(body)}")
                matches_expected = contains_expected_text(answer, expected_answer)
                if use_graph and not matches_expected:
                    raise RuntimeError(f"{label} answer missing expected text for question: {question}")
                chat_rows[label] = {
                    "answer_preview": answer[:200],
                    "citation_count": citation_count,
                    "matches_expected": matches_expected,
                    "elapsed_sec": round(elapsed, 3),
                }

            question_results.append(
                {
                    "question": question,
                    "expected_answer": expected_answer,
                    "kg_search_clues": clue_count,
                    "kg_search_events": event_count,
                    **chat_rows,
                }
            )
        summary["question_results"] = question_results

        status, body, elapsed = api.json(
            "POST",
            "/api/v1/evaluations/kg/search/diagnostics",
            payload={
                "dataset_id": dataset_id,
                "case_ids": list(regression_case_ids),
                "max_cases": len(regression_case_ids),
                "k": 5,
                "auto_extract_kg": False,
                "hardcase_mode": "off",
                "hardcases_per_failed_case": 0,
                "max_failed_cases_for_hardcase": 0,
                "persist_run": True,
            },
            timeout=args.timeout,
        )
        record_step(steps, "kg_search_diagnostics", status, body, elapsed)
        if not ok_status(status):
            raise RuntimeError(f"kg search diagnostics failed: {snippet(body)}")
        summary_obj = body.get("summary") if isinstance(body, dict) and isinstance(body.get("summary"), dict) else {}
        items = body.get("items") if isinstance(body, dict) and isinstance(body.get("items"), list) else []
        run_id = str(body.get("run_id") or "") if isinstance(body, dict) else ""
        if float(summary_obj.get("baseline_hit_rate") or 0.0) < 1.0:
            raise RuntimeError(f"kg diagnostics baseline_hit_rate too low: {snippet(body)}")
        if float(summary_obj.get("baseline_recall") or 0.0) < 1.0:
            raise RuntimeError(f"kg diagnostics baseline_recall too low: {snippet(body)}")
        for item in QUESTIONS:
            diag_item = diagnostics_item_for_question({"items": items}, item["question"])
            if diag_item is None:
                raise RuntimeError(f"diagnostics missing item for question: {item['question']}")
            baseline = diag_item.get("baseline") if isinstance(diag_item.get("baseline"), dict) else {}
            metrics = baseline.get("metrics") if isinstance(baseline.get("metrics"), dict) else {}
            if bool(metrics.get("hit_at_k")) is not True:
                raise RuntimeError(f"diagnostics hit_at_k false for question: {item['question']}")
            if len(baseline.get("clues") or []) <= 0:
                raise RuntimeError(f"diagnostics baseline clues empty for question: {item['question']}")
        if run_id:
            run_detail = poll_kg_diagnostics_run(api, run_id=run_id, steps=steps, timeout=args.poll_timeout)
            summary["kg_diagnostics_run"] = {
                "run_id": run_id,
                "status": ((run_detail.get("run") or {}).get("status") if isinstance(run_detail.get("run"), dict) else None),
            }
        summary["kg_diagnostics"] = {
            "run_id": run_id or None,
            "baseline_hit_rate": summary_obj.get("baseline_hit_rate"),
            "baseline_recall": summary_obj.get("baseline_recall"),
            "failure_breakdown": summary_obj.get("failure_breakdown"),
        }

        cleanup = delete_regression_cases(api, case_ids=regression_case_ids, steps=steps, timeout=args.timeout)
        cleanup.update(
            perform_cleanup(
                api=api,
                steps=steps,
                dataset_id=dataset_id,
                document_id=document_rows[0]["document_id"],
                cleanup_mode="purge_dataset",
                delete_dataset_after=bool(args.delete_dataset_after),
                timeout=args.timeout,
            )
        )
        summary["cleanup"] = cleanup
        summary["ok"] = True
    except Exception as exc:  # noqa: BLE001
        summary["ok"] = False
        summary["error"] = str(exc)
    finally:
        if dataset_id and document_rows and not summary.get("cleanup"):
            cleanup: dict[str, Any] = {}
            try:
                if regression_case_ids:
                    cleanup.update(delete_regression_cases(api, case_ids=regression_case_ids, steps=steps, timeout=args.timeout))
                cleanup.update(
                    perform_cleanup(
                        api=api,
                        steps=steps,
                        dataset_id=dataset_id,
                        document_id=document_rows[0]["document_id"],
                        cleanup_mode="purge_dataset",
                        delete_dataset_after=bool(args.delete_dataset_after),
                        timeout=args.timeout,
                    )
                )
            except Exception as cleanup_exc:  # noqa: BLE001
                cleanup["error"] = str(cleanup_exc)
            if cleanup:
                summary["cleanup"] = cleanup
        summary["steps"] = steps
        report_path = artifact_dir / "report.json"
        report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "ok": summary.get("ok"),
                    "artifact_dir": str(artifact_dir),
                    "dataset_id": summary.get("dataset_id"),
                    "error": summary.get("error"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
