#!/usr/bin/env python3
"""Verify chunking breadth on real parsed outputs against a live API."""

from __future__ import annotations

import argparse
import json
import os
import shutil
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
    from scripts.remote_kb_boundary_matrix import (
        LiveApi,
        ensure_success,
        list_count,
        parsed_text_from_response,
        record_step,
        snippet,
        wait_for_document_completed,
    )
except ModuleNotFoundError:
    ensure_repo_root_on_sys_path(__file__)
    from scripts.remote_kb_boundary_matrix import (
        LiveApi,
        ensure_success,
        list_count,
        parsed_text_from_response,
        record_step,
        snippet,
        wait_for_document_completed,
    )


DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"
REPO_ROOT = Path(__file__).resolve().parents[1]
WORD_FIXTURE = REPO_ROOT / "tests/fixtures/parsing_golden_broader/word_project_brief_docx/input/sample.docx"
XLSX_FIXTURE = REPO_ROOT / "tests/fixtures/parsing_golden_broader/excel_budget_sheet_xlsx/input/sample.xlsx"
SMALL_PDF_FIXTURE = REPO_ROOT / "tests/fixtures/parsing_golden_broader/mixed_layout_pdf/input/sample.pdf"
LONG_PDF_FALLBACK = REPO_ROOT / "artifacts/production-readiness/20260522-020117/corpus/rfc9000-quic.pdf"
LONG_PDF_URL = "https://www.rfc-editor.org/rfc/rfc9000.pdf"
DOCUMENT_CHUNK_LIST_LIMIT = 2000


