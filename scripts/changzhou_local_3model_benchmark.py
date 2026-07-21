#!/usr/bin/env python3
"""Benchmark a locally configured MimirQ retriever and LLM on the fixed 800-case pack.

The target MimirQ instance must already be configured with the embedding and reranker
services named in the run metadata.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import dify_3way_benchmark as bench  # noqa: E402
from scripts.evaluate_mixed_rag_quality import (  # noqa: E402
    build_markdown_report,
    evaluate_mixed_rag_quality,
)

DEFAULT_CASES = "artifacts/dify_3way_benchmark_post_scope_fix_http_800_20260713/cases_800.json"
DEFAULT_OUT_DIR = "artifacts/changzhou_local_3model_800"
DEFAULT_MIMIRQ_BASE_URL = "http://127.0.0.1:8001"
DEFAULT_LLM_BASE_URL = "http://127.0.0.1:8000/v1"
DEFAULT_LLM_MODEL = "Qwen3-30B-A3B-Instruct-2507-FP16"
SYSTEM_NAME = "mimirq_local_3model"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_generation_messages(query: str, records: list[dict[str, Any]]) -> list[dict[str, str]]:
    evidence: list[str] = []
    for index, record in enumerate(records[:5], 1):
        title = _text(record.get("title")) or f"证据 {index}"
        content = _text(record.get("content") or record.get("text"))
        if content:
            evidence.append(f"[证据 {index}] {title}\n{content}")

    context = "\n\n".join(evidence) or "（未检索到证据）"
    return [
        {
            "role": "system",
            "content": (
                "你是常州政务服务问答助手。只能依据提供的证据回答，不得编造。"
                "直接回答用户问题。若证据含事项名称，首行必须原样输出“事项名称：值”；"
                "其余答案按问题要求逐项输出“字段名：值”，保留证据中的完整字段标签、枚举项和原文措辞。"
                "问题中的年份、入口名称和补贴类型等关键短语也要原样保留；"
                "证据不足时明确说明缺少哪部分信息。不要复述本指令。"
            ),
        },
        {
            "role": "user",
            "content": f"用户问题：{_text(query)}\n\n可用证据：\n{context}",
        },
    ]


def _llm_url(base_url: str) -> str:
    base = _text(base_url).rstrip("/")
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


def _call_llm(
    *,
    base_url: str,
    api_key: str,
    model: str,
    query: str,
    records: list[dict[str, Any]],
    timeout: float,
    max_tokens: int,
) -> tuple[str, dict[str, Any]]:
    payload = {
        "model": model,
        "messages": build_generation_messages(query, records),
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }
    response = bench._post_json_no_proxy(  # noqa: SLF001
        _llm_url(base_url),
        api_key,
        payload,
        timeout=timeout,
    )
    choices = response.get("choices") if isinstance(response, dict) else None
    first = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = _text(message.get("content"))
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    return content, {
        "finish_reason": _text(first.get("finish_reason")),
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }


def _call_case(
    *,
    case: dict[str, Any],
    mimirq_base_url: str,
    mimirq_token: str,
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    timeout: float,
    max_tokens: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    retrieval = bench._call_mimirq_case(  # noqa: SLF001
        case=case,
        base_url=mimirq_base_url,
        token=mimirq_token,
        timeout=timeout,
    )
    item = dict(retrieval)
    item["system"] = SYSTEM_NAME
    item["retrieval_latency_ms"] = retrieval.get("latency_ms")
    item["answer"] = ""

    if retrieval.get("ok") is not True:
        item["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return item

    generation_started = time.perf_counter()
    try:
        answer, usage = _call_llm(
            base_url=llm_base_url,
            api_key=llm_api_key,
            model=llm_model,
            query=bench._case_question(case),  # noqa: SLF001
            records=item.get("records") or [],
            timeout=timeout,
            max_tokens=max_tokens,
        )
        item["answer"] = answer
        item["llm"] = usage
        item["ok"] = bool(answer)
        if not answer:
            item["error"] = "empty LLM answer"
    except Exception as exc:  # noqa: BLE001
        item["ok"] = False
        item["error"] = bench._safe_error(exc, secrets=[llm_api_key, mimirq_token])  # noqa: SLF001
    item["generation_latency_ms"] = round((time.perf_counter() - generation_started) * 1000, 2)
    item["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return item


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_existing_items(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = payload.get("items") if isinstance(payload, dict) else []
    return [dict(item) for item in items if isinstance(item, dict)]


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 2)


def _run_summary(items: list[dict[str, Any]], *, cases: int, resumed: int) -> dict[str, Any]:
    succeeded = sum(1 for item in items if item.get("ok") is True)
    latencies = [float(item["latency_ms"]) for item in items if isinstance(item.get("latency_ms"), int | float)]
    retrieval_latencies = [
        float(item["retrieval_latency_ms"])
        for item in items
        if isinstance(item.get("retrieval_latency_ms"), int | float)
    ]
    generation_latencies = [
        float(item["generation_latency_ms"])
        for item in items
        if isinstance(item.get("generation_latency_ms"), int | float)
    ]
    return {
        "cases": cases,
        "completed": len(items),
        "succeeded": succeeded,
        "failed": len(items) - succeeded,
        "pending": max(0, cases - len(items)),
        "resumed": resumed,
        "complete": len(items) == cases and succeeded == cases,
        "latency_ms": {
            "mean": round(sum(latencies) / len(latencies), 2) if latencies else None,
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "retrieval_mean": round(sum(retrieval_latencies) / len(retrieval_latencies), 2)
            if retrieval_latencies
            else None,
            "generation_mean": round(sum(generation_latencies) / len(generation_latencies), 2)
            if generation_latencies
            else None,
        },
    }


def _run_payload(
    *,
    items: list[dict[str, Any]],
    cases: int,
    resumed: int,
    source: dict[str, Any],
) -> dict[str, Any]:
    ordered = sorted(items, key=lambda item: _text(item.get("case_id") or item.get("id")))
    return {
        "schema": "mimirq.local_3model_benchmark.run.v1",
        "generated_at": _utc_now_text(),
        "system": SYSTEM_NAME,
        "source": source,
        "summary": _run_summary(ordered, cases=cases, resumed=resumed),
        "items": ordered,
    }


def run_benchmark(
    *,
    cases: list[dict[str, Any]],
    run_path: Path,
    mimirq_base_url: str,
    mimirq_token: str,
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    embedding_model: str,
    embedding_base_url: str,
    reranker_model: str,
    reranker_base_url: str,
    timeout: float,
    max_tokens: int,
    concurrency: int,
    resume: bool,
    retry_failures: bool,
    flush_every: int,
) -> dict[str, Any]:
    existing = _load_existing_items(run_path) if resume else []
    existing_by_id = {
        _text(item.get("case_id") or item.get("id")): item
        for item in existing
        if _text(item.get("case_id") or item.get("id"))
    }
    reusable: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for case in cases:
        case_id = bench._case_id(case)  # noqa: SLF001
        item = existing_by_id.get(case_id)
        if item is None or (retry_failures and item.get("ok") is not True):
            pending.append(case)
        else:
            reusable.append(item)

    items = list(reusable)
    source = {
        "pipeline": "MimirQ External Knowledge retrieval -> local OpenAI-compatible LLM",
        "mimirq_base_url": mimirq_base_url.rstrip("/"),
        "embedding_model": embedding_model,
        "embedding_base_url": embedding_base_url.rstrip("/"),
        "reranker_model": reranker_model,
        "reranker_base_url": reranker_base_url.rstrip("/"),
        "llm_base_url": llm_base_url.rstrip("/"),
        "llm_model": llm_model,
        "judge": "deterministic evidence-clause matching; no LLM judge",
    }

    def checkpoint() -> None:
        _write_json(
            run_path,
            _run_payload(items=items, cases=len(cases), resumed=len(reusable), source=source),
        )

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        futures = [
            executor.submit(
                _call_case,
                case=case,
                mimirq_base_url=mimirq_base_url,
                mimirq_token=mimirq_token,
                llm_base_url=llm_base_url,
                llm_api_key=llm_api_key,
                llm_model=llm_model,
                timeout=timeout,
                max_tokens=max_tokens,
            )
            for case in pending
        ]
        for future in as_completed(futures):
            items.append(future.result())
            completed = len(items)
            if completed % 25 == 0 or completed == len(cases):
                succeeded = sum(1 for item in items if item.get("ok") is True)
                print(f"[{SYSTEM_NAME}] progress={completed}/{len(cases)} ok={succeeded}", flush=True)
            if flush_every > 0 and completed % flush_every == 0:
                checkpoint()

    run = _run_payload(items=items, cases=len(cases), resumed=len(reusable), source=source)
    _write_json(run_path, run)
    return run


def _summary_markdown(summary: dict[str, Any]) -> str:
    quality = summary.get("quality") if isinstance(summary.get("quality"), dict) else {}
    latency = summary.get("latency_ms") if isinstance(summary.get("latency_ms"), dict) else {}
    return "\n".join(
        [
            "# 常州政务 800 题本地三模型复测",
            "",
            f"- 生成时间：`{summary.get('generated_at')}`",
            f"- 完成：`{summary.get('succeeded')} / {summary.get('cases')}`",
            f"- 回答证据覆盖：`{quality.get('mean_answer_clause_coverage')}`",
            f"- 回答子问题覆盖：`{quality.get('mean_answer_subquestion_coverage')}`",
            f"- 可用率：`{quality.get('usable_rate')}`",
            f"- 准确率：`{quality.get('accurate_rate')}`",
            f"- 端到端平均 / P50 / P95：`{latency.get('mean')} / {latency.get('p50')} / {latency.get('p95')} ms`",
            "- 评分：确定性证据条款匹配，不使用 LLM judge。",
            "",
        ]
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default=DEFAULT_CASES)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--mimirq-base-url", default=DEFAULT_MIMIRQ_BASE_URL)
    parser.add_argument("--mimirq-token", default=os.getenv("MIMIRQ_TOKEN") or "")
    parser.add_argument("--llm-base-url", default=os.getenv("LLM_API_BASE") or DEFAULT_LLM_BASE_URL)
    parser.add_argument("--llm-api-key", default=os.getenv("LLM_API_KEY") or "")
    parser.add_argument("--llm-model", default=os.getenv("LLM_MODEL") or DEFAULT_LLM_MODEL)
    parser.add_argument("--embedding-model", default=os.getenv("EMBEDDING_MODEL") or "bge-m3")
    parser.add_argument("--embedding-base-url", default=os.getenv("EMBEDDING_API_BASE") or "")
    parser.add_argument("--reranker-model", default=os.getenv("RERANKER_MODEL") or "bge-reranker-large")
    parser.add_argument("--reranker-base-url", default=os.getenv("RERANKER_API_BASE") or "")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-tokens", type=int, default=800)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-failures", action="store_true")
    parser.add_argument("--flush-every", type=int, default=25)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if not _text(args.mimirq_token):
        raise SystemExit("MIMIRQ_TOKEN or --mimirq-token is required")
    if not _text(args.llm_api_key):
        raise SystemExit("LLM_API_KEY or --llm-api-key is required")

    cases_path = Path(args.cases)
    all_cases = bench.load_prebuilt_cases(str(cases_path))
    cases = bench.select_cases_to_run(all_cases, limit=int(args.limit or 0))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    run = run_benchmark(
        cases=cases,
        run_path=out_dir / "run_mimirq_local_3model.json",
        mimirq_base_url=str(args.mimirq_base_url),
        mimirq_token=str(args.mimirq_token),
        llm_base_url=str(args.llm_base_url),
        llm_api_key=str(args.llm_api_key),
        llm_model=str(args.llm_model),
        embedding_model=str(args.embedding_model),
        embedding_base_url=str(args.embedding_base_url),
        reranker_model=str(args.reranker_model),
        reranker_base_url=str(args.reranker_base_url),
        timeout=float(args.timeout),
        max_tokens=int(args.max_tokens),
        concurrency=int(args.concurrency),
        resume=bool(args.resume),
        retry_failures=bool(args.retry_failures),
        flush_every=int(args.flush_every),
    )

    quality_report = evaluate_mixed_rag_quality(cases=cases, runs=[run])
    _write_json(out_dir / "quality_report.json", quality_report)
    (out_dir / "quality_report.md").write_text(build_markdown_report(quality_report), encoding="utf-8")
    leaderboard = quality_report.get("leaderboard") if isinstance(quality_report.get("leaderboard"), list) else []
    quality = leaderboard[0] if leaderboard and isinstance(leaderboard[0], dict) else {}
    audit = bench.build_audit_rows(quality_report, cases, [run])
    verdicts = bench.build_verdict_summary(audit)
    verdict = verdicts[0] if verdicts and isinstance(verdicts[0], dict) else {}
    run_summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
    summary = {
        "schema": "mimirq.local_3model_benchmark.summary.v1",
        "generated_at": _utc_now_text(),
        "cases_sha256": _sha256_file(cases_path),
        "cases": len(cases),
        "succeeded": int(run_summary.get("succeeded") or 0),
        "failed": int(run_summary.get("failed") or 0),
        "complete": run_summary.get("complete") is True,
        "models": run.get("source"),
        "quality": {
            "mean_answer_clause_coverage": quality.get("mean_answer_clause_coverage"),
            "mean_answer_subquestion_coverage": quality.get("mean_answer_subquestion_coverage"),
            "mean_evidence_coverage": quality.get("mean_evidence_coverage"),
            "mean_answer_supported_clause_rate": quality.get("mean_answer_supported_clause_rate"),
            "mean_wrong_evidence_rate": quality.get("mean_wrong_evidence_rate"),
            "accurate_rate": verdict.get("accurate_rate"),
            "usable_rate": verdict.get("usable_rate"),
            "accurate": verdict.get("accurate"),
            "partially_accurate": verdict.get("partially_accurate"),
            "insufficient_evidence": verdict.get("insufficient_evidence"),
            "no_answer": verdict.get("no_answer"),
        },
        "latency_ms": run_summary.get("latency_ms"),
    }
    _write_json(out_dir / "summary.json", summary)
    (out_dir / "summary.md").write_text(_summary_markdown(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
