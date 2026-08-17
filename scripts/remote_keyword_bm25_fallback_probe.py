#!/usr/bin/env python3
"""Verify keyword-mode BM25 fallback on xlsx corpora against a live API."""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any


def ensure_repo_root_on_sys_path(script_path: str | Path) -> str:
    repo_root = Path(script_path).resolve().parents[1]
    for entry in sys.path:
        try:
            if Path(entry or ".").resolve() == repo_root:
                return str(repo_root)
        except (OSError, RuntimeError):
            continue
    sys.path.insert(0, str(repo_root))
    return str(repo_root)


ensure_repo_root_on_sys_path(__file__)


def _load_remote_kb_boundary_matrix() -> tuple[Any, ...]:
    from scripts.remote_kb_boundary_matrix import (
        LiveApi,
        citation_document_ids,
        ensure_success,
        record_step,
        response_text_from_body,
        wait_for_document_completed,
    )

    return (
        LiveApi,
        citation_document_ids,
        ensure_success,
        record_step,
        response_text_from_body,
        wait_for_document_completed,
    )


(
    LiveApi,
    citation_document_ids,
    ensure_success,
    record_step,
    response_text_from_body,
    wait_for_document_completed,
) = _load_remote_kb_boundary_matrix()


DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"
REPO_ROOT = Path(__file__).resolve().parents[1]
WORD_FIXTURE = REPO_ROOT / "tests/fixtures/parsing_golden_broader/word_project_brief_docx/input/sample.docx"
XLSX_FIXTURE = REPO_ROOT / "tests/fixtures/parsing_golden_broader/excel_budget_sheet_xlsx/input/sample.xlsx"


def keyword_metrics(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {}
    metrics = body.get("metrics")
    if not isinstance(metrics, dict):
        return {}
    per_query = metrics.get("retrieval_per_query")
    if not isinstance(per_query, list) or not per_query:
        return {}
    first = per_query[0]
    if not isinstance(first, dict):
        return {}
    return dict(first.get("retriever_debug") or {})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run xlsx keyword->BM25 fallback verification against a live API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default="demo")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--poll-timeout", type=int, default=600)
    return parser.parse_args(argv)


def build_keyword_scenarios(fixtures: dict[str, Path]) -> list[dict[str, Any]]:
    return [
        {
            "name": "xlsx_only_bm25",
            "files": [fixtures["xlsx"]],
            "require_first_doc": True,
        },
        {
            "name": "xlsx_mixed_bm25",
            "files": [fixtures["xlsx"], fixtures["docx"], fixtures["csv"], fixtures["yaml"], fixtures["html"]],
            "require_first_doc": True,
        },
    ]


def _channel_box(channels: Any, key: str) -> dict[str, Any]:
    if isinstance(channels, dict) and isinstance(channels.get(key), dict):
        return channels.get(key) or {}
    return {}


def _append_keyword_id_failures(
    failures: list[str],
    *,
    name: str,
    xlsx_document_id: str,
    retrieve_ids: list[str],
    chat_ids: list[str],
    require_first_doc: bool,
) -> None:
    if not retrieve_ids or xlsx_document_id not in retrieve_ids:
        failures.append(f"{name}: retrieve_missing_xlsx actual={retrieve_ids}")
    if not chat_ids or xlsx_document_id not in chat_ids:
        failures.append(f"{name}: chat_missing_xlsx actual={chat_ids}")
    if require_first_doc and retrieve_ids and retrieve_ids[0] != xlsx_document_id:
        failures.append(f"{name}: retrieve_first_doc expected={xlsx_document_id} actual={retrieve_ids[0]}")
    if require_first_doc and chat_ids and chat_ids[0] != xlsx_document_id:
        failures.append(f"{name}: chat_first_doc expected={xlsx_document_id} actual={chat_ids[0]}")


