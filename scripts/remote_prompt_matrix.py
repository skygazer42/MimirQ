#!/usr/bin/env python3
"""Run a remote prompt workflow matrix against a live MimirQ API."""

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


PROMPT_KEYS = {
    "answer": "rag_answer_claude_xml_zh",
    "kg": "kg_extract_graphrag_zh",
    "judge": "judge_faithfulness_ragas_zh",
    "testgen": "testset_generation_ragas_zh",
}


FIXTURES: list[dict[str, str]] = [
    {
        "filename": "alpha-rollout.md",
        "content": (
            "# Alpha Rollout\n\n"
            "Alpha rollout uses the blue flag and completed successfully on 2026-05-22.\n\n"
            "Alice led the rollout and documented the evidence requirements for future audits.\n"
        ),
    },
    {
        "filename": "beta-rollout.md",
        "content": (
            "# Beta Rollout\n\n"
            "Beta rollout uses the red flag and was paused after a rollback rehearsal.\n\n"
            "Bob led the rollback rehearsal for the beta environment.\n"
        ),
    },
]


def write_fixture(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def extract_first_event_id(body: Any) -> str:
    nodes = body.get("nodes") if isinstance(body, dict) else None
    if not isinstance(nodes, list):
        return ""
    for item in nodes:
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("id") or "").strip()
        if node_id.startswith("event:"):
            return node_id.split(":", 1)[1].strip()
    return ""


def first_generated_question_metadata_value(body: Any, key: str) -> Any:
    rows = body.get("generated_questions") if isinstance(body, dict) else None
    if not isinstance(rows, list) or not rows:
        return None
    first = rows[0] if isinstance(rows[0], dict) else {}
    metadata = first.get("metadata") if isinstance(first.get("metadata"), dict) else {}
    return metadata.get(key)


def poll_document_until_completed(
    api: LiveApi,
    *,
    document_id: str,
    steps: list[dict[str, Any]],
    timeout: int,
) -> dict[str, Any]:
    deadline = time.time() + int(timeout)
    last_body: dict[str, Any] = {}
    while time.time() < deadline:
        status, body, elapsed = api.json("GET", f"/api/v1/documents/{document_id}", timeout=timeout)
        doc_status = str((body or {}).get("status") or "")
        record_step(steps, "poll_document", status, body, elapsed, doc_status=doc_status)
        if not ok_status(status):
            raise RuntimeError(f"document poll failed: {snippet(body)}")
        last_body = body if isinstance(body, dict) else {}
        if doc_status.lower() == "completed":
            return last_body
        if doc_status.lower() in {"failed", "quarantined", "cancelled"}:
            raise RuntimeError(f"document terminal status={doc_status}: {snippet(body)}")
        time.sleep(2)
    raise RuntimeError(f"document did not complete in time: {document_id}")


