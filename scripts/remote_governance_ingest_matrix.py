#!/usr/bin/env python3
"""Run a remote governance ingest matrix against a live MimirQ API.

This script validates governance behavior on real document ingestion paths:
- upload -> parse -> governance -> persisted parsed content
- chunk persistence
- retrieval preview safety for sanitized documents
- quarantine behavior for low-signal documents
"""

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
        DOCUMENT_CHUNK_LIST_LIMIT,
        LiveApi,
        list_count,
        ok_status,
        parsed_text_from_response,
        perform_cleanup,
        record_step,
        snippet,
    )
except ModuleNotFoundError:
    ensure_repo_root_on_sys_path(__file__)
    from scripts.remote_real_pdf_chain import (
        DEFAULT_TENANT_ID,
        DOCUMENT_CHUNK_LIST_LIMIT,
        LiveApi,
        list_count,
        ok_status,
        parsed_text_from_response,
        perform_cleanup,
        record_step,
        snippet,
    )

BASE_PIPELINE: dict[str, Any] = {
    "governance_enabled": True,
    "persist_parsed_content": True,
    "persist_parsed_content_max_chars": 200000,
    "chunk_size": 600,
    "chunk_overlap": 80,
    "chunk_vector_enabled": True,
    "bm25_index_enabled": True,
    "kg_enabled": False,
    "event_vector_enabled": False,
    "entity_vector_enabled": False,
}