def maybe_copy_or_download_long_pdf(target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "rfc9000-quic.pdf"
    if LONG_PDF_FALLBACK.exists():
        shutil.copy2(LONG_PDF_FALLBACK, target)
        return target
    if str(os.getenv("MIMIRQ_REMOTE_FIXTURE_DOWNLOADS", "") or "").strip().lower() not in {"1", "true", "yes", "on"}:
        shutil.copy2(SMALL_PDF_FIXTURE, target)
        return target
    from urllib.request import Request, urlopen

    request = Request(LONG_PDF_URL, headers={"User-Agent": "MimirQ remote chunking matrix"})
    with urlopen(request, timeout=300) as response:
        target.write_bytes(response.read())
    return target


def prepare_fixture_files(fixtures_dir: Path) -> list[dict[str, Any]]:
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    markdown_path = fixtures_dir / "chunking-handbook.md"
    markdown_path.write_text(
        "# Rollout Handbook\n\n"
        "MimirQ rollout notes explain parser service health, retrieval tuning, and governance cleanup.\n\n"
        "## Parser Service\n\n"
        "MagicPDF is the primary PDF path for production.\n\n"
        "## Retrieval\n\n"
        "Citations must remain grounded in persisted chunks.\n",
        encoding="utf-8",
    )

    html_path = fixtures_dir / "chunking-portal.html"
    html_path.write_text(
        "<!doctype html><html><body><h1>Operations Portal</h1>"
        "<p>MimirQ tracks parser health, dataset coverage, and audit evidence.</p>"
        "<p>HTML normalization should still preserve the key operational facts.</p>"
        "</body></html>",
        encoding="utf-8",
    )

    csv_path = fixtures_dir / "chunking-metrics.csv"
    csv_path.write_text(
        "region,status,owner,token\n"
        "APAC,Review,Rina Vale,CSV-APAC\n"
        "EU,Healthy,Evan Peak,CSV-EU\n",
        encoding="utf-8",
    )

    word_target = fixtures_dir / "word-project-brief.docx"
    xlsx_target = fixtures_dir / "excel-budget-sheet.xlsx"
    pdf_target = fixtures_dir / "mixed-layout.pdf"
    shutil.copy2(WORD_FIXTURE, word_target)
    shutil.copy2(XLSX_FIXTURE, xlsx_target)
    shutil.copy2(SMALL_PDF_FIXTURE, pdf_target)
    long_pdf_target = maybe_copy_or_download_long_pdf(fixtures_dir)

    return [
        {
            "name": "markdown_handbook",
            "file_type": "md",
            "path": markdown_path,
            "parser_backend": "auto",
            "persist_chunk_strategy": "langchain_recursive",
            "preview_strategies": [
                "langchain_recursive",
                "markdown_hierarchy",
                "semantic_sentence",
                "parent_child",
                "separator",
            ],
            "min_chunks": 1,
            "min_parsed_chars": 80,
        },
        {
            "name": "html_portal",
            "file_type": "html",
            "path": html_path,
            "parser_backend": "auto",
            "persist_chunk_strategy": "langchain_recursive",
            "preview_strategies": [
                "langchain_recursive",
                "markdown_hierarchy",
                "semantic_sentence",
                "parent_child",
            ],
            "min_chunks": 1,
            "min_parsed_chars": 80,
        },
        {
            "name": "csv_metrics",
            "file_type": "csv",
            "path": csv_path,
            "parser_backend": "auto",
            "persist_chunk_strategy": "langchain_recursive",
            "preview_strategies": [
                "langchain_recursive",
                "csv_rows",
                "markdown_table",
            ],
            "min_chunks": 1,
            "min_parsed_chars": 30,
        },
        {
            "name": "word_project_brief_docx",
            "file_type": "docx",
            "path": word_target,
            "parser_backend": "auto",
            "persist_chunk_strategy": "langchain_recursive",
            "preview_strategies": [
                "langchain_recursive",
                "semantic_sentence",
                "parent_child",
            ],
            "min_chunks": 1,
            "min_parsed_chars": 100,
        },
        {
            "name": "excel_budget_sheet_xlsx",
            "file_type": "xlsx",
            "path": xlsx_target,
            "parser_backend": "auto",
            "persist_chunk_strategy": "langchain_recursive",
            "preview_strategies": [
                "langchain_recursive",
                "csv_rows",
                "markdown_table",
            ],
            "min_chunks": 1,
            "min_parsed_chars": 80,
        },
        {
            "name": "mixed_layout_pdf",
            "file_type": "pdf",
            "path": pdf_target,
            "parser_backend": "magicpdf",
            "persist_chunk_strategy": "langchain_recursive",
            "preview_strategies": [
                "langchain_recursive",
                "markdown_hierarchy",
                "semantic_sentence",
                "parent_child",
            ],
            "min_chunks": 1,
            "min_parsed_chars": 300,
        },
        {
            "name": "rfc9000_long_pdf",
            "file_type": "pdf",
            "path": long_pdf_target,
            "parser_backend": "magicpdf",
            "persist_chunk_strategy": "langchain_recursive",
            "preview_strategies": [
                "langchain_recursive",
                "markdown_hierarchy",
                "semantic_sentence",
                "parent_child",
            ],
            "min_chunks": 100,
            "min_parsed_chars": 100000,
            "preview_include_chunks": False,
        },
    ]


def preview_strategy_fields(case: dict[str, Any], strategy: str) -> dict[str, str]:
    include_chunks = "false" if not bool(case.get("preview_include_chunks", True)) else "true"
    fields: dict[str, str] = {
        "parser_backend": str(case.get("parser_backend") or "auto"),
        "chunk_strategy": str(strategy),
        "chunk_size": "1200",
        "chunk_overlap": "120",
        "include_original_text": "false",
        "include_chunks": include_chunks,
        "use_parse_cache": "true",
        "max_chunks": "0" if include_chunks == "false" else "4000",
    }
    if strategy == "separator":
        fields.update(
            {
                "separator_preset": "paragraph",
                "keep_separator": "true",
                "separator_max_chunk_size": "0",
            }
        )
    if strategy == "parent_child":
        fields.update(
            {
                "child_ratio": "0.5",
                "min_child_size": "240",
            }
        )
    return fields


def empty_chunk_count(body: Any) -> int | None:
    if not isinstance(body, dict):
        return None
    chunks = body.get("chunks")
    if not isinstance(chunks, list):
        return None
    total = 0
    for item in chunks:
        if not isinstance(item, dict):
            continue
        if not str(item.get("content") or "").strip():
            total += 1
    return total


def summarize_preview_result(case: dict[str, Any], strategy: str, body: Any) -> dict[str, Any]:
    payload = body if isinstance(body, dict) else {}
    stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
    quality_gate = payload.get("quality_gate") if isinstance(payload.get("quality_gate"), dict) else {}
    return {
        "case": str(case.get("name") or ""),
        "strategy": str(strategy),
        "parser_backend": str(case.get("parser_backend") or "auto"),
        "total_chunks": int(payload.get("total_chunks") or list_count(payload)),
        "total_chunks_full": int(payload.get("total_chunks_full") or payload.get("total_chunks") or list_count(payload)),
        "avg_chunk_length": int(stats.get("avg") or 0),
        "coverage_ratio": float(stats.get("coverage_ratio") or 0.0),
        "overlap_waste_ratio": float(stats.get("overlap_waste_ratio") or 0.0),
        "short_count": int(stats.get("short_count") or 0),
        "duplicate_count": int(stats.get("duplicate_count") or 0),
        "gap_count": int(stats.get("gap_count") or 0),
        "histogram_bins": len(stats.get("histogram") or []) if isinstance(stats.get("histogram"), list) else 0,
        "empty_chunks": empty_chunk_count(payload),
        "quality_grade": str(quality_gate.get("grade") or ""),
        "chunks_truncated": bool(payload.get("chunks_truncated")),
        "parse_cache_hit": bool(payload.get("parse_cache_hit")),
    }


def evaluate_persisted_case(case: dict[str, Any], *, detail: dict[str, Any], chunk_items: list[dict[str, Any]], parsed_chars: int) -> list[str]:
    failures: list[str] = []
    name = str(case.get("name") or "case")
    chunk_count = int(list_count({"items": chunk_items}) or 0)
    min_chunks = int(case.get("min_chunks") or 0)
    min_parsed_chars = int(case.get("min_parsed_chars") or 0)
    metadata = detail.get("metadata") if isinstance(detail.get("metadata"), dict) else {}
    stats = metadata.get("chunking_stats") if isinstance(metadata.get("chunking_stats"), dict) else {}
    coverage = metadata.get("chunk_coverage") if isinstance(metadata.get("chunk_coverage"), dict) else {}
    first_meta = chunk_items[0].get("metadata") if chunk_items and isinstance(chunk_items[0].get("metadata"), dict) else {}
    empty_chunks = sum(1 for item in chunk_items if not str(item.get("content") or "").strip())

    if str(detail.get("status") or "").lower() != "completed":
        failures.append(f"{name}: status={detail.get('status')}")
    if min_chunks and chunk_count < min_chunks:
        failures.append(f"{name}: min_chunks={min_chunks} actual={chunk_count}")
    if min_parsed_chars and parsed_chars < min_parsed_chars:
        failures.append(f"{name}: min_parsed_chars={min_parsed_chars} actual={parsed_chars}")
    if not isinstance(stats, dict) or int(stats.get("count") or 0) <= 0:
        failures.append(f"{name}: missing chunking_stats")
    if not isinstance(coverage, dict) or float(coverage.get("coverage_ratio") or 0.0) <= 0.0:
        failures.append(f"{name}: missing chunk_coverage")
    if str(first_meta.get("chunk_strategy") or "").strip() != str(case.get("persist_chunk_strategy") or "").strip():
        failures.append(
            f"{name}: persisted chunk_strategy expected={case.get('persist_chunk_strategy')} actual={first_meta.get('chunk_strategy')}"
        )
    if empty_chunks > 0:
        failures.append(f"{name}: empty persisted chunks={empty_chunks}")
    return failures


def evaluate_preview_summary(case: dict[str, Any], preview: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    name = str(case.get("name") or "case")
    strategy = str(preview.get("strategy") or "")
    total_chunks = int(preview.get("total_chunks_full") or preview.get("total_chunks") or 0)
    avg_chunk_length = int(preview.get("avg_chunk_length") or 0)
    coverage_ratio = float(preview.get("coverage_ratio") or 0.0)
    overlap_waste_ratio = float(preview.get("overlap_waste_ratio") or 0.0)
    empty_chunks = preview.get("empty_chunks")

    if total_chunks <= 0:
        failures.append(f"{name}:{strategy}: total_chunks={total_chunks}")
    if avg_chunk_length <= 0:
        failures.append(f"{name}:{strategy}: avg_chunk_length={avg_chunk_length}")
    if not (0.0 <= coverage_ratio <= 1.0):
        failures.append(f"{name}:{strategy}: coverage_ratio={coverage_ratio}")
    if not (0.0 <= overlap_waste_ratio <= 1.0):
        failures.append(f"{name}:{strategy}: overlap_waste_ratio={overlap_waste_ratio}")
    if empty_chunks is not None and int(empty_chunks) > 0:
        failures.append(f"{name}:{strategy}: empty_chunks={empty_chunks}")
    return failures


def summarize_profile_summary(body: Any) -> dict[str, Any]:
    payload = body if isinstance(body, dict) else {}
    return {
        "total_documents": int(payload.get("total_documents") or 0),
        "chunk_count_histogram_bins": len(payload.get("chunk_count_histogram") or []) if isinstance(payload.get("chunk_count_histogram"), list) else 0,
        "avg_chunk_chars_histogram_bins": len(payload.get("avg_chunk_chars_histogram") or []) if isinstance(payload.get("avg_chunk_chars_histogram"), list) else 0,
        "chunk_length_histogram_bins": len(payload.get("chunk_length_histogram") or []) if isinstance(payload.get("chunk_length_histogram"), list) else 0,
        "chunk_coverage_histogram_bins": len(payload.get("chunk_coverage_histogram") or []) if isinstance(payload.get("chunk_coverage_histogram"), list) else 0,
        "chunk_overlap_waste_histogram_bins": len(payload.get("chunk_overlap_waste_histogram") or []) if isinstance(payload.get("chunk_overlap_waste_histogram"), list) else 0,
        "by_file_type": dict(payload.get("by_file_type") or {}) if isinstance(payload.get("by_file_type"), dict) else {},
    }


def evaluate_profile_summary(summary: dict[str, Any], *, expected_documents: int, expected_file_types: set[str]) -> list[str]:
    failures: list[str] = []
    if int(summary.get("total_documents") or 0) != int(expected_documents):
        failures.append(
            f"profile: total_documents expected={expected_documents} actual={summary.get('total_documents')}"
        )
    for field in (
        "chunk_count_histogram_bins",
        "avg_chunk_chars_histogram_bins",
        "chunk_length_histogram_bins",
        "chunk_coverage_histogram_bins",
        "chunk_overlap_waste_histogram_bins",
    ):
        if int(summary.get(field) or 0) <= 0:
            failures.append(f"profile: missing {field}")
    file_types = set(str(item) for item in (summary.get("by_file_type") or {}).keys())
    missing_types = sorted(expected_file_types - file_types)
    if missing_types:
        failures.append(f"profile: missing file types {missing_types}")
    return failures


def cleanup_dataset(api: LiveApi, *, steps: list[dict[str, Any]], dataset_id: str) -> dict[str, Any]:
    summary: dict[str, Any] = {"dataset_id": dataset_id}
    resp = api.json("POST", f"/api/v1/datasets/{dataset_id}/purge?dry_run=false&max_delete=2000", payload={})
    record_step(steps, f"cleanup:purge:{dataset_id}", resp)
    ensure_success(f"cleanup:purge:{dataset_id}", resp)
    summary["purge_deleted"] = int((resp.body or {}).get("deleted") or 0) if isinstance(resp.body, dict) else 0

    resp = api.json("GET", f"/api/v1/datasets/{dataset_id}/documents/export?export_format=json&limit=50")
    record_step(steps, f"cleanup:export:{dataset_id}", resp, remaining=list_count(resp.body))
    ensure_success(f"cleanup:export:{dataset_id}", resp)
    if int(list_count(resp.body) or 0) > 0:
        raise RuntimeError(f"cleanup export still returns documents: {snippet(resp.body)}")

    resp = api.json("DELETE", f"/api/v1/datasets/{dataset_id}")
    record_step(steps, f"cleanup:delete_dataset:{dataset_id}", resp)
    if not 200 <= int(resp.status) < 300 and int(resp.status) != 204:
        raise RuntimeError(f"cleanup delete dataset failed: {snippet(resp.body)}")
    summary["delete_dataset_status"] = int(resp.status)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run remote chunking verification on real parsed outputs.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default="demo")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--poll-timeout", type=int, default=3600)
    args = parser.parse_args()

    run_id = time.strftime("%Y%m%d-%H%M%S")
    artifact_dir = Path(args.artifact_dir or f"artifacts/chunking-matrix/{run_id}").resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    cases = prepare_fixture_files(artifact_dir / "fixtures")
    api = LiveApi(args.base_url, args.tenant_id, args.account_id, args.user_id, args.timeout)

    steps: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "ok": False,
        "artifact_dir": str(artifact_dir),
        "base_url": args.base_url,
        "dataset_id": "",
        "persisted_cases": [],
        "preview_checks": [],
        "profile_summary": {},
        "cleanup": {},
        "failures": [],
    }

    dataset_id = ""
    failures: list[str] = []

    try:
        resp = api.json("GET", "/api/v1/health")
        record_step(steps, "health", resp)
        ensure_success("health", resp)

        resp = api.json(
            "POST",
            "/api/v1/datasets/",
            payload={
                "name": f"Chunking Matrix {run_id}",
                "description": "Chunking breadth verification on real parsed outputs.",
                "permission": "all_team_members",
                "default_parser_backend": "auto",
                "default_chunk_strategy": "langchain_recursive",
                "pipeline": {
                    "governance_enabled": True,
                    "persist_parsed_content": True,
                    "persist_parsed_content_max_chars": 400000,
                    "chunk_size": 1200,
                    "chunk_overlap": 120,
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

        for case in cases:
            upload_fields = {
                "dataset_id": dataset_id,
                "parser_backend": str(case.get("parser_backend") or "auto"),
                "chunk_strategy": str(case.get("persist_chunk_strategy") or "langchain_recursive"),
                "governance_enabled": "true",
                "chunk_vector_enabled": "true",
                "bm25_index_enabled": "true",
                "kg_enabled": "false",
                "event_vector_enabled": "false",
                "entity_vector_enabled": "false",
            }
            resp = api.multipart("POST", "/api/v1/documents/upload", fields=upload_fields, file_path=Path(case["path"]))
            record_step(steps, f"upload:{case['name']}", resp)
            ensure_success(f"upload:{case['name']}", resp)
            document_id = str((resp.body or {}).get("id") or (resp.body or {}).get("document_id") or "")
            if not document_id:
                raise RuntimeError(f"upload:{case['name']} missing document id")

            detail = wait_for_document_completed(
                api,
                steps=steps,
                filename=str(case["name"]),
                document_id=document_id,
                poll_timeout=args.poll_timeout,
            )
            detail_resp = api.json("GET", f"/api/v1/documents/{document_id}")
            record_step(steps, f"detail:{case['name']}", detail_resp)
            ensure_success(f"detail:{case['name']}", detail_resp)
            detail = detail_resp.body if isinstance(detail_resp.body, dict) else detail

            chunks_resp = api.json("GET", f"/api/v1/documents/{document_id}/chunks?limit={DOCUMENT_CHUNK_LIST_LIMIT}")
            chunk_items = list((chunks_resp.body or {}).get("items") or []) if isinstance(chunks_resp.body, dict) else []
            record_step(steps, f"chunks:{case['name']}", chunks_resp, chunk_count=len(chunk_items))
            ensure_success(f"chunks:{case['name']}", chunks_resp)

            parsed_resp = api.json("GET", f"/api/v1/documents/{document_id}/parsed-content?max_chars=25000")
            parsed_chars = max(
                len(parsed_text_from_response(parsed_resp.body)),
                int(detail.get("total_characters") or 0),
            )
            record_step(steps, f"parsed:{case['name']}", parsed_resp, parsed_chars=parsed_chars)
            ensure_success(f"parsed:{case['name']}", parsed_resp)

            case_row = {
                "name": str(case["name"]),
                "file_type": str(case["file_type"]),
                "document_id": document_id,
                "status": str(detail.get("status") or ""),
                "chunk_count": int((chunks_resp.body or {}).get("total") or len(chunk_items)) if isinstance(chunks_resp.body, dict) else len(chunk_items),
                "parsed_chars": parsed_chars,
                "empty_persisted_chunks": sum(1 for item in chunk_items if not str(item.get("content") or "").strip()),
                "chunking_stats": (detail.get("metadata") or {}).get("chunking_stats") if isinstance(detail.get("metadata"), dict) else None,
                "chunk_coverage": (detail.get("metadata") or {}).get("chunk_coverage") if isinstance(detail.get("metadata"), dict) else None,
                "first_chunk_metadata": (chunk_items[0].get("metadata") or {}) if chunk_items and isinstance(chunk_items[0].get("metadata"), dict) else {},
            }
            case_failures = evaluate_persisted_case(case, detail=detail, chunk_items=chunk_items, parsed_chars=parsed_chars)
            case_row["failures"] = case_failures
            if case_failures:
                failures.extend(case_failures)
            summary["persisted_cases"].append(case_row)

            for strategy in [item for item in case.get("preview_strategies") or [] if str(item).strip()]:
                preview_fields = preview_strategy_fields(case, str(strategy))
                preview_resp = api.multipart(
                    "POST",
                    "/api/v1/documents/chunk-preview",
                    fields=preview_fields,
                    file_path=Path(case["path"]),
                    timeout=args.timeout,
                )
                preview_row = summarize_preview_result(case, str(strategy), preview_resp.body)
                record_step(
                    steps,
                    f"preview:{case['name']}:{strategy}",
                    preview_resp,
                    total_chunks=preview_row["total_chunks_full"],
                    avg_chunk_length=preview_row["avg_chunk_length"],
                    parse_cache_hit=preview_row["parse_cache_hit"],
                )
                ensure_success(f"preview:{case['name']}:{strategy}", preview_resp)
                preview_failures = evaluate_preview_summary(case, preview_row)
                preview_row["elapsed_sec"] = round(float(preview_resp.elapsed_sec), 3)
                preview_row["failures"] = preview_failures
                if preview_failures:
                    failures.extend(preview_failures)
                summary["preview_checks"].append(preview_row)

        profile_resp = api.json("GET", f"/api/v1/datasets/{dataset_id}/profile/summary")
        record_step(steps, "profile:summary", profile_resp)
        ensure_success("profile:summary", profile_resp)
        profile_summary = summarize_profile_summary(profile_resp.body)
        profile_failures = evaluate_profile_summary(
            profile_summary,
            expected_documents=len(cases),
            expected_file_types={str(case["file_type"]) for case in cases},
        )
        profile_summary["failures"] = profile_failures
        if profile_failures:
            failures.extend(profile_failures)
        summary["profile_summary"] = profile_summary
    finally:
        if dataset_id:
            try:
                summary["cleanup"] = cleanup_dataset(api, steps=steps, dataset_id=dataset_id)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"cleanup: {exc}")
                summary["cleanup"] = {"dataset_id": dataset_id, "error": str(exc)}

    summary["failures"] = failures
    summary["ok"] = not failures
    summary["steps"] = steps

    report_json = artifact_dir / "report.json"
    report_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Remote Chunking Matrix",
        "",
        f"- ok: `{summary['ok']}`",
        f"- dataset_id: `{summary.get('dataset_id') or '-'}`",
        f"- persisted_cases: `{len(summary.get('persisted_cases') or [])}`",
        f"- preview_checks: `{len(summary.get('preview_checks') or [])}`",
        f"- failures: `{len(summary.get('failures') or [])}`",
        "",
        "## Persisted Cases",
    ]
    for item in summary.get("persisted_cases") or []:
        lines.append(
            f"- {item['name']}: status={item['status']} chunks={item['chunk_count']} parsed_chars={item['parsed_chars']} empty={item['empty_persisted_chunks']}"
        )
    lines.append("")
    lines.append("## Preview Checks")
    for item in summary.get("preview_checks") or []:
        lines.append(
            f"- {item['case']} / {item['strategy']}: total_chunks={item['total_chunks_full']} avg={item['avg_chunk_length']} "
            f"coverage={item['coverage_ratio']:.3f} overlap={item['overlap_waste_ratio']:.3f} elapsed={item['elapsed_sec']}s"
        )
    if failures:
        lines.append("")
        lines.append("## Failures")
        for failure in failures:
            lines.append(f"- {failure}")
    (artifact_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({"ok": summary["ok"], "artifact_dir": str(artifact_dir), "dataset_id": summary.get("dataset_id")}, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