def _append_keyword_metric_failures(
    failures: list[str],
    *,
    name: str,
    vector_box: dict[str, Any],
    lexical_box: dict[str, Any],
    keyword_strategy: dict[str, Any],
    counts: dict[str, Any],
) -> None:
    vector_candidates = int(vector_box.get("candidates") or 0)
    if vector_candidates != 0:
        failures.append(f"{name}: vector_candidates expected=0 actual={vector_candidates}")
    bm25_candidates = int(counts.get("bm25_candidates") or 0)
    if bm25_candidates < 1:
        failures.append(f"{name}: bm25_candidates expected>=1 actual={bm25_candidates}")
    if bool(keyword_strategy.get("bm25_used")) is not True:
        failures.append(f"{name}: bm25_used expected=true actual={keyword_strategy.get('bm25_used')!r}")
    if bool(keyword_strategy.get("lexical_db_used")) is not False:
        failures.append(f"{name}: lexical_db_used expected=false actual={keyword_strategy.get('lexical_db_used')!r}")
    lexical_candidates = int(lexical_box.get("candidates") or 0)
    if lexical_candidates != 0:
        failures.append(f"{name}: lexical_candidates expected=0 actual={lexical_candidates}")


def _append_keyword_text_failures(failures: list[str], *, name: str, chat_body: Any) -> None:
    lowered = response_text_from_body(chat_body).casefold()
    if "review" not in lowered:
        failures.append(f"{name}: chat_missing_review")
    if "apac" not in lowered:
        failures.append(f"{name}: chat_missing_apac")


def evaluate_keyword_case(
    *,
    name: str,
    xlsx_document_id: str,
    retrieve_body: Any,
    chat_body: Any,
    require_first_doc: bool,
) -> list[str]:
    failures: list[str] = []

    retrieve_ids = citation_document_ids(retrieve_body)
    chat_ids = citation_document_ids(chat_body)
    retrieve_debug = keyword_metrics(retrieve_body)
    channels = retrieve_debug.get("channels") if isinstance(retrieve_debug.get("channels"), dict) else {}
    vector_box = _channel_box(channels, "vector")
    lexical_box = _channel_box(channels, "lexical_db")
    keyword_strategy = _channel_box(channels, "keyword_strategy")
    counts = retrieve_debug.get("counts") if isinstance(retrieve_debug.get("counts"), dict) else {}

    _append_keyword_id_failures(
        failures,
        name=name,
        xlsx_document_id=xlsx_document_id,
        retrieve_ids=retrieve_ids,
        chat_ids=chat_ids,
        require_first_doc=require_first_doc,
    )
    _append_keyword_metric_failures(
        failures,
        name=name,
        vector_box=vector_box,
        lexical_box=lexical_box,
        keyword_strategy=keyword_strategy,
        counts=counts,
    )
    _append_keyword_text_failures(failures, name=name, chat_body=chat_body)
    return failures