def poll_regression_run(
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
            f"/api/v1/evaluations/ragas/regression/runs/{run_id}?include_items=true&include_contexts=false",
            timeout=timeout,
        )
        run = body.get("run") if isinstance(body, dict) and isinstance(body.get("run"), dict) else {}
        run_status = str(run.get("status") or "")
        record_step(steps, "poll_regression_run", status, body, elapsed, run_status=run_status)
        if not ok_status(status):
            raise RuntimeError(f"regression run poll failed: {snippet(body)}")
        if run_status.lower() == "completed":
            return body if isinstance(body, dict) else {}
        if run_status.lower() == "failed":
            raise RuntimeError(f"regression run failed: {snippet(body)}")
        time.sleep(2)
    raise RuntimeError(f"regression run did not complete in time: {run_id}")


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a remote prompt workflow matrix on a live MimirQ API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default="demo")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--poll-timeout", type=int, default=1800)
    parser.add_argument("--delete-dataset-after", action="store_true")
    args = parser.parse_args()

    run_id = time.strftime("%Y%m%d-%H%M%S")
    artifact_dir = Path(args.artifact_dir or f"artifacts/prompt-matrix/{run_id}").resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    api = LiveApi(args.base_url, args.tenant_id, args.account_id, args.user_id, args.timeout)
    steps: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "ok": False,
        "artifact_dir": str(artifact_dir),
        "base_url": args.base_url,
    }

    dataset_id = ""
    document_ids: list[str] = []
    regression_case_ids: list[str] = []
    try:
        status, body, elapsed = api.json("POST", "/api/v1/prompt-templates/builtins/sync", payload={}, timeout=args.timeout)
        record_step(steps, "sync_builtin_prompt_templates", status, body, elapsed)
        if not ok_status(status):
            raise RuntimeError(f"builtin prompt sync failed: {snippet(body)}")
        summary["prompt_templates_sync"] = body

        status, body, elapsed = api.json(
            "POST",
            "/api/v1/datasets/",
            payload={
                "name": f"Prompt Matrix {run_id}",
                "description": "Remote prompt workflow verification dataset",
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
            final_doc = poll_document_until_completed(api, document_id=document_id, steps=steps, timeout=args.poll_timeout)
            document_ids.append(document_id)
            if not summary.get("documents"):
                summary["documents"] = []
            summary["documents"].append(
                {
                    "document_id": document_id,
                    "filename": fixture["filename"],
                    "pipeline_hash": str((final_doc.get("metadata") or {}).get("active_pipeline_hash") or (final_doc.get("metadata") or {}).get("pipeline_hash") or ""),
                }
            )

        alpha_document_id = document_ids[0]
        alpha_pipeline_hash = str((summary["documents"][0] or {}).get("pipeline_hash") or "")

        status, body, elapsed = api.json(
            "POST",
            "/api/v1/rag/prompt-preview",
            payload={
                "query": "What color flag does the Alpha rollout use?",
                "dataset_id": dataset_id,
                "prompt_template_key": PROMPT_KEYS["answer"],
                "rag_config": {
                    "top_k": 4,
                    "score_threshold": 0.0,
                    "retrieval_mode": "hybrid",
                    "enable_reranker": False,
                    "enable_multi_query": False,
                    "enable_hyde": False,
                    "enable_query_decomposition": False,
                },
            },
            timeout=args.timeout,
        )
        record_step(steps, "prompt_preview", status, body, elapsed, citation_count=len((body or {}).get("citations") or []))
        if not ok_status(status):
            raise RuntimeError(f"prompt preview failed: {snippet(body)}")
        prompt_text = str((body or {}).get("prompt_text") or "")
        if str((body or {}).get("prompt_template_key") or "") != PROMPT_KEYS["answer"]:
            raise RuntimeError(f"prompt preview did not select expected template: {snippet(body)}")
        if "<context>" not in prompt_text or "Alpha rollout uses the blue flag" not in prompt_text:
            raise RuntimeError("prompt preview text missing expected context markers/content")
        summary["prompt_preview"] = {
            "prompt_template_key": body.get("prompt_template_key"),
            "citation_count": len((body or {}).get("citations") or []),
            "prompt_chars": len(prompt_text),
        }

        status, body, elapsed = api.json(
            "POST",
            "/api/v1/chat",
            payload={
                "message": "What color flag does the Alpha rollout use?",
                "dataset_id": dataset_id,
                "stream": False,
                "prompt_template_key": PROMPT_KEYS["answer"],
                "rag_config": {
                    "top_k": 4,
                    "score_threshold": 0.0,
                    "retrieval_mode": "hybrid",
                    "enable_reranker": False,
                    "enable_multi_query": False,
                    "enable_hyde": False,
                    "enable_query_decomposition": False,
                },
            },
            timeout=args.timeout,
        )
        record_step(steps, "chat_answer_prompt", status, body, elapsed)
        if not ok_status(status):
            raise RuntimeError(f"chat failed: {snippet(body)}")
        metrics = body.get("metrics") if isinstance(body, dict) and isinstance(body.get("metrics"), dict) else {}
        if str(metrics.get("prompt_template_key") or "") != PROMPT_KEYS["answer"]:
            raise RuntimeError(f"chat metrics missing expected prompt_template_key: {snippet(body)}")
        if len((body.get("citations") or [])) <= 0:
            raise RuntimeError("chat returned no citations")
        summary["chat"] = {
            "prompt_template_key": metrics.get("prompt_template_key"),
            "citation_count": len(body.get("citations") or []),
            "content_preview": str(body.get("content") or "")[:200],
        }

        status, body, elapsed = api.json(
            "POST",
            (
                f"/api/v1/kg/documents/{alpha_document_id}/extract"
                f"?replace_existing=true&extract_relations=false&extract_skills=false"
                f"&extraction_backend=llm&prompt_template_key={PROMPT_KEYS['kg']}"
            ),
            payload={},
            timeout=args.timeout,
        )
        record_step(steps, "kg_extract_prompt", status, body, elapsed)
        if not ok_status(status):
            raise RuntimeError(f"kg extract failed: {snippet(body)}")

        status, body, elapsed = api.json(
            "GET",
            f"/api/v1/kg/graph?document_ids={alpha_document_id}&pipeline_hash={alpha_pipeline_hash}&max_events=10&max_entities=20&max_links=20",
            timeout=args.timeout,
        )
        record_step(steps, "kg_graph", status, body, elapsed)
        if not ok_status(status):
            raise RuntimeError(f"kg graph failed: {snippet(body)}")
        event_id = extract_first_event_id(body)
        if not event_id:
            raise RuntimeError(f"kg graph returned no event nodes: {snippet(body)}")

        status, body, elapsed = api.json(
            "GET",
            f"/api/v1/kg/events/{event_id}?document_ids={alpha_document_id}&pipeline_hash={alpha_pipeline_hash}",
            timeout=args.timeout,
        )
        record_step(steps, "kg_event_detail", status, body, elapsed)
        if not ok_status(status):
            raise RuntimeError(f"kg event detail failed: {snippet(body)}")
        event = body.get("event") if isinstance(body, dict) and isinstance(body.get("event"), dict) else {}
        event_extra = event.get("extra_data") if isinstance(event.get("extra_data"), dict) else {}
        if str(event_extra.get("kg_prompt_template_key") or "") != PROMPT_KEYS["kg"]:
            raise RuntimeError(f"kg event extra_data missing expected prompt key: {snippet(body)}")
        summary["kg_extract"] = {
            "event_id": event_id,
            "kg_prompt_template_key": event_extra.get("kg_prompt_template_key"),
        }

        status, body, elapsed = api.json(
            "POST",
            "/api/v1/evaluations/ragas/test-gen/from-documents",
            payload={
                "dataset_id": dataset_id,
                "document_ids": [alpha_document_id],
                "num_questions": 2,
                "question_types": ["factual", "reasoning"],
                "auto_save_as_cases": True,
                "prompt_template_key": PROMPT_KEYS["testgen"],
            },
            timeout=args.timeout,
        )
        record_step(steps, "testgen_from_documents", status, body, elapsed)
        if not ok_status(status):
            raise RuntimeError(f"test generation failed: {snippet(body)}")
        generated_questions = body.get("generated_questions") if isinstance(body, dict) and isinstance(body.get("generated_questions"), list) else []
        regression_case_ids = [str(item) for item in (body.get("saved_case_ids") or []) if str(item).strip()]
        if len(generated_questions) <= 0 or len(regression_case_ids) <= 0:
            raise RuntimeError(f"test generation returned no questions/cases: {snippet(body)}")
        if first_generated_question_metadata_value(body, "prompt_template_key") != PROMPT_KEYS["testgen"]:
            raise RuntimeError(f"test generation metadata missing prompt_template_key: {snippet(body)}")
        summary["testgen"] = {
            "generated_questions": len(generated_questions),
            "saved_case_ids": regression_case_ids,
            "prompt_template_key": first_generated_question_metadata_value(body, "prompt_template_key"),
        }

        status, body, elapsed = api.json(
            "POST",
            "/api/v1/evaluations/ragas/regression/runs",
            payload={
                "case_ids": list(regression_case_ids),
                "dataset_id": dataset_id,
                "metrics": ["faithfulness_det"],
                "use_llm_judge": True,
                "skip_empty_contexts": True,
                "max_cases": len(regression_case_ids),
                "top_k": 4,
                "score_threshold": 0.0,
                "retrieval_mode": "hybrid",
                "enable_reranker": False,
                "prompt_template_key": PROMPT_KEYS["answer"],
                "judge_prompt_template_key": PROMPT_KEYS["judge"],
            },
            timeout=args.timeout,
        )
        record_step(steps, "create_regression_run", status, body, elapsed)
        if not ok_status(status):
            raise RuntimeError(f"create regression run failed: {snippet(body)}")
        run_id = str((body or {}).get("id") or "")
        if not run_id:
            raise RuntimeError(f"regression run response missing id: {snippet(body)}")

        run_detail = poll_regression_run(api, run_id=run_id, steps=steps, timeout=args.poll_timeout)
        run = run_detail.get("run") if isinstance(run_detail.get("run"), dict) else {}
        items = run_detail.get("items") if isinstance(run_detail.get("items"), list) else []
        summary_data = run.get("summary") if isinstance(run.get("summary"), dict) else {}
        if str(summary_data.get("llm_judge_prompt_template_key") or "") != PROMPT_KEYS["judge"]:
            raise RuntimeError(f"regression summary missing judge prompt key: {snippet(run_detail)}")
        first_item_meta = items[0].get("meta") if items and isinstance(items[0], dict) and isinstance(items[0].get("meta"), dict) else {}
        llm_judge_meta = first_item_meta.get("llm_judge") if isinstance(first_item_meta.get("llm_judge"), dict) else {}
        generation_meta = llm_judge_meta.get("generation") if isinstance(llm_judge_meta.get("generation"), dict) else {}
        if str(generation_meta.get("prompt_template_key") or "") != PROMPT_KEYS["judge"]:
            raise RuntimeError(f"regression item meta missing generation judge prompt key: {snippet(run_detail)}")
        summary["regression_run"] = {
            "run_id": run_id,
            "status": run.get("status"),
            "llm_judge_items": summary_data.get("llm_judge_items"),
            "llm_judge_prompt_template_key": summary_data.get("llm_judge_prompt_template_key"),
            "item_generation_prompt_template_key": generation_meta.get("prompt_template_key"),
        }

        summary["cleanup"] = delete_regression_cases(
            api,
            case_ids=regression_case_ids,
            steps=steps,
            timeout=args.timeout,
        )
        cleanup_summary = perform_cleanup(
            api=api,
            steps=steps,
            dataset_id=dataset_id,
            document_id=alpha_document_id,
            cleanup_mode="purge_dataset",
            delete_dataset_after=bool(args.delete_dataset_after),
            timeout=args.timeout,
        )
        summary["cleanup"].update(cleanup_summary)
        summary["ok"] = True
    except Exception as exc:  # noqa: BLE001
        summary["ok"] = False
        summary["error"] = str(exc)
    finally:
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
