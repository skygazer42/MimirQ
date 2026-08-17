#!/usr/bin/env python3
"""Run a remote KG usefulness matrix against a live MimirQ API."""

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


ensure_repo_root_on_sys_path(__file__)


def load_runtime_deps() -> tuple[Any, Any, Any, Any, Any, Any]:
    from scripts.remote_real_pdf_chain import (
        DEFAULT_TENANT_ID,
        LiveApi,
        ok_status,
        perform_cleanup,
        record_step,
        snippet,
    )

    return (
        DEFAULT_TENANT_ID,
        LiveApi,
        ok_status,
        perform_cleanup,
        record_step,
        snippet,
    )


(
    DEFAULT_TENANT_ID,
    LiveApi,
    ok_status,
    perform_cleanup,
    record_step,
    snippet,
) = load_runtime_deps()


FIXTURES: list[dict[str, str]] = [
    {
        "filename": "atlas-acquisition.md",
        "content": ("# Atlas Acquisition\n\nProject Atlas acquired Blue Harbor on 2026-01-10.\n"),
    },
    {
        "filename": "integration-lead.md",
        "content": (
            "# Integration Lead\n\nAfter the acquisition, Mira Chen led the Blue Harbor integration program.\n"
        ),
    },
    {
        "filename": "orion-migration.md",
        "content": ("# Migration Outcome\n\nThe Blue Harbor integration program migrated the Orion billing service.\n"),
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

SUMMARY_QUESTIONS: list[dict[str, Any]] = [
    {
        "question": "What happened after Project Atlas acquired Blue Harbor?",
        "expected_answer": (
            "After Project Atlas acquired Blue Harbor, Mira Chen led the integration program "
            "that migrated the Orion billing service."
        ),
        "expected_terms": ["Project Atlas", "Blue Harbor", "Mira Chen", "Orion billing service"],
        "min_expected_terms": 3,
        "require_expected_match": False,
        "min_citations": 3,
        "evidence_filenames": ["atlas-acquisition.md", "integration-lead.md", "orion-migration.md"],
    },
    {
        "question": "Summarize this corpus in one sentence.",
        "expected_answer": (
            "Project Atlas acquired Blue Harbor, Mira Chen led the integration program, "
            "and that program migrated the Orion billing service."
        ),
        "expected_terms": ["Project Atlas", "Blue Harbor", "Mira Chen", "Orion billing service"],
        "min_expected_terms": 3,
        "require_expected_match": False,
        "min_citations": 3,
        "evidence_filenames": ["atlas-acquisition.md", "integration-lead.md", "orion-migration.md"],
    },
    {
        "question": "What is the overall story across these documents?",
        "expected_answer": (
            "The documents describe Project Atlas acquiring Blue Harbor, Mira Chen leading "
            "integration, and the Orion billing service migration."
        ),
        "expected_terms": ["Project Atlas", "Blue Harbor", "Mira Chen", "Orion billing service"],
        "min_expected_terms": 3,
        "require_expected_match": False,
        "min_citations": 3,
        "evidence_filenames": ["atlas-acquisition.md", "integration-lead.md", "orion-migration.md"],
    },
]


def write_fixture(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def contains_expected_text(text: str, expected: str) -> bool:
    return normalize_text(expected) in normalize_text(text)


def answer_match_summary(item: dict[str, Any], answer: str) -> dict[str, Any]:
    expected_terms = [str(term) for term in (item.get("expected_terms") or []) if str(term).strip()]
    matched_terms = [term for term in expected_terms if contains_expected_text(answer, term)]
    min_expected_terms = int(item.get("min_expected_terms") or (len(expected_terms) if expected_terms else 0))

    if expected_terms:
        matches = len(matched_terms) >= max(1, min_expected_terms)
    else:
        matches = contains_expected_text(answer, str(item.get("expected_answer") or ""))

    return {
        "matches_expectation": matches,
        "expected_terms": expected_terms,
        "matched_terms": matched_terms,
        "matched_term_count": len(matched_terms),
        "min_expected_terms": min_expected_terms,
    }


def chat_expectation_summary(item: dict[str, Any], answer: str, *, citation_count: int) -> dict[str, Any]:
    match = answer_match_summary(item, answer)
    min_citations = int(item.get("min_citations") or 1)
    require_expected_match = bool(item.get("require_expected_match", True))
    passes_gate = int(citation_count) >= max(1, min_citations) and (
        not require_expected_match or bool(match["matches_expectation"])
    )
    return {
        **match,
        "citation_count": int(citation_count),
        "min_citations": min_citations,
        "require_expected_match": require_expected_match,
        "passes_gate": passes_gate,
    }


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
    api: Any,
    *,
    case_ids: list[str],
    steps: list[dict[str, Any]],
    timeout: int,
) -> dict[str, Any]:
    deleted = 0
    for case_id in case_ids:
        status, body, elapsed = api.json(
            "DELETE",
            f"/api/v1/evaluations/ragas/regression/cases/{case_id}",
            timeout=timeout,
        )
        record_step(
            steps,
            "cleanup:delete_regression_case",
            status,
            body,
            elapsed,
            case_id=case_id,
        )
        if ok_status(status) or int(status) == 204:
            deleted += 1
            continue
        raise RuntimeError(f"delete regression case failed: {case_id} {snippet(body)}")
    return {"deleted_regression_cases": deleted}


def poll_document_until_completed(
    api: Any,
    *,
    document_id: str,
    steps: list[dict[str, Any]],
    timeout: int,
) -> None:
    deadline = time.time() + int(timeout)
    while time.time() < deadline:
        status, body, elapsed = api.json(
            "GET",
            f"/api/v1/documents/{document_id}",
            timeout=timeout,
        )
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
    api: Any,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a remote KG usefulness matrix on a live MimirQ API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default="demo")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--poll-timeout", type=int, default=1800)
    parser.add_argument("--delete-dataset-after", action="store_true")
    return parser


def build_artifact_dir(*, artifact_dir_arg: str, run_id: str) -> Path:
    artifact_dir = Path(artifact_dir_arg or f"artifacts/kg-usefulness-matrix/{run_id}").resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir


def create_dataset(
    api: Any,
    *,
    run_id: str,
    steps: list[dict[str, Any]],
    timeout: int,
) -> str:
    status, body, elapsed = api.json(
        "POST",
        "/api/v1/datasets/",
        payload={
            "name": f"KG Usefulness Matrix {run_id}",
            "description": "Remote KG usefulness verification dataset",
            "default_parser_backend": "basic",
            "default_chunk_strategy": "langchain_recursive",
        },
        timeout=timeout,
    )
    record_step(steps, "create_dataset", status, body, elapsed)
    if not ok_status(status):
        raise RuntimeError(f"create_dataset failed: {snippet(body)}")

    dataset_id = str((body or {}).get("id") or (body or {}).get("dataset_id") or "")
    if not dataset_id:
        raise RuntimeError(f"create_dataset missing id: {snippet(body)}")
    return dataset_id


def upload_fixture_documents(
    api: Any,
    *,
    artifact_dir: Path,
    dataset_id: str,
    steps: list[dict[str, Any]],
    timeout: int,
    poll_timeout: int,
) -> list[dict[str, str]]:
    document_rows: list[dict[str, str]] = []
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
            timeout=timeout,
        )
        record_step(
            steps,
            "upload_document",
            status,
            body,
            elapsed,
            filename=fixture["filename"],
        )
        if not ok_status(status):
            raise RuntimeError(f"upload failed for {fixture['filename']}: {snippet(body)}")

        document_id = str((body or {}).get("id") or (body or {}).get("document_id") or "")
        if not document_id:
            raise RuntimeError(f"upload missing document_id for {fixture['filename']}")

        poll_document_until_completed(
            api,
            document_id=document_id,
            steps=steps,
            timeout=poll_timeout,
        )

        status, body, elapsed = api.json(
            "GET",
            f"/api/v1/documents/{document_id}/chunks?limit=2000",
            timeout=timeout,
        )
        record_step(steps, "list_chunks", status, body, elapsed, document_id=document_id)
        if not ok_status(status):
            raise RuntimeError(f"chunk listing failed for {fixture['filename']}: {snippet(body)}")

        rows = chunk_list(body)
        if not rows:
            raise RuntimeError(f"no chunks returned for {fixture['filename']}")

        chunk_id = str(rows[0].get("id") or "")
        if not chunk_id:
            raise RuntimeError(f"first chunk missing id for {fixture['filename']}")

        document_rows.append(
            {
                "filename": fixture["filename"],
                "document_id": document_id,
                "chunk_id": chunk_id,
            }
        )

    return document_rows