def prepare_fixture_files(fixtures_dir: Path) -> dict[str, Path]:
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    html_path = fixtures_dir / "kb-page.html"
    html_path.write_text(
        "<!doctype html><html><body><p>Token HTML-CASCADE belongs only to the "
        "HTML page.</p><p>Owner: Hugo Cascade.</p></body></html>",
        encoding="utf-8",
    )
    csv_path = fixtures_dir / "kb-metrics.csv"
    csv_path.write_text("token,owner,status\nCSV-RIDGE,Rita Ridge,healthy\n", encoding="utf-8")
    yaml_path = fixtures_dir / "kb-config.yaml"
    yaml_path.write_text("token: YAML-CINDER\nowner: Yara Cinder\nstatus: approved\n", encoding="utf-8")
    word_target = fixtures_dir / "word-project-brief.docx"
    xlsx_target = fixtures_dir / "excel-budget-sheet.xlsx"
    shutil.copy2(WORD_FIXTURE, word_target)
    shutil.copy2(XLSX_FIXTURE, xlsx_target)
    return {
        "html": html_path,
        "csv": csv_path,
        "yaml": yaml_path,
        "docx": word_target,
        "xlsx": xlsx_target,
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


def _keyword_rag_config() -> dict[str, Any]:
    return {
        "top_k": 4,
        "score_threshold": 0.0,
        "retrieval_mode": "keyword",
        "enable_reranker": False,
        "enable_multi_query": False,
        "enable_hyde": False,
        "enable_query_decomposition": False,
    }


def create_keyword_dataset(api: LiveApi, *, run_id: str, scenario_name: str, steps: list[dict[str, Any]]) -> str:
    resp = api.json(
        "POST",
        "/api/v1/datasets/",
        payload={
            "name": f"Keyword BM25 Fallback {scenario_name} {run_id}",
            "description": "xlsx keyword lexical miss fallback verification.",
            "permission": "all_team_members",
            "default_parser_backend": "auto",
            "default_chunk_strategy": "langchain_recursive",
            "pipeline": {
                "governance_enabled": True,
                "persist_parsed_content": True,
                "persist_parsed_content_max_chars": 200000,
                "chunk_size": 1200,
                "chunk_overlap": 120,
                "chunk_vector_enabled": False,
                "bm25_index_enabled": True,
                "kg_enabled": False,
                "event_vector_enabled": False,
                "entity_vector_enabled": False,
            },
        },
    )
    record_step(steps, f"create_dataset:{scenario_name}", resp)
    ensure_success(f"create_dataset:{scenario_name}", resp)
    dataset_id = str((resp.body or {}).get("id") or (resp.body or {}).get("dataset_id") or "")
    if not dataset_id:
        raise RuntimeError(f"create_dataset:{scenario_name} missing dataset id")
    return dataset_id


def upload_keyword_scenario_files(
    api: LiveApi,
    *,
    dataset_id: str,
    scenario: dict[str, Any],
    steps: list[dict[str, Any]],
    poll_timeout: int,
) -> tuple[str, list[dict[str, str]]]:
    xlsx_document_id = ""
    uploaded: list[dict[str, str]] = []
    for file_path in scenario["files"]:
        resp = api.multipart(
            "POST",
            "/api/v1/documents/upload",
            fields={
                "dataset_id": dataset_id,
                "parser_backend": "auto",
                "chunk_strategy": "langchain_recursive",
                "governance_enabled": "true",
                "chunk_vector_enabled": "false",
                "bm25_index_enabled": "true",
                "kg_enabled": "false",
                "event_vector_enabled": "false",
                "entity_vector_enabled": "false",
            },
            file_path=file_path,
        )
        record_step(steps, f"upload:{scenario['name']}:{file_path.name}", resp)
        ensure_success(f"upload:{scenario['name']}:{file_path.name}", resp)
        document_id = str((resp.body or {}).get("id") or (resp.body or {}).get("document_id") or "")
        if not document_id:
            raise RuntimeError(f"upload:{scenario['name']}:{file_path.name} missing document id")
        if file_path.suffix.lower() == ".xlsx":
            xlsx_document_id = document_id
        uploaded.append({"name": file_path.name, "document_id": document_id})
        wait_for_document_completed(
            api,
            steps=steps,
            filename=f"{scenario['name']}:{file_path.name}",
            document_id=document_id,
            poll_timeout=poll_timeout,
        )
    if not xlsx_document_id:
        raise RuntimeError(f"{scenario['name']} missing xlsx document id")
    return xlsx_document_id, uploaded


def run_keyword_scenario(
    api: LiveApi,
    *,
    dataset_id: str,
    scenario: dict[str, Any],
    steps: list[dict[str, Any]],
    rag_config: dict[str, Any],
    poll_timeout: int,
) -> dict[str, Any]:
    xlsx_document_id, uploaded = upload_keyword_scenario_files(
        api,
        dataset_id=dataset_id,
        scenario=scenario,
        steps=steps,
        poll_timeout=poll_timeout,
    )

    retrieve_resp = api.json(
        "POST",
        "/api/v1/rag/retrieve-preview",
        payload={
            "query": "In the Excel budget sheet, what status belongs to APAC?",
            "dataset_id": dataset_id,
            "rag_config": rag_config,
        },
    )
    record_step(steps, f"retrieve:{scenario['name']}", retrieve_resp)
    ensure_success(f"retrieve:{scenario['name']}", retrieve_resp)

    chat_resp = api.json(
        "POST",
        "/api/v1/chat",
        payload={
            "message": "In the Excel budget sheet, what status belongs to APAC?",
            "dataset_id": dataset_id,
            "stream": False,
            "rag_config": {**rag_config, "answer_mode": "extractive", "max_tokens": 300},
        },
    )
    record_step(steps, f"chat:{scenario['name']}", chat_resp)
    ensure_success(f"chat:{scenario['name']}", chat_resp)

    failures = evaluate_keyword_case(
        name=str(scenario["name"]),
        xlsx_document_id=xlsx_document_id,
        retrieve_body=retrieve_resp.body,
        chat_body=chat_resp.body,
        require_first_doc=bool(scenario["require_first_doc"]),
    )
    return {
        "name": scenario["name"],
        "dataset_id": dataset_id,
        "xlsx_document_id": xlsx_document_id,
        "uploaded": uploaded,
        "retrieve_citation_document_ids": citation_document_ids(retrieve_resp.body),
        "chat_citation_document_ids": citation_document_ids(chat_resp.body),
        "ok": not failures,
        "failures": failures,
    }


def cleanup_keyword_datasets(
    api: LiveApi,
    *,
    steps: list[dict[str, Any]],
    dataset_ids: list[str],
    existing_rows: Any = None,
) -> list[dict[str, Any]]:
    rows = existing_rows if isinstance(existing_rows, list) else []
    for dataset_id in list(dataset_ids):
        rows.append(cleanup_dataset(api, steps=steps, dataset_id=dataset_id))
    dataset_ids.clear()
    return rows


def run_keyword_probe(args: argparse.Namespace) -> tuple[Path, dict[str, Any], list[dict[str, Any]], int]:
    run_id = time.strftime("%Y%m%d-%H%M%S")
    artifact_dir = Path(args.artifact_dir or f"artifacts/keyword-bm25-fallback/{run_id}").resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    fixtures = prepare_fixture_files(artifact_dir / "fixtures")
    api = LiveApi(args.base_url, args.tenant_id, args.account_id, args.user_id, args.timeout)
    rag_config = _keyword_rag_config()

    steps: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "ok": False,
        "artifact_dir": str(artifact_dir),
        "base_url": args.base_url,
        "cases": [],
    }
    datasets_to_cleanup: list[str] = []

    try:
        resp = api.json("GET", "/api/v1/health")
        record_step(steps, "health", resp)
        ensure_success("health", resp)

        for scenario in build_keyword_scenarios(fixtures):
            dataset_id = create_keyword_dataset(
                api,
                run_id=run_id,
                scenario_name=str(scenario["name"]),
                steps=steps,
            )
            datasets_to_cleanup.append(dataset_id)
            result = run_keyword_scenario(
                api,
                dataset_id=dataset_id,
                scenario=scenario,
                steps=steps,
                rag_config=rag_config,
                poll_timeout=args.poll_timeout,
            )
            summary["cases"].append(result)
            if result["failures"]:
                raise RuntimeError(f"keyword fallback case failed {scenario['name']}: {result['failures']}")

        summary["cleanup"] = cleanup_keyword_datasets(api, steps=steps, dataset_ids=datasets_to_cleanup)
        summary["ok"] = True
        return_code = 0
    except Exception as exc:  # noqa: BLE001
        summary["ok"] = False
        summary["error"] = str(exc)
        return_code = 1
    finally:
        if datasets_to_cleanup:
            summary["cleanup"] = cleanup_keyword_datasets(
                api,
                steps=steps,
                dataset_ids=datasets_to_cleanup,
                existing_rows=summary.get("cleanup"),
            )
    return artifact_dir, summary, steps, return_code


def main(argv: list[str] | None = None) -> int:
    artifact_dir, summary, steps, return_code = run_keyword_probe(parse_args(argv))
    report = {"summary": summary, "steps": steps}
    (artifact_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