CASES: list[dict[str, Any]] = [
    {
        "name": "pii_mask",
        "filename": "pii-note.md",
        "parser_backend": "basic",
        "chunk_strategy": "langchain_recursive",
        "content": (
            "# Governance Contact\n\n"
            "Contact alice@example.com or call 13800138000 for rollout coordination.\n\n"
            "This note explains the parser rollout for tenant alpha.\n"
        ),
        "query": "What placeholder replaced the contact details?",
        "pipeline": {
            "governance_pii_anonymize": True,
            "governance_pii_mode": "mask",
            "governance_pii_mask": "[PII]",
        },
        "expected_status": "completed",
        "required_metadata_keys": ["governance_pii_hits"],
        "present_in_parsed": ["[PII]", "tenant alpha"],
        "absent_in_parsed": ["alice@example.com", "13800138000"],
        "present_in_chunks": ["[PII]"],
        "absent_in_chunks": ["alice@example.com", "13800138000"],
        "require_citations": True,
        "absent_in_citations": ["alice@example.com", "13800138000"],
    },
    {
        "name": "secret_mask",
        "filename": "secret-note.md",
        "parser_backend": "basic",
        "chunk_strategy": "langchain_recursive",
        "content": (
            "# Secrets\n\n"
            "Bearer sk-1234567890abcdef1234567890abcdef should never be persisted in retrieval.\n\n"
            "The useful content is that the worker retry budget is eighty attempts.\n"
        ),
        "query": "What does the note say about the retry budget?",
        "pipeline": {
            "governance_secrets_redact": True,
            "governance_secrets_mode": "mask",
            "governance_secrets_mask": "[SECRET]",
        },
        "expected_status": "completed",
        "required_metadata_keys": ["governance_secrets_hits"],
        "present_in_parsed": ["[SECRET]", "eighty attempts"],
        "absent_in_parsed": ["sk-1234567890abcdef1234567890abcdef"],
        "present_in_chunks": ["[SECRET]"],
        "absent_in_chunks": ["sk-1234567890abcdef1234567890abcdef"],
        "require_citations": True,
        "absent_in_citations": ["sk-1234567890abcdef1234567890abcdef"],
        "present_in_citations": ["eighty attempts"],
    },
    {
        "name": "html_rule_packs",
        "filename": "web-governance.html",
        "parser_backend": "markitdown",
        "chunk_strategy": "langchain_recursive",
        "content": (
            "<html><body>"
            "<div>Cookie consent</div>"
            "<div>Accept cookies</div>"
            "<div>Home > Docs > Governance</div>"
            "<main>"
            "<h1>Governance Metrics</h1>"
            "<p>Useful paragraph about retrieval quality and evidence grounding.</p>"
            "<table>"
            "<tr><th>Metric</th><th>Value</th></tr>"
            "<tr><td>retrieval_mrr</td><td>0.74</td></tr>"
            "</table>"
            "</main>"
            "</body></html>"
        ),
        "query": "Which metric is listed in the governance table?",
        "pipeline": {
            "governance_rule_packs": ["web_navigation", "web_cookie_banners"],
            "governance_normalize_tables": True,
        },
        "expected_status": "completed",
        "required_metadata_keys": ["governance_tables_normalized"],
        "required_rule_packs": ["web_navigation", "web_cookie_banners"],
        "present_in_parsed": ["Governance Metrics", "retrieval_mrr", "0.74"],
        "absent_in_parsed": ["Cookie consent", "Accept cookies", "Home > Docs > Governance"],
        "present_in_chunks": ["retrieval_mrr"],
        "absent_in_chunks": ["Cookie consent", "Accept cookies", "Home > Docs > Governance"],
        "require_citations": True,
        "absent_in_citations": ["Cookie consent", "Accept cookies", "Home > Docs > Governance"],
    },
    {
        "name": "duplicate_drop",
        "filename": "duplicate-note.md",
        "parser_backend": "basic",
        "chunk_strategy": "langchain_recursive",
        "content": (
            "Footer repeated line\n\n"
            "Useful paragraph about graph recall improvements.\n\n"
            "Footer repeated line\n\n"
            "Footer repeated line\n"
        ),
        "query": "What useful paragraph remains after cleanup?",
        "pipeline": {
            "governance_drop_duplicate_paragraphs": True,
            "governance_drop_duplicate_paragraphs_min_occurrences": 3,
            "governance_drop_duplicate_paragraphs_min_chars": 10,
        },
        "expected_status": "completed",
        "present_in_parsed": ["graph recall improvements"],
        "absent_in_parsed": ["Footer repeated line"],
        "present_in_chunks": ["graph recall improvements"],
        "absent_in_chunks": ["Footer repeated line"],
        "require_citations": True,
        "present_in_citations": ["graph recall improvements"],
        "absent_in_citations": ["Footer repeated line"],
    },
    {
        "name": "quality_gate_quarantine",
        "filename": "outline-only.md",
        "parser_backend": "basic",
        "chunk_strategy": "langchain_recursive",
        "content": (
            "# Executive Summary\n\n"
            "## Agenda\n\n"
            "## Risks\n\n"
            "## Next Steps\n"
        ),
        "pipeline": {
            "chunk_vector_enabled": False,
            "bm25_index_enabled": False,
            "governance_drop_outline_only": True,
            "governance_drop_outline_min_content_chars": 50,
            "governance_drop_outline_max_heading_ratio": 0.8,
            "governance_drop_low_density": True,
            "governance_drop_low_density_threshold": 0.3,
            "governance_quarantine_on_drop": True,
        },
        "expected_status": "quarantined",
        "required_metadata_keys": ["governance_dropped_documents"],
        "allowed_drop_reasons": ["outline_only", "low_density", "empty_document"],
    },
]


def metadata_has_nonempty_value(metadata: dict[str, Any], key: str) -> bool:
    value = metadata.get(key)
    if value in (None, "", 0, False):
        return False
    if isinstance(value, (list, dict, set, tuple)):
        return len(value) > 0
    return True


def chunk_text_from_response(body: Any) -> str:
    if isinstance(body, list):
        items = body
    elif isinstance(body, dict):
        items = body.get("items")
        if not isinstance(items, list):
            items = body.get("chunks")
        if not isinstance(items, list):
            items = []
    else:
        items = []
    parts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = item.get("content")
        if isinstance(text, str) and text.strip():
            parts.append(text)
    return "\n".join(parts)


def citation_text_from_response(body: Any) -> str:
    citations = body.get("citations") if isinstance(body, dict) else None
    if not isinstance(citations, list):
        return ""
    parts: list[str] = []
    for item in citations:
        if not isinstance(item, dict):
            continue
        for key in ("chunk_content", "content", "text", "snippet"):
            text = item.get(key)
            if isinstance(text, str) and text.strip():
                parts.append(text)
                break
    return "\n".join(parts)