def extract_kg_documents(
    api: Any,
    *,
    document_rows: list[dict[str, str]],
    steps: list[dict[str, Any]],
    timeout: int,
) -> None:
    for row in document_rows:
        status, body, elapsed = api.json(
            "POST",
            (
                f"/api/v1/kg/documents/{row['document_id']}/extract"
                "?replace_existing=true&extract_relations=false"
                "&extract_skills=false&extraction_backend=heuristic"
            ),
            payload={},
            timeout=timeout,
        )
        record_step(steps, "kg_extract", status, body, elapsed, document_id=row["document_id"])
        if not ok_status(status):
            raise RuntimeError(f"kg extract failed for {row['filename']}: {snippet(body)}")


def create_regression_cases(
    api: Any,
    *,
    dataset_id: str,
    document_rows: list[dict[str, str]],
    steps: list[dict[str, Any]],
    timeout: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    case_rows: list[dict[str, Any]] = []
    regression_case_ids: list[str] = []
    filename_to_row = {row["filename"]: row for row in document_rows}

    for item in QUESTIONS:
        reference_sources = []
        document_ids = []
        for filename in item["evidence_filenames"]:
            row = filename_to_row[filename]
            reference_sources.append({"document_id": row["document_id"], "chunk_id": row["chunk_id"]})
            document_ids.append(row["document_id"])

        status, body, elapsed = api.json(
            "POST",
            "/api/v1/evaluations/ragas/regression/cases",
            payload={
                "dataset_id": dataset_id,
                "question": item["question"],
                "expected_answer": item["expected_answer"],
                "reference_sources": reference_sources,
                "tags": ["kg_usefulness", "multi_hop"],
                "document_ids": document_ids,
            },
            timeout=timeout,
        )
        record_step(
            steps,
            "create_regression_case",
            status,
            body,
            elapsed,
            question=item["question"],
        )
        if not ok_status(status):
            raise RuntimeError(f"create regression case failed: {snippet(body)}")

        case_id = str((body or {}).get("id") or "")
        if not case_id:
            raise RuntimeError(f"regression case missing id: {snippet(body)}")

        regression_case_ids.append(case_id)
        case_rows.append(
            {
                "question": item["question"],
                "expected_answer": item["expected_answer"],
                "case_id": case_id,
            }
        )

    return case_rows, regression_case_ids


def build_chat_payload(*, dataset_id: str, question: str, use_graph: bool) -> dict[str, Any]:
    return {
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
    }


def run_chat_variant(
    api: Any,
    *,
    dataset_id: str,
    item: dict[str, Any],
    question: str,
    label: str,
    use_graph: bool,
    steps: list[dict[str, Any]],
    timeout: int,
) -> dict[str, Any]:
    status, body, elapsed = api.json(
        "POST",
        "/api/v1/chat",
        payload=build_chat_payload(
            dataset_id=dataset_id,
            question=question,
            use_graph=use_graph,
        ),
        timeout=timeout,
    )
    answer = str((body or {}).get("content") or (body or {}).get("answer") or "")
    citation_count = len((body or {}).get("citations") or []) if isinstance(body, dict) else 0
    record_step(
        steps,
        label,
        status,
        body,
        elapsed,
        question=question,
        citation_count=citation_count,
        answer_preview=answer[:200],
    )
    if not ok_status(status):
        raise RuntimeError(f"{label} failed: {snippet(body)}")

    chat_expectation = chat_expectation_summary(item, answer, citation_count=citation_count)
    if not bool(chat_expectation["passes_gate"]):
        raise RuntimeError(f"{label} answer did not satisfy expectation for question: {question} :: {answer[:300]}")

    return {
        "answer_preview": answer[:200],
        "citation_count": citation_count,
        "matches_expected": bool(chat_expectation["matches_expectation"]),
        "matched_terms": list(chat_expectation["matched_terms"]),
        "matched_term_count": int(chat_expectation["matched_term_count"]),
        "expected_terms": list(chat_expectation["expected_terms"]),
        "min_expected_terms": int(chat_expectation["min_expected_terms"]),
        "min_citations": int(chat_expectation["min_citations"]),
        "require_expected_match": bool(chat_expectation["require_expected_match"]),
        "passes_gate": bool(chat_expectation["passes_gate"]),
        "elapsed_sec": round(elapsed, 3),
    }


def run_question_matrix(
    api: Any,
    *,
    dataset_id: str,
    steps: list[dict[str, Any]],
    timeout: int,
) -> list[dict[str, Any]]:
    question_results: list[dict[str, Any]] = []
    for item in [*QUESTIONS, *SUMMARY_QUESTIONS]:
        question = item["question"]
        status, body, elapsed = api.json(
            "POST",
            "/api/v1/kg/search",
            payload={"query": question, "dataset_id": dataset_id},
            timeout=timeout,
        )
        clue_count = kg_search_clue_count(body)
        result_payload = body.get("result") if isinstance(body, dict) else {}
        if not isinstance(result_payload, dict):
            result_payload = {}
        event_count = len(result_payload.get("events") or [])
        record_step(
            steps,
            "kg_search",
            status,
            body,
            elapsed,
            question=question,
            clue_count=clue_count,
            event_count=event_count,
        )
        if not ok_status(status):
            raise RuntimeError(f"kg search failed: {snippet(body)}")
        if clue_count <= 0:
            raise RuntimeError(f"kg search returned no clues for usefulness question: {question}")

        question_results.append(
            {
                "question": question,
                "expected_answer": item["expected_answer"],
                "expected_terms": list(item.get("expected_terms") or []),
                "kg_search_clues": clue_count,
                "kg_search_events": event_count,
                "chat_baseline": run_chat_variant(
                    api,
                    dataset_id=dataset_id,
                    item=item,
                    question=question,
                    label="chat_baseline",
                    use_graph=False,
                    steps=steps,
                    timeout=timeout,
                ),
                "chat_graph": run_chat_variant(
                    api,
                    dataset_id=dataset_id,
                    item=item,
                    question=question,
                    label="chat_graph",
                    use_graph=True,
                    steps=steps,
                    timeout=timeout,
                ),
            }
        )

    return question_results


def parse_kg_diagnostics_body(body: Any) -> tuple[dict[str, Any], list[Any], str]:
    summary_obj = body.get("summary") if isinstance(body, dict) else {}
    if not isinstance(summary_obj, dict):
        summary_obj = {}
    items = body.get("items") if isinstance(body, dict) else []
    if not isinstance(items, list):
        items = []
    run_id = str(body.get("run_id") or "") if isinstance(body, dict) else ""
    return summary_obj, items, run_id


def validate_kg_diagnostics(
    *,
    body: Any,
    summary_obj: dict[str, Any],
    items: list[Any],
) -> None:
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


def run_kg_diagnostics(
    api: Any,
    *,
    dataset_id: str,
    regression_case_ids: list[str],
    steps: list[dict[str, Any]],
    timeout: int,
    poll_timeout: int,
) -> dict[str, Any]:
    status, body, elapsed = api.json(
        "POST",
        "/api/v1/evaluations/kg/search/diagnostics",
        payload={
            "dataset_id": dataset_id,
            "case_ids": regression_case_ids,
            "max_cases": len(regression_case_ids),
            "k": 5,
            "auto_extract_kg": False,
            "hardcase_mode": "off",
            "hardcases_per_failed_case": 0,
            "max_failed_cases_for_hardcase": 0,
            "persist_run": True,
        },
        timeout=timeout,
    )
    record_step(steps, "kg_search_diagnostics", status, body, elapsed)
    if not ok_status(status):
        raise RuntimeError(f"kg search diagnostics failed: {snippet(body)}")

    summary_obj, items, run_id = parse_kg_diagnostics_body(body)
    validate_kg_diagnostics(body=body, summary_obj=summary_obj, items=items)

    result = {
        "kg_diagnostics": {
            "run_id": run_id or None,
            "baseline_hit_rate": summary_obj.get("baseline_hit_rate"),
            "baseline_recall": summary_obj.get("baseline_recall"),
            "failure_breakdown": summary_obj.get("failure_breakdown"),
        },
        "kg_diagnostics_run": None,
    }
    if run_id:
        run_detail = poll_kg_diagnostics_run(
            api,
            run_id=run_id,
            steps=steps,
            timeout=poll_timeout,
        )
        run_body = run_detail.get("run") if isinstance(run_detail.get("run"), dict) else {}
        run_status = run_body.get("status") if isinstance(run_body, dict) else None
        result["kg_diagnostics_run"] = {"run_id": run_id, "status": run_status}

    return result


def run_cleanup(
    api: Any,
    *,
    dataset_id: str,
    document_rows: list[dict[str, str]],
    regression_case_ids: list[str],
    steps: list[dict[str, Any]],
    delete_dataset_after: bool,
    timeout: int,
) -> dict[str, Any]:
    cleanup = delete_regression_cases(
        api,
        case_ids=regression_case_ids,
        steps=steps,
        timeout=timeout,
    )
    cleanup.update(
        perform_cleanup(
            api=api,
            steps=steps,
            dataset_id=dataset_id,
            document_id=document_rows[0]["document_id"],
            cleanup_mode="purge_dataset",
            delete_dataset_after=delete_dataset_after,
            timeout=timeout,
        )
    )
    return cleanup


def maybe_cleanup(
    api: Any,
    *,
    summary: dict[str, Any],
    dataset_id: str,
    document_rows: list[dict[str, str]],
    regression_case_ids: list[str],
    steps: list[dict[str, Any]],
    delete_dataset_after: bool,
    timeout: int,
) -> None:
    if not dataset_id or not document_rows or summary.get("cleanup"):
        return

    cleanup: dict[str, Any] = {}
    try:
        if regression_case_ids:
            cleanup.update(
                delete_regression_cases(
                    api,
                    case_ids=regression_case_ids,
                    steps=steps,
                    timeout=timeout,
                )
            )
        cleanup.update(
            perform_cleanup(
                api=api,
                steps=steps,
                dataset_id=dataset_id,
                document_id=document_rows[0]["document_id"],
                cleanup_mode="purge_dataset",
                delete_dataset_after=delete_dataset_after,
                timeout=timeout,
            )
        )
    except Exception as cleanup_exc:
        cleanup["error"] = str(cleanup_exc)

    if cleanup:
        summary["cleanup"] = cleanup


def write_summary_report(
    *,
    artifact_dir: Path,
    summary: dict[str, Any],
    steps: list[dict[str, Any]],
) -> None:
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


def main() -> int:
    args = build_parser().parse_args()
    run_id = time.strftime("%Y%m%d-%H%M%S")
    artifact_dir = build_artifact_dir(artifact_dir_arg=args.artifact_dir, run_id=run_id)
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
        dataset_id = create_dataset(
            api,
            run_id=run_id,
            steps=steps,
            timeout=args.timeout,
        )
        summary["dataset_id"] = dataset_id

        document_rows = upload_fixture_documents(
            api,
            artifact_dir=artifact_dir,
            dataset_id=dataset_id,
            steps=steps,
            timeout=args.timeout,
            poll_timeout=args.poll_timeout,
        )
        summary["documents"] = document_rows

        extract_kg_documents(
            api,
            document_rows=document_rows,
            steps=steps,
            timeout=args.timeout,
        )

        case_rows, regression_case_ids = create_regression_cases(
            api,
            dataset_id=dataset_id,
            document_rows=document_rows,
            steps=steps,
            timeout=args.timeout,
        )
        summary["cases"] = case_rows
        summary["question_results"] = run_question_matrix(
            api,
            dataset_id=dataset_id,
            steps=steps,
            timeout=args.timeout,
        )

        diagnostics = run_kg_diagnostics(
            api,
            dataset_id=dataset_id,
            regression_case_ids=regression_case_ids,
            steps=steps,
            timeout=args.timeout,
            poll_timeout=args.poll_timeout,
        )
        summary["kg_diagnostics"] = diagnostics["kg_diagnostics"]
        if diagnostics["kg_diagnostics_run"] is not None:
            summary["kg_diagnostics_run"] = diagnostics["kg_diagnostics_run"]

        summary["cleanup"] = run_cleanup(
            api,
            dataset_id=dataset_id,
            document_rows=document_rows,
            regression_case_ids=regression_case_ids,
            steps=steps,
            delete_dataset_after=bool(args.delete_dataset_after),
            timeout=args.timeout,
        )
        summary["ok"] = True
    except Exception as exc:
        summary["ok"] = False
        summary["error"] = str(exc)
    finally:
        maybe_cleanup(
            api,
            summary=summary,
            dataset_id=dataset_id,
            document_rows=document_rows,
            regression_case_ids=regression_case_ids,
            steps=steps,
            delete_dataset_after=bool(args.delete_dataset_after),
            timeout=args.timeout,
        )
        write_summary_report(artifact_dir=artifact_dir, summary=summary, steps=steps)
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
