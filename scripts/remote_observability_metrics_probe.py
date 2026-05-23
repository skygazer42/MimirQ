from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:8000/api/v1"
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"
DEFAULT_USER_ID = "demo"


def now_ms() -> int:
    return int(time.time() * 1000)


def live_headers(*, tenant_id: str, user_id: str) -> dict[str, str]:
    return {
        "X-Tenant-ID": str(tenant_id),
        "X-Account-ID": str(user_id),
        "X-User-ID": str(user_id),
    }


def build_chat_payload(
    *,
    dataset_id: str,
    message: str,
    retrieval_mode: str = "hybrid",
    score_threshold: float = 0.0,
) -> dict[str, Any]:
    return {
        "message": str(message),
        "dataset_id": str(dataset_id),
        "stream": False,
        "rag_config": {
            "top_k": 4,
            "score_threshold": float(score_threshold),
            "retrieval_mode": str(retrieval_mode),
            "enable_reranker": False,
            "enable_multi_query": False,
            "enable_hyde": False,
            "enable_query_decomposition": False,
            "use_graph": False,
            "answer_mode": "extractive",
        },
    }


def metrics_progress_satisfied(
    *,
    before_summary: dict[str, Any],
    before_query_analytics: dict[str, Any],
    summary_after: dict[str, Any],
    query_analytics_after: dict[str, Any],
    min_trace_delta: int,
    min_zero_hit_delta: int,
) -> bool:
    summary_before_count = int(before_summary.get("rag_trace_count") or 0)
    analytics_before_count = int(before_query_analytics.get("rag_trace_count") or 0)
    zero_before_count = int(before_query_analytics.get("zero_hit_count") or 0)

    summary_after_count = int(summary_after.get("rag_trace_count") or 0)
    analytics_after_count = int(query_analytics_after.get("rag_trace_count") or 0)
    zero_after_count = int(query_analytics_after.get("zero_hit_count") or 0)

    if not bool(summary_after.get("enabled")):
        return False
    if not bool(query_analytics_after.get("enabled")):
        return False
    if summary_after_count < summary_before_count + int(min_trace_delta):
        return False
    if analytics_after_count < analytics_before_count + int(min_trace_delta):
        return False
    if zero_after_count < zero_before_count + int(min_zero_hit_delta):
        return False
    return True