def normalize_search_text(text: str) -> str:
    return str(text or "").replace("\\_", "_")


def evaluate_case_expectations(
    case: dict[str, Any],
    *,
    document_status: str,
    metadata: dict[str, Any],
    parsed_text: str,
    chunk_text: str,
    citation_text: str,
    citation_count: int,
) -> list[str]:
    failures: list[str] = []

    expected_status = str(case.get("expected_status") or "").strip().lower()
    if expected_status and str(document_status or "").strip().lower() != expected_status:
        failures.append(f"status expected {expected_status} got {document_status}")

    if metadata.get("governance_enabled") is not True:
        failures.append("metadata missing governance_enabled=true")

    for key in case.get("required_metadata_keys") or []:
        if not metadata_has_nonempty_value(metadata, str(key)):
            failures.append(f"metadata missing non-empty {key}")

    required_rule_packs = [str(item).strip().lower() for item in (case.get("required_rule_packs") or []) if str(item).strip()]
    actual_rule_packs = {
        str(item).strip().lower()
        for item in (metadata.get("governance_rule_packs") or [])
        if str(item).strip()
    }
    for pack in required_rule_packs:
        if pack not in actual_rule_packs:
            failures.append(f"metadata missing rule_pack {pack}")

    allowed_drop_reasons = [str(item).strip() for item in (case.get("allowed_drop_reasons") or []) if str(item).strip()]
    if allowed_drop_reasons:
        actual_drop_reasons = metadata.get("governance_drop_reasons") if isinstance(metadata.get("governance_drop_reasons"), dict) else {}
        if not any(str(reason) in actual_drop_reasons for reason in allowed_drop_reasons):
            failures.append(f"drop_reasons missing one of {allowed_drop_reasons}")

    checks: list[tuple[str, str, list[str]]] = [
        ("parsed", normalize_search_text(parsed_text), [str(item) for item in (case.get("present_in_parsed") or [])]),
        ("chunks", normalize_search_text(chunk_text), [str(item) for item in (case.get("present_in_chunks") or [])]),
        ("citations", normalize_search_text(citation_text), [str(item) for item in (case.get("present_in_citations") or [])]),
    ]
    for label, haystack, needles in checks:
        for needle in needles:
            if needle and needle not in haystack:
                failures.append(f"{label} missing expected text: {needle}")

    anti_checks: list[tuple[str, str, list[str]]] = [
        ("parsed", normalize_search_text(parsed_text), [str(item) for item in (case.get("absent_in_parsed") or [])]),
        ("chunks", normalize_search_text(chunk_text), [str(item) for item in (case.get("absent_in_chunks") or [])]),
        ("citations", normalize_search_text(citation_text), [str(item) for item in (case.get("absent_in_citations") or [])]),
    ]
    for label, haystack, needles in anti_checks:
        for needle in needles:
            if needle and needle in haystack:
                failures.append(f"{label} still contains forbidden text: {needle}")

    if bool(case.get("require_citations")) and int(citation_count) <= 0:
        failures.append("retrieval returned no citations")

    return failures


