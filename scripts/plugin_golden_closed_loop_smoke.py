#!/usr/bin/env python3
"""Live API smoke for plugin Golden import plus retrieval-only regression.

This script intentionally uses only the Python standard library so it can run on
remote hosts and inside minimal containers without installing test-only
dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"
REGISTERED_CHUNK_PLUGIN_REF_RE = re.compile(
    r"^plugin:[a-z0-9][a-z0-9_.-]{0,63}@[A-Za-z0-9][A-Za-z0-9_.+-]{0,31}:chunk$"
)


@dataclass(frozen=True)
class ClosedLoopResult:
    dataset_id: str
    plugin_ref: str
    run_id: str
    case_ids: list[str]
    summary: dict[str, Any]
    import_result: dict[str, Any]
    plugin_source: dict[str, Any]


class LiveApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        tenant_id: str = DEFAULT_TENANT_ID,
        account_id: str = "demo",
        user_id: str = "demo",
        bearer: str = "",
        timeout_sec: float = 60.0,
    ) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.timeout_sec = float(timeout_sec)
        self.headers = {
            "Accept": "application/json",
            "X-Tenant-ID": str(tenant_id),
            "X-Account-ID": str(account_id),
            "X-User-ID": str(user_id),
        }
        if bearer:
            self.headers["Authorization"] = f"Bearer {bearer}"

    def json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = _join_url(self.base_url, path, query=query)
        headers = dict(self.headers)
        data: bytes | None = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=self.timeout_sec) as resp:
                raw = resp.read()
                status = int(resp.status)
        except HTTPError as exc:
            raw = exc.read()
            status = int(exc.code)
            body = _decode_body(raw)
            raise RuntimeError(f"{method} {url} failed: HTTP {status}: {_snippet(body)}") from exc
        except URLError as exc:
            raise RuntimeError(f"{method} {url} failed: {exc}") from exc

        body = _decode_body(raw)
        if not 200 <= status < 300:
            raise RuntimeError(f"{method} {url} failed: HTTP {status}: {_snippet(body)}")
        if isinstance(body, dict):
            return body
        raise RuntimeError(f"{method} {url} returned non-object JSON: {_snippet(body)}")


def _decode_body(raw: bytes) -> Any:
    if not raw:
        return {}
    text = raw.decode("utf-8", errors="replace")
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _snippet(value: Any, *, limit: int = 800) -> str:
    if isinstance(value, str):
        return value[:limit]
    return json.dumps(value, ensure_ascii=False, default=str)[:limit]


def _join_url(base_url: str, path: str, *, query: dict[str, Any] | None = None) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("base_url is required")
    p = str(path or "").strip()
    if not p.startswith("/"):
        p = f"/{p}"
    if base.endswith("/api/v1") and p.startswith("/api/v1/"):
        p = p[len("/api/v1") :]
    url = f"{base}{p}"
    clean_query = {k: v for k, v in (query or {}).items() if v is not None}
    if clean_query:
        url = f"{url}?{urlencode(clean_query, doseq=True)}"
    return url


def _is_golden_enabled(plugin: dict[str, Any]) -> bool:
    contract = plugin.get("contract")
    if not isinstance(contract, dict):
        return False
    golden = contract.get("golden")
    return isinstance(golden, dict) and golden.get("enabled") is True


def select_plugin_ref(plugin_list: dict[str, Any]) -> str:
    items = plugin_list.get("items") if isinstance(plugin_list, dict) else []
    if not isinstance(items, list):
        raise RuntimeError("plugin list response must contain items[]")

    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        refs = item.get("refs")
        if not isinstance(refs, dict):
            continue
        chunk_ref = str(refs.get("chunk") or "").strip()
        if not chunk_ref:
            continue
        if item.get("executable") is not True:
            continue
        if not _is_golden_enabled(item):
            continue
        score = 0
        if item.get("test_status") == "passed":
            score += 4
        if item.get("published") is True:
            score += 2
        if str(item.get("package_hash") or "").strip():
            score += 1
        candidates.append((score, chunk_ref, item))

    if not candidates:
        errors = plugin_list.get("errors") if isinstance(plugin_list, dict) else None
        error_hint = f"; registry errors={_snippet(errors)}" if errors else ""
        raise RuntimeError(f"no executable pipeline plugin with enabled Golden contract and chunk ref found{error_hint}")

    candidates.sort(key=lambda entry: entry[0], reverse=True)
    return candidates[0][1]


def require_registered_chunk_plugin_ref(plugin_ref: str) -> str:
    ref = str(plugin_ref or "").strip()
    if not REGISTERED_CHUNK_PLUGIN_REF_RE.fullmatch(ref):
        raise RuntimeError("plugin_ref must be a registered chunk plugin ref")
    return ref


def _extract_case_ids(import_response: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    import_result = import_response.get("import_result")
    if not isinstance(import_result, dict):
        raise RuntimeError("golden-draft/import response missing import_result")
    if import_result.get("errors"):
        raise RuntimeError(f"golden-draft/import returned errors: {_snippet(import_result.get('errors'))}")

    raw_ids = import_result.get("case_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        raw_ids = [
            *(import_result.get("created_case_ids") or []),
            *(import_result.get("updated_case_ids") or []),
            *(import_result.get("skipped_case_ids") or []),
        ]
    case_ids = [str(item).strip() for item in raw_ids if str(item or "").strip()]
    if not case_ids:
        draft = import_response.get("draft") if isinstance(import_response.get("draft"), dict) else {}
        raise RuntimeError(f"golden-draft/import created no case ids; draft items={draft.get('items_total')}")
    return import_result, case_ids


def _draft_has_expected_metadata(import_response: dict[str, Any]) -> bool:
    draft = import_response.get("draft")
    if not isinstance(draft, dict):
        return False
    bundle = draft.get("bundle")
    if not isinstance(bundle, dict):
        return False
    items = bundle.get("items")
    if not isinstance(items, list):
        return False
    for item in items:
        extra = item.get("extra") if isinstance(item, dict) else None
        expected = extra.get("expected_metadata") if isinstance(extra, dict) else None
        if isinstance(expected, dict) and expected:
            return True
    return False


def _plugin_source_from_import_response(import_response: dict[str, Any]) -> dict[str, Any]:
    draft = import_response.get("draft") if isinstance(import_response.get("draft"), dict) else {}
    out: dict[str, Any] = {}
    for key in ("plugin_id", "plugin_version", "plugin_ref"):
        value = str(draft.get(key) or "").strip()
        if value:
            out[key] = value
    try:
        out["draft_items_total"] = int(draft.get("items_total") or 0)
    except Exception:
        out["draft_items_total"] = 0

    bundle = draft.get("bundle") if isinstance(draft.get("bundle"), dict) else {}
    items = bundle.get("items") if isinstance(bundle, dict) else []
    if isinstance(items, list):
        for item in items:
            extra = item.get("extra") if isinstance(item, dict) else None
            package_hash = str((extra or {}).get("plugin_package_hash") or "").strip() if isinstance(extra, dict) else ""
            if package_hash:
                out["plugin_package_hash"] = package_hash
                break
    return out


def _extract_run_id(run_response: dict[str, Any]) -> str:
    run_id = str(run_response.get("id") or "").strip()
    if not run_id and isinstance(run_response.get("run"), dict):
        run_id = str(run_response["run"].get("id") or "").strip()
    if not run_id:
        raise RuntimeError(f"regression run create response missing id: {_snippet(run_response)}")
    return run_id


def _extract_run(detail_response: dict[str, Any]) -> dict[str, Any]:
    run = detail_response.get("run")
    if isinstance(run, dict):
        return run
    if "status" in detail_response:
        return detail_response
    raise RuntimeError(f"regression run detail response missing run: {_snippet(detail_response)}")


def _validate_expected_metadata_summary(
    summary: dict[str, Any],
    *,
    min_hit_rate: float,
    min_recall: float,
) -> None:
    required = (
        "expected_metadata_cases_total",
        "expected_metadata_hit_rate",
        "expected_metadata_recall",
        "expected_metadata_fields_total",
        "expected_metadata_fields_matched",
    )
    missing = [key for key in required if key not in summary]
    if missing:
        raise RuntimeError(f"regression summary missing expected_metadata metrics: {', '.join(missing)}")

    cases_total = float(summary.get("expected_metadata_cases_total") or 0)
    fields_total = float(summary.get("expected_metadata_fields_total") or 0)
    hit_rate = float(summary.get("expected_metadata_hit_rate") or 0)
    recall = float(summary.get("expected_metadata_recall") or 0)
    if cases_total <= 0 or fields_total <= 0:
        raise RuntimeError(f"expected_metadata summary has no evaluated cases/fields: {_snippet(summary)}")
    if hit_rate < min_hit_rate:
        raise RuntimeError(f"expected_metadata_hit_rate {hit_rate:.4f} is below threshold {min_hit_rate:.4f}")
    if recall < min_recall:
        raise RuntimeError(f"expected_metadata_recall {recall:.4f} is below threshold {min_recall:.4f}")


def _poll_regression_run(
    *,
    client: Any,
    run_id: str,
    poll_timeout_sec: float,
    poll_interval_sec: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + float(poll_timeout_sec)
    last_detail: dict[str, Any] | None = None
    while True:
        detail = client.json(
            "GET",
            f"/api/v1/evaluations/ragas/regression/runs/{run_id}",
            query={"include_items": "false", "include_contexts": "false"},
        )
        last_detail = detail
        run = _extract_run(detail)
        status = str(run.get("status") or "").strip().lower()
        if status == "completed":
            return client.json(
                "GET",
                f"/api/v1/evaluations/ragas/regression/runs/{run_id}",
                query={"include_items": "true", "include_contexts": "false"},
            )
        if status in {"failed", "error", "cancelled", "canceled"}:
            raise RuntimeError(f"regression run {run_id} ended with status={status}: {_snippet(run)}")
        if time.monotonic() >= deadline:
            raise RuntimeError(f"timed out waiting for regression run {run_id}; last detail={_snippet(last_detail)}")
        if poll_interval_sec > 0:
            time.sleep(float(poll_interval_sec))


def run_closed_loop_smoke(
    *,
    client: Any,
    dataset_id: str,
    plugin_ref: str | None,
    max_items: int,
    max_chunks: int,
    include_unmarked_chunks: bool,
    overwrite: bool,
    poll_timeout_sec: float,
    poll_interval_sec: float,
    min_expected_metadata_hit_rate: float = 1.0,
    min_expected_metadata_recall: float = 1.0,
    enable_hierarchy_recall: bool = True,
    hierarchy_sibling_window: int = 2,
    hierarchy_overfetch_factor: int = 4,
    regression_top_k: int = 20,
) -> ClosedLoopResult:
    selected_ref = str(plugin_ref or "").strip()
    if not selected_ref:
        selected_ref = select_plugin_ref(client.json("GET", "/api/v1/pipeline/plugins"))
    selected_ref = require_registered_chunk_plugin_ref(selected_ref)

    import_payload = {
        "dataset_id": dataset_id,
        "plugin_ref": selected_ref,
        "max_items": int(max_items),
        "max_chunks": int(max_chunks),
        "include_unmarked_chunks": bool(include_unmarked_chunks),
        "overwrite": bool(overwrite),
    }
    import_response = client.json(
        "POST",
        "/api/v1/pipeline/plugins/golden-draft/import",
        payload=import_payload,
    )
    import_result, case_ids = _extract_case_ids(import_response)
    if not _draft_has_expected_metadata(import_response):
        raise RuntimeError("plugin Golden draft did not produce any extra.expected_metadata fields")
    plugin_source = _plugin_source_from_import_response(import_response)
    plugin_source["plugin_ref"] = str(plugin_source.get("plugin_ref") or selected_ref)

    run_payload = {
        "dataset_id": dataset_id,
        "case_ids": case_ids,
        "metrics": [],
        "use_llm_judge": False,
        "skip_empty_contexts": True,
        "max_cases": max(1, min(500, len(case_ids), int(max_items))),
        "top_k": max(1, min(50, int(regression_top_k or 20))),
    }
    if enable_hierarchy_recall:
        run_payload.update(
            {
                "enable_hierarchy_recall": True,
                "hierarchy_sibling_window": max(0, int(hierarchy_sibling_window or 0)),
                "hierarchy_overfetch_factor": max(1, int(hierarchy_overfetch_factor or 1)),
            }
        )
    run_response = client.json("POST", "/api/v1/evaluations/ragas/regression/runs", payload=run_payload)
    run_id = _extract_run_id(run_response)
    detail = _poll_regression_run(
        client=client,
        run_id=run_id,
        poll_timeout_sec=poll_timeout_sec,
        poll_interval_sec=poll_interval_sec,
    )
    run = _extract_run(detail)
    summary = run.get("summary")
    if not isinstance(summary, dict):
        raise RuntimeError(f"completed regression run {run_id} missing summary: {_snippet(run)}")
    _validate_expected_metadata_summary(
        summary,
        min_hit_rate=float(min_expected_metadata_hit_rate),
        min_recall=float(min_expected_metadata_recall),
    )

    return ClosedLoopResult(
        dataset_id=dataset_id,
        plugin_ref=selected_ref,
        run_id=run_id,
        case_ids=case_ids,
        summary=summary,
        import_result=import_result,
        plugin_source=plugin_source,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a live plugin Golden import + retrieval-only regression smoke test."
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("MIMIRQ_API_BASE_URL") or os.getenv("BACKEND_BASE_URL") or "http://127.0.0.1:8000",
        help="Backend base URL; may be root or /api/v1 (default: env MIMIRQ_API_BASE_URL/BACKEND_BASE_URL or http://127.0.0.1:8000)",
    )
    parser.add_argument("--dataset-id", required=True, help="Dataset UUID to import plugin Golden cases into.")
    parser.add_argument("--plugin-ref", default="", help="Optional plugin ref. If omitted, auto-select an executable Golden chunk plugin.")
    parser.add_argument("--tenant-id", default=os.getenv("MIMIRQ_TENANT_ID") or DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default=os.getenv("MIMIRQ_ACCOUNT_ID") or "demo")
    parser.add_argument("--user-id", default=os.getenv("MIMIRQ_USER_ID") or "demo")
    parser.add_argument("--bearer", default=os.getenv("MIMIRQ_API_TOKEN") or os.getenv("AUTH_TOKEN") or "")
    parser.add_argument("--timeout", type=float, default=float(os.getenv("MIMIRQ_API_TIMEOUT_SEC") or "60"))
    parser.add_argument("--poll-timeout", type=float, default=float(os.getenv("MIMIRQ_POLL_TIMEOUT_SEC") or "600"))
    parser.add_argument("--poll-interval", type=float, default=float(os.getenv("MIMIRQ_POLL_INTERVAL_SEC") or "2"))
    parser.add_argument("--max-items", type=int, default=200)
    parser.add_argument("--max-chunks", type=int, default=5000)
    parser.add_argument(
        "--include-unmarked-chunks",
        action="store_true",
        help=(
            "Debug only: request Golden import from chunks not marked by the plugin. "
            "The API rejects this unless PYTHON_PIPELINE_PLUGIN_ALLOW_UNMARKED_GOLDEN_CHUNKS=true."
        ),
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--min-expected-metadata-hit-rate", type=float, default=1.0)
    parser.add_argument("--min-expected-metadata-recall", type=float, default=1.0)
    parser.add_argument(
        "--disable-hierarchy-recall",
        action="store_true",
        help="Disable hierarchy/sibling recall for the retrieval-only regression run.",
    )
    parser.add_argument("--hierarchy-sibling-window", type=int, default=2)
    parser.add_argument("--hierarchy-overfetch-factor", type=int, default=4)
    parser.add_argument(
        "--regression-top-k",
        type=int,
        default=20,
        help="Retrieval-only regression top_k/citation evaluation window. Default keeps recall-friendly backend behavior.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    client = LiveApiClient(
        base_url=str(args.base_url),
        tenant_id=str(args.tenant_id),
        account_id=str(args.account_id),
        user_id=str(args.user_id),
        bearer=str(args.bearer or ""),
        timeout_sec=float(args.timeout),
    )
    try:
        result = run_closed_loop_smoke(
            client=client,
            dataset_id=str(args.dataset_id),
            plugin_ref=str(args.plugin_ref or ""),
            max_items=int(args.max_items),
            max_chunks=int(args.max_chunks),
            include_unmarked_chunks=bool(args.include_unmarked_chunks),
            overwrite=bool(args.overwrite),
            poll_timeout_sec=float(args.poll_timeout),
            poll_interval_sec=float(args.poll_interval),
            min_expected_metadata_hit_rate=float(args.min_expected_metadata_hit_rate),
            min_expected_metadata_recall=float(args.min_expected_metadata_recall),
            enable_hierarchy_recall=not bool(args.disable_hierarchy_recall),
            hierarchy_sibling_window=int(args.hierarchy_sibling_window),
            hierarchy_overfetch_factor=int(args.hierarchy_overfetch_factor),
            regression_top_k=int(args.regression_top_k),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[plugin-golden-smoke] ERR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