class ApiClient:
    def __init__(self, *, base_url: str, tenant_id: str, user_id: str, timeout_sec: float) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.headers = live_headers(tenant_id=tenant_id, user_id=user_id)
        self.timeout = float(timeout_sec)
        self.session = requests.Session()

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def get_json(self, path: str) -> dict[str, Any]:
        response = self.session.get(self._url(path), headers=self.headers, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def put_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.session.put(
            self._url(path),
            headers={**self.headers, "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            self._url(path),
            headers={**self.headers, "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def post_multipart(
        self,
        path: str,
        *,
        files: dict[str, Any],
        data: dict[str, Any],
    ) -> dict[str, Any]:
        response = self.session.post(
            self._url(path),
            headers=self.headers,
            files=files,
            data=data,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def delete(self, path: str) -> int:
        response = self.session.delete(self._url(path), headers=self.headers, timeout=self.timeout)
        response.raise_for_status()
        return int(response.status_code)


def write_report(report: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe observability metrics on the current remote API.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--timeout-sec", type=float, default=60.0)
    parser.add_argument(
        "--output-dir",
        default="artifacts/observability-metrics/remote-20260524",
    )
    args = parser.parse_args(argv)

    api = ApiClient(
        base_url=args.base_url,
        tenant_id=args.tenant_id,
        user_id=args.user_id,
        timeout_sec=args.timeout_sec,
    )

    started_at = now_ms()
    dataset_id = ""
    conversation_ids: list[str] = []
    original_obs: dict[str, Any] = {}
    failures: list[str] = []

    try:
        original_obs = api.get_json("/settings").get("observability") or {}
        original_metrics_enabled = bool(original_obs.get("metrics_log_enabled"))
        original_metrics_include_text = bool(original_obs.get("metrics_log_include_text"))

        if not original_metrics_enabled:
            api.put_json(
                "/settings",
                {
                    "observability": {
                        "metrics_log_enabled": True,
                        "metrics_log_include_text": original_metrics_include_text,
                    }
                },
            )

        before_summary = api.get_json("/observability/rag-metrics/summary?window_minutes=60")
        before_qa = api.get_json("/observability/rag-metrics/query-analytics?window_minutes=60&slow_threshold_sec=2")

        dataset_name = f"observability-metrics-{started_at}"
        dataset_body = api.post_json(
            "/datasets/",
            {
                "name": dataset_name,
                "description": "Disposable dataset for observability metrics probe.",
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
                    "kg_enabled": False,
                    "event_vector_enabled": False,
                    "entity_vector_enabled": False,
                },
            },
        )
        dataset_id = str(dataset_body.get("id") or dataset_body.get("dataset_id") or "")

        document_body = api.post_multipart(
            "/documents/upload",
            files={
                "file": (
                    f"observability-{started_at}.md",
                    (
                        "# Observability Metrics\n\n"
                        "Token OBS belongs only here.\n\n"
                        "This document exists only to exercise extractive metrics logging."
                    ).encode("utf-8"),
                    "text/markdown",
                )
            },
            data={
                "dataset_id": dataset_id,
                "parser_backend": "basic",
                "chunk_strategy": "langchain_recursive",
            },
        )
        document_id = str(document_body.get("id") or document_body.get("document_id") or "")

        document_status = ""
        for _ in range(30):
            document_status = str(api.get_json(f"/documents/{document_id}").get("status") or "")
            if document_status == "completed":
                break
            time.sleep(1)
        if document_status != "completed":
            failures.append(f"document_not_completed:{document_status}")

        grounded = api.post_json(
            "/chat",
            build_chat_payload(
                dataset_id=dataset_id,
                message="What token belongs only to OBS?",
            ),
        )
        grounded_conversation_id = str(grounded.get("conversation_id") or "")
        if grounded_conversation_id:
            conversation_ids.append(grounded_conversation_id)

        zero_hit = api.post_json(
            "/chat",
            build_chat_payload(
                dataset_id=dataset_id,
                message="qwertyuiop asdfghjkl zxcvbnm",
                retrieval_mode="keyword",
                score_threshold=1.0,
            ),
        )
        zero_hit_conversation_id = str(zero_hit.get("conversation_id") or "")
        if zero_hit_conversation_id:
            conversation_ids.append(zero_hit_conversation_id)

        summary_after: dict[str, Any] = {}
        qa_after: dict[str, Any] = {}
        for _ in range(15):
            summary_after = api.get_json("/observability/rag-metrics/summary?window_minutes=60")
            qa_after = api.get_json("/observability/rag-metrics/query-analytics?window_minutes=60&slow_threshold_sec=2")
            if metrics_progress_satisfied(
                before_summary=before_summary,
                before_query_analytics=before_qa,
                summary_after=summary_after,
                query_analytics_after=qa_after,
                min_trace_delta=1,
                min_zero_hit_delta=1,
            ):
                break
            time.sleep(2)
        else:
            failures.append("metrics_progress_not_observed")

        report = {
            "schema": "mimirq.observability_metrics_probe.v1",
            "started_at_ms": started_at,
            "base_url": args.base_url,
            "dataset_id": dataset_id or None,
            "conversation_ids": conversation_ids,
            "before_summary": {
                "enabled": before_summary.get("enabled"),
                "rag_trace_count": before_summary.get("rag_trace_count"),
            },
            "before_query_analytics": {
                "enabled": before_qa.get("enabled"),
                "rag_trace_count": before_qa.get("rag_trace_count"),
                "zero_hit_count": before_qa.get("zero_hit_count"),
            },
            "after_summary": {
                "enabled": summary_after.get("enabled"),
                "rag_trace_count": summary_after.get("rag_trace_count"),
            },
            "after_query_analytics": {
                "enabled": qa_after.get("enabled"),
                "rag_trace_count": qa_after.get("rag_trace_count"),
                "unique_query_hashes": qa_after.get("unique_query_hashes"),
                "zero_hit_count": qa_after.get("zero_hit_count"),
                "top_zero_hit_queries": qa_after.get("top_zero_hit_queries"),
            },
            "failures": failures,
        }
        output_path = write_report(report, Path(args.output_dir))
        print(output_path)
        return 0 if not failures else 1
    finally:
        for conversation_id in conversation_ids:
            try:
                api.delete(f"/chat/conversations/{conversation_id}")
            except Exception:
                pass
        if dataset_id:
            try:
                api.post_json(
                    f"/datasets/{dataset_id}/purge?dry_run=false&max_delete=1000",
                    {},
                )
            except Exception:
                pass
            try:
                api.delete(f"/datasets/{dataset_id}")
            except Exception:
                pass
        if original_obs:
            try:
                api.put_json(
                    "/settings",
                    {
                        "observability": {
                            "metrics_log_enabled": bool(original_obs.get("metrics_log_enabled")),
                            "metrics_log_include_text": bool(original_obs.get("metrics_log_include_text")),
                        }
                    },
                )
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