def write_fixture(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def poll_document_until_terminal(
    api: LiveApi,
    *,
    document_id: str,
    steps: list[dict[str, Any]],
    poll_timeout: int,
    request_timeout: int,
) -> dict[str, Any]:
    deadline = time.time() + int(poll_timeout)
    last_body: dict[str, Any] = {}
    while time.time() < deadline:
        status, body, elapsed = api.json("GET", f"/api/v1/documents/{document_id}", timeout=request_timeout)
        doc_status = str((body or {}).get("status") or "")
        record_step(steps, "poll_document", status, body, elapsed, doc_status=doc_status)
        if not ok_status(status):
            raise RuntimeError(f"document poll failed: {snippet(body)}")
        last_body = body if isinstance(body, dict) else {}
        if doc_status.lower() in {"completed", "failed", "quarantined", "cancelled"}:
            return last_body
        time.sleep(2)
    raise RuntimeError(f"document did not reach a terminal state: {document_id}")


def retrieve_preview_with_retry(
    api: LiveApi,
    *,
    document_id: str,
    dataset_id: str,
    query: str,
    timeout: int,
    attempts: int = 3,
) -> tuple[int, Any, float]:
    last_status = 0
    last_body: Any = {}
    last_elapsed = 0.0
    for attempt in range(max(1, int(attempts))):
        status, body, elapsed = api.json(
            "POST",
            "/api/v1/rag/retrieve-preview",
            payload={
                "query": query,
                "dataset_id": dataset_id,
                "document_ids": [document_id],
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
            timeout=timeout,
        )
        last_status, last_body, last_elapsed = status, body, elapsed
        if ok_status(status) and list_count(body) > 0:
            return status, body, elapsed
        if attempt + 1 < attempts:
            time.sleep(2)
    return last_status, last_body, last_elapsed


def metadata_subset(metadata: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "governance_enabled",
        "governance_changed_documents",
        "governance_rules_applied",
        "governance_dropped_documents",
        "governance_drop_reasons",
        "governance_pii_hits",
        "governance_secrets_hits",
        "governance_paragraphs_dropped",
        "governance_tables_normalized",
        "governance_rule_packs",
        "governance_quality",
    )
    return {key: metadata.get(key) for key in keys if key in metadata}


def run_case(
    api: LiveApi,
    *,
    artifact_dir: Path,
    dataset_id: str,
    case: dict[str, Any],
    steps: list[dict[str, Any]],
    timeout: int,
    poll_timeout: int,
) -> dict[str, Any]:
    fixture_path = artifact_dir / "fixtures" / str(case["filename"])
    write_fixture(fixture_path, str(case["content"]))

    pipeline = dict(BASE_PIPELINE)
    pipeline.update(case.get("pipeline") or {})

    status, body, elapsed = api.multipart(
        "POST",
        "/api/v1/documents/upload",
        fields={
            "dataset_id": dataset_id,
            "parser_backend": str(case.get("parser_backend") or "basic"),
            "chunk_strategy": str(case.get("chunk_strategy") or "langchain_recursive"),
            "pipeline": json.dumps(pipeline, ensure_ascii=False),
        },
        file_path=fixture_path,
        timeout=timeout,
    )
    record_step(steps, f"{case['name']}:upload", status, body, elapsed)
    if not ok_status(status):
        raise RuntimeError(f"{case['name']} upload failed: {snippet(body)}")

    document_id = str((body or {}).get("id") or (body or {}).get("document_id") or "")
    if not document_id:
        raise RuntimeError(f"{case['name']} upload missing document_id: {snippet(body)}")

    final_doc = poll_document_until_terminal(
        api,
        document_id=document_id,
        steps=steps,
        poll_timeout=poll_timeout,
        request_timeout=timeout,
    )
    final_status = str(final_doc.get("status") or "").strip().lower()
    metadata = final_doc.get("metadata") if isinstance(final_doc.get("metadata"), dict) else {}

    parsed_text = ""
    chunk_text = ""
    citation_text = ""
    citation_count = 0
    parsed_available = False
    chunk_count = 0

    if final_status == "completed":
        status, body, elapsed = api.json(
            "GET",
            f"/api/v1/documents/{document_id}/parsed-content?max_chars=200000",
            timeout=timeout,
        )
        parsed_text = parsed_text_from_response(body)
        parsed_available = bool(isinstance(body, dict) and body.get("available"))
        record_step(
            steps,
            f"{case['name']}:parsed_content",
            status,
            body,
            elapsed,
            parsed_chars=len(parsed_text),
            available=parsed_available,
        )

        status, body, elapsed = api.json(
            "GET",
            f"/api/v1/documents/{document_id}/chunks?limit={DOCUMENT_CHUNK_LIST_LIMIT}",
            timeout=timeout,
        )
        chunk_count = list_count(body)
        chunk_text = chunk_text_from_response(body)
        record_step(steps, f"{case['name']}:chunks", status, body, elapsed, chunk_count=chunk_count)

        query = str(case.get("query") or "").strip()
        if query:
            status, body, elapsed = retrieve_preview_with_retry(
                api,
                document_id=document_id,
                dataset_id=dataset_id,
                query=query,
                timeout=min(int(timeout), 180),
            )
            citation_count = list_count(body)
            citation_text = citation_text_from_response(body)
            record_step(
                steps,
                f"{case['name']}:retrieve_preview",
                status,
                body,
                elapsed,
                citation_count=citation_count,
            )

    failures = evaluate_case_expectations(
        case,
        document_status=final_status,
        metadata=metadata,
        parsed_text=parsed_text,
        chunk_text=chunk_text,
        citation_text=citation_text,
        citation_count=citation_count,
    )

    return {
        "name": case["name"],
        "document_id": document_id,
        "status": final_status,
        "ok": len(failures) == 0,
        "failures": failures,
        "parsed_available": parsed_available,
        "parsed_chars": len(parsed_text),
        "chunk_count": int(chunk_count),
        "citation_count": int(citation_count),
        "metadata": metadata_subset(metadata),
        "parsed_preview": parsed_text[:500],
        "citation_preview": citation_text[:500],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a remote governance ingest matrix on a live MimirQ API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default="demo")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--poll-timeout", type=int, default=1800)
    parser.add_argument("--cleanup-mode", default="purge_dataset")
    parser.add_argument("--delete-dataset-after", action="store_true")
    args = parser.parse_args()

    run_id = time.strftime("%Y%m%d-%H%M%S")
    artifact_dir = Path(args.artifact_dir or f"artifacts/governance-ingest-matrix/{run_id}").resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    api = LiveApi(args.base_url, args.tenant_id, args.account_id, args.user_id, args.timeout)
    steps: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "ok": False,
        "artifact_dir": str(artifact_dir),
        "base_url": args.base_url,
        "cases": [],
    }

    dataset_id = ""
    last_document_id = ""
    try:
        status, body, elapsed = api.json(
            "POST",
            "/api/v1/datasets/",
            payload={
                "name": f"Governance Ingest Matrix {run_id}",
                "description": "Live governance ingest verification dataset",
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
            raise RuntimeError(f"create_dataset response missing id: {snippet(body)}")
        summary["dataset_id"] = dataset_id

        case_rows: list[dict[str, Any]] = []
        for case in CASES:
            row = run_case(
                api,
                artifact_dir=artifact_dir,
                dataset_id=dataset_id,
                case=case,
                steps=steps,
                timeout=int(args.timeout),
                poll_timeout=int(args.poll_timeout),
            )
            last_document_id = str(row.get("document_id") or last_document_id)
            case_rows.append(row)
        summary["cases"] = case_rows

        cleanup_summary = perform_cleanup(
            api=api,
            steps=steps,
            dataset_id=dataset_id,
            document_id=last_document_id or "00000000-0000-0000-0000-000000000000",
            cleanup_mode=str(args.cleanup_mode or "purge_dataset"),
            delete_dataset_after=bool(args.delete_dataset_after),
            timeout=int(args.timeout),
        )
        summary["cleanup"] = cleanup_summary
        summary["ok"] = all(bool(item.get("ok")) for item in case_rows)
    except Exception as exc:  # noqa: BLE001
        summary["ok"] = False
        summary["error"] = str(exc)
    finally:
        summary["steps"] = steps
        report_path = artifact_dir / "report.json"
        report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        lines = [
            "# Remote Governance Ingest Matrix",
            "",
            f"- ok: `{summary.get('ok')}`",
            f"- dataset_id: `{summary.get('dataset_id')}`",
            "",
            "## Cases",
        ]
        for item in summary.get("cases") or []:
            lines.append(
                f"- {item.get('name')}: ok={item.get('ok')} status={item.get('status')} "
                f"chunks={item.get('chunk_count')} citations={item.get('citation_count')}"
            )
            failures = item.get("failures") or []
            if failures:
                lines.append(f"  failures: {', '.join(str(entry) for entry in failures)}")
        (artifact_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

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
