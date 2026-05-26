#!/usr/bin/env python3
"""Run a repeatable DeepDoc QA/retrieval/KG quality gate against a live dataset."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx

DEFAULT_RETRIEVAL_VARIANTS: dict[str, dict[str, Any]] = {
    "hybrid_top10": {
        "top_k": 10,
        "score_threshold": 0.0,
        "retrieval_mode": "hybrid",
        "enable_reranker": False,
        "enable_multi_query": False,
        "use_graph": False,
    },
    "expanded_top20": {
        "top_k": 20,
        "retrieval_profile": "expanded",
        "score_threshold": 0.0,
        "retrieval_mode": "hybrid",
        "enable_reranker": False,
        "enable_multi_query": False,
        "use_graph": False,
    },
    "recall50": {
        "top_k": 50,
        "retrieval_profile": "recall50",
        "score_threshold": 0.0,
        "retrieval_mode": "hybrid",
        "enable_reranker": False,
        "enable_multi_query": False,
        "use_graph": False,
    },
}

DEFAULT_THRESHOLDS: dict[str, dict[str, float]] = {
    "retrieve:expanded_top20": {
        "min_ok_rate": 1.0,
        "min_source_hit_rate": 0.85,
        "min_fact_hit_rate": 0.50,
        "max_p95_ms": 10_000.0,
    },
    "chat": {
        "min_ok_rate": 0.95,
        "min_source_hit_rate": 0.85,
        "min_fact_hit_rate": 0.90,
        "max_p95_ms": 20_000.0,
    },
    "kg": {
        "min_ok_rate": 0.95,
        "min_source_hit_rate": 0.75,
        "min_fact_hit_rate": 0.35,
        "max_p95_ms": 8_000.0,
    },
}


def percentile(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    vals = sorted(float(v or 0.0) for v in values)
    pp = max(0, min(100, int(p)))
    if pp <= 0:
        return vals[0]
    if pp >= 100:
        return vals[-1]
    rank = int(math.ceil((pp / 100.0) * len(vals)))
    return vals[max(0, min(len(vals) - 1, rank - 1))]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _fact_groups(raw: Any) -> list[list[str]]:
    out: list[list[str]] = []
    if not isinstance(raw, list):
        return out
    for group in raw:
        if isinstance(group, list):
            terms = [str(x).strip() for x in group if str(x or "").strip()]
        else:
            terms = [str(group).strip()] if str(group or "").strip() else []
        if terms:
            out.append(terms)
    return out


def load_cases(path: Path) -> list[dict[str, Any]]:
    payload = _load_json(path)
    if isinstance(payload, list):
        raw_cases = payload
        rows: list[dict[str, Any]] = []
    elif isinstance(payload, dict):
        raw_cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
        rows = []
        for key in ("retrieval_rows", "chat_rows", "kg_rows", "rows"):
            vals = payload.get(key)
            if isinstance(vals, list):
                rows.extend([item for item in vals if isinstance(item, dict)])
    else:
        raw_cases = []
        rows = []

    expected_by_case: dict[str, str] = {}
    for row in rows:
        cid = str(row.get("case_id") or row.get("id") or "").strip()
        expected = str(row.get("expected_doc") or row.get("expected_document_id") or "").strip()
        if cid and expected:
            expected_by_case.setdefault(cid, expected)

    cases: list[dict[str, Any]] = []
    for idx, raw in enumerate(raw_cases):
        if not isinstance(raw, dict):
            continue
        cid = str(raw.get("id") or raw.get("case_id") or f"case-{idx + 1}").strip()
        question = str(raw.get("question") or raw.get("q") or "").strip()
        if not question:
            continue
        expected_doc = str(
            raw.get("expected_document_id")
            or raw.get("expected_doc")
            or raw.get("document_id")
            or expected_by_case.get(cid)
            or ""
        ).strip()
        cases.append(
            {
                "id": cid,
                "doc": str(raw.get("doc") or raw.get("document") or "").strip(),
                "question": question,
                "fact_groups": _fact_groups(raw.get("fact_groups") or raw.get("groups") or raw.get("expected_terms")),
                "expected_document_id": expected_doc or None,
            }
        )
    return cases


def _headers(*, tenant_id: str, user_id: str, bearer: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    elif user_id:
        headers["X-User-ID"] = user_id
    return headers


def _api_v1_url(base_url: str) -> str:
    base = str(base_url or "").rstrip("/")
    return base if base.endswith("/api/v1") else f"{base}/api/v1"


def _join(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_dicts(item)


def _doc_id(item: dict[str, Any]) -> str:
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    refs = item.get("references") if isinstance(item.get("references"), dict) else {}
    for obj in (item, meta, source, refs):
        for key in ("document_id", "doc_id", "source_document_id", "expected_doc"):
            val = str(obj.get(key) or "").strip()
            if val:
                return val
    return ""


def _text(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "answer",
        "content",
        "text",
        "page_content",
        "chunk_content",
        "summary",
        "title",
        "evidence",
        "quote",
    ):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val)
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    for key in ("content", "text", "title", "source", "header_path"):
        val = meta.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val)
    return "\n".join(parts)


def _extract_sources_and_text(payload: Any) -> tuple[list[str], str]:
    docs: list[str] = []
    texts: list[str] = []
    for item in _iter_dicts(payload):
        doc = _doc_id(item)
        if doc:
            docs.append(doc)
        text = _text(item)
        if text:
            texts.append(text)
    seen: set[str] = set()
    ordered_docs: list[str] = []
    for doc in docs:
        if doc not in seen:
            seen.add(doc)
            ordered_docs.append(doc)
    return ordered_docs, "\n".join(texts)


def _fact_hit(text: str, groups: list[list[str]]) -> tuple[bool, int, list[list[str]]]:
    if not groups:
        return True, 0, []
    folded = str(text or "").casefold()
    missed: list[list[str]] = []
    hit_count = 0
    for group in groups:
        if any(str(term or "").casefold() in folded for term in group):
            hit_count += 1
        else:
            missed.append(group)
    return hit_count == len(groups), hit_count, missed


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def extract_runtime_metrics(payload: Any, *, elapsed_ms: float) -> dict[str, Any]:
    """Extract compact runtime/KG observability fields from an API response."""
    metrics: dict[str, Any] = {}
    if isinstance(payload, dict):
        raw = payload.get("metrics")
        if isinstance(raw, dict):
            metrics = raw
        elif isinstance(payload.get("query_debug"), dict):
            qd = payload.get("query_debug") or {}
            raw_metrics = qd.get("metrics")
            if isinstance(raw_metrics, dict):
                metrics = raw_metrics

    retrieval_sec = _as_float(metrics.get("retrieval_elapsed_sec"), 0.0)
    server_retrieval_ms = retrieval_sec * 1000.0 if retrieval_sec > 0.0 else 0.0
    api_overhead_ms = max(0.0, float(elapsed_ms or 0.0) - server_retrieval_ms) if server_retrieval_ms > 0.0 else 0.0

    return {
        "server_retrieval_ms": round(server_retrieval_ms, 1),
        "api_overhead_ms": round(api_overhead_ms, 1),
        "retrieval_query_count": _as_int(metrics.get("retrieval_query_count"), 0),
        "retrieval_query_parallelism": _as_int(metrics.get("retrieval_query_parallelism"), 0),
        "kg_chunks_injected": _as_int(metrics.get("kg_chunks_injected"), 0),
        "kg_chunk_boost_promoted": _as_int(metrics.get("kg_chunk_boost_promoted"), 0),
        "kg_query_expansion_used": bool(metrics.get("kg_query_expansion_used")),
    }


def summarize_dataset_diagnostics(
    ingestion_stats: Any,
    kg_stats: Any,
    kg_quality_report: Any,
) -> dict[str, Any]:
    """Build a compact, PII-minimal dataset governance/KG diagnostics payload."""
    ingestion = ingestion_stats if isinstance(ingestion_stats, dict) else {}
    kg = kg_stats if isinstance(kg_stats, dict) else {}
    kgq = kg_quality_report if isinstance(kg_quality_report, dict) else {}
    kgq_summary = kgq.get("summary") if isinstance(kgq.get("summary"), dict) else kgq
    kgq_links = 0
    if isinstance(kgq_summary, dict):
        kgq_links = _as_int(
            kgq_summary.get("links", kgq_summary.get("event_entity_links", kgq_summary.get("relations", 0))),
            0,
        )

    return {
        "ingestion": {
            "total_documents": _as_int(ingestion.get("total_documents"), 0),
            "total_chunks": _as_int(ingestion.get("total_chunks"), 0),
            "total_size": _as_int(ingestion.get("total_size"), 0),
            "total_characters": _as_int(ingestion.get("total_characters"), 0),
            "by_status": dict(ingestion.get("by_status") or {}) if isinstance(ingestion.get("by_status"), dict) else {},
        },
        "kg_stats": {
            "events": _as_int(kg.get("events"), 0),
            "entities": _as_int(kg.get("entities"), 0),
            "links": _as_int(kg.get("links"), 0),
            "entity_types": list(kg.get("entity_types") or [])[:20] if isinstance(kg.get("entity_types"), list) else [],
        },
        "kg_quality": {
            "documents": _as_int(kgq_summary.get("documents"), 0) if isinstance(kgq_summary, dict) else 0,
            "events": _as_int(kgq_summary.get("events"), 0) if isinstance(kgq_summary, dict) else 0,
            "entities": _as_int(kgq_summary.get("entities"), 0) if isinstance(kgq_summary, dict) else 0,
            "links": int(kgq_links),
            "orphan_entities": _as_int(kgq_summary.get("orphan_entities"), 0) if isinstance(kgq_summary, dict) else 0,
        },
    }


async def _post_json(client: httpx.AsyncClient, url: str, payload: dict[str, Any]) -> tuple[int, Any, float]:
    started = time.perf_counter()
    try:
        resp = await client.post(url, json=payload)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        try:
            body = resp.json()
        except Exception:
            body = {"text": resp.text}
        return int(resp.status_code), body, elapsed_ms
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return 0, {"error": str(exc)[:300]}, elapsed_ms


async def _get_json(client: httpx.AsyncClient, url: str) -> tuple[int, Any, float]:
    started = time.perf_counter()
    try:
        resp = await client.get(url)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        try:
            body = resp.json()
        except Exception:
            body = {"text": resp.text}
        return int(resp.status_code), body, elapsed_ms
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return 0, {"error": str(exc)[:300]}, elapsed_ms


async def collect_dataset_diagnostics(
    *,
    base_url: str,
    dataset_id: str,
    headers: dict[str, str],
) -> dict[str, Any]:
    base = _api_v1_url(base_url)
    async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(60.0), trust_env=False) as client:
        ingestion_status, ingestion_body, ingestion_ms = await _get_json(
            client,
            _join(base, f"datasets/{dataset_id}/ingestion/stats"),
        )
        kg_status, kg_body, kg_ms = await _get_json(client, _join(base, f"kg/stats?dataset_id={dataset_id}"))
        kgq_status, kgq_body, kgq_ms = await _get_json(
            client,
            _join(base, f"evaluations/kg/quality/report?dataset_id={dataset_id}"),
        )

    out = summarize_dataset_diagnostics(
        ingestion_body if 200 <= ingestion_status < 300 else {},
        kg_body if 200 <= kg_status < 300 else {},
        kgq_body if 200 <= kgq_status < 300 else {},
    )
    out["status"] = {
        "ingestion": int(ingestion_status),
        "kg_stats": int(kg_status),
        "kg_quality": int(kgq_status),
    }
    out["elapsed_ms"] = {
        "ingestion": round(float(ingestion_ms), 1),
        "kg_stats": round(float(kg_ms), 1),
        "kg_quality": round(float(kgq_ms), 1),
    }
    return out


async def run_gate(
    *,
    base_url: str,
    dataset_id: str,
    cases: list[dict[str, Any]],
    modes: set[str],
    retrieval_variants: dict[str, dict[str, Any]],
    chat_rag_config: dict[str, Any],
    concurrency: int,
    headers: dict[str, str],
) -> list[dict[str, Any]]:
    base = _api_v1_url(base_url)
    sem = asyncio.Semaphore(max(1, int(concurrency or 1)))
    rows: list[dict[str, Any]] = []

    async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(180.0), trust_env=False) as client:

        async def run_one(kind: str, case: dict[str, Any], variant: str = "", rag_config: dict[str, Any] | None = None) -> None:
            async with sem:
                question = str(case.get("question") or "")
                if kind == "retrieve":
                    payload = {"query": question, "dataset_id": dataset_id, "rag_config": dict(rag_config or {})}
                    status, body, elapsed_ms = await _post_json(client, _join(base, "rag/retrieve-preview"), payload)
                elif kind == "chat":
                    cfg = dict(chat_rag_config or {})
                    cfg.setdefault("answer_mode", "extractive")
                    payload = {"message": question, "dataset_id": dataset_id, "rag_config": cfg}
                    status, body, elapsed_ms = await _post_json(client, _join(base, "chat"), payload)
                elif kind == "kg":
                    status, body, elapsed_ms = await _post_json(client, _join(base, "kg/search"), {"query": question, "dataset_id": dataset_id})
                else:
                    return

                docs, text = _extract_sources_and_text(body)
                runtime_metrics = extract_runtime_metrics(body, elapsed_ms=elapsed_ms)
                expected = str(case.get("expected_document_id") or "").strip()
                fact_ok, fact_hit_count, missed = _fact_hit(text, list(case.get("fact_groups") or []))
                rows.append(
                    {
                        "kind": kind,
                        "variant": variant or None,
                        "case_id": case.get("id"),
                        "question": question,
                        "ok": 200 <= int(status or 0) < 300,
                        "status": int(status or 0),
                        "elapsed_ms": round(float(elapsed_ms), 1),
                        "expected_doc": expected or None,
                        "top1_doc": docs[0] if docs else None,
                        "source_top1": bool(expected and docs and docs[0] == expected),
                        "source_hit": bool(expected and expected in docs),
                        "source_count": int(len(docs)),
                        "fact_hit": bool(fact_ok),
                        "fact_hit_count": int(fact_hit_count),
                        "fact_group_count": int(len(case.get("fact_groups") or [])),
                        "missed_groups": missed,
                        **runtime_metrics,
                    }
                )

        tasks = []
        for case in cases:
            if "retrieve" in modes:
                for name, cfg in retrieval_variants.items():
                    tasks.append(run_one("retrieve", case, name, cfg))
            if "chat" in modes:
                tasks.append(run_one("chat", case))
            if "kg" in modes:
                tasks.append(run_one("kg", case))
        await asyncio.gather(*tasks)

    rows.sort(key=lambda r: (str(r.get("kind") or ""), str(r.get("variant") or ""), str(r.get("case_id") or "")))
    return rows


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        kind = str(row.get("kind") or "").strip()
        variant = str(row.get("variant") or "").strip()
        key = f"{kind}:{variant}" if variant else kind
        grouped[key].append(row)

    out: dict[str, Any] = {}
    for key, vals in grouped.items():
        total = len(vals)
        ok = sum(1 for r in vals if bool(r.get("ok")))
        source_top1_total = sum(1 for r in vals if r.get("expected_doc"))
        if source_top1_total == 0 and any("source_hit" in r or "source_top1" in r for r in vals):
            source_top1_total = total
        source_top1 = sum(1 for r in vals if bool(r.get("source_top1")))
        source_hit = sum(1 for r in vals if bool(r.get("source_hit")))
        fact_total = sum(1 for r in vals if int(r.get("fact_group_count") or 0) > 0)
        fact_hit = sum(1 for r in vals if bool(r.get("fact_hit")) and int(r.get("fact_group_count") or 0) > 0)
        latencies = [float(r.get("elapsed_ms") or 0.0) for r in vals]
        server_retrieval_latencies = [float(r.get("server_retrieval_ms") or 0.0) for r in vals if float(r.get("server_retrieval_ms") or 0.0) > 0.0]
        api_overhead_latencies = [float(r.get("api_overhead_ms") or 0.0) for r in vals if float(r.get("api_overhead_ms") or 0.0) > 0.0]
        kg_query_expansion_used = sum(1 for r in vals if bool(r.get("kg_query_expansion_used")))
        out[key] = {
            "requests": total,
            "ok": ok,
            "ok_rate": (ok / total) if total else 0.0,
            "source_top1": source_top1,
            "source_top1_rate": (source_top1 / source_top1_total) if source_top1_total else 0.0,
            "source_hit": source_hit,
            "source_hit_rate": (source_hit / source_top1_total) if source_top1_total else 0.0,
            "fact_hit": fact_hit,
            "fact_hit_rate": (fact_hit / fact_total) if fact_total else 0.0,
            "latency": {
                "min_ms": min(latencies) if latencies else 0.0,
                "p50_ms": percentile(latencies, 50),
                "p95_ms": percentile(latencies, 95),
                "p99_ms": percentile(latencies, 99),
                "max_ms": max(latencies) if latencies else 0.0,
            },
            "runtime": {
                "server_retrieval_p50_ms": percentile(server_retrieval_latencies, 50),
                "server_retrieval_p95_ms": percentile(server_retrieval_latencies, 95),
                "api_overhead_p50_ms": percentile(api_overhead_latencies, 50),
                "api_overhead_p95_ms": percentile(api_overhead_latencies, 95),
                "max_retrieval_query_count": max([int(r.get("retrieval_query_count") or 0) for r in vals] or [0]),
                "max_retrieval_query_parallelism": max([int(r.get("retrieval_query_parallelism") or 0) for r in vals] or [0]),
            },
            "kg": {
                "chunks_injected_total": sum(int(r.get("kg_chunks_injected") or 0) for r in vals),
                "boost_promoted_total": sum(int(r.get("kg_chunk_boost_promoted") or 0) for r in vals),
                "query_expansion_used": int(kg_query_expansion_used),
                "query_expansion_used_rate": (kg_query_expansion_used / total) if total else 0.0,
            },
        }
    return out


def evaluate_gate(summary: dict[str, Any], *, thresholds: dict[str, dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    checks: list[dict[str, Any]] = []
    for key, rules in (thresholds or {}).items():
        section = summary.get(key) if isinstance(summary.get(key), dict) else {}
        if not section:
            continue
        for metric, raw_threshold in (rules or {}).items():
            if metric == "max_p95_ms":
                observed = float(((section.get("latency") or {}) if isinstance(section.get("latency"), dict) else {}).get("p95_ms") or 0.0)
                passed = observed <= float(raw_threshold)
                label = f"{key}.p95_ms"
                if not passed:
                    failures.append(f"{label}: {observed:.3f} > max {float(raw_threshold):.3f}")
            elif metric.startswith("min_"):
                field = metric.removeprefix("min_")
                observed = float(section.get(field) or 0.0)
                passed = observed >= float(raw_threshold)
                label = f"{key}.{field}"
                if not passed:
                    failures.append(f"{label}: {observed:.6f} < min {float(raw_threshold):.6f}")
            else:
                continue
            checks.append({"metric": label, "observed": observed, "threshold": float(raw_threshold), "passed": passed})
    return {"passed": not failures, "failures": failures, "checks": checks}


def _load_thresholds(path: str) -> dict[str, dict[str, Any]]:
    if not str(path or "").strip():
        return dict(DEFAULT_THRESHOLDS)
    obj = _load_json(Path(path))
    if isinstance(obj, dict) and isinstance(obj.get("thresholds"), dict):
        return dict(obj.get("thresholds") or {})
    return dict(obj) if isinstance(obj, dict) else dict(DEFAULT_THRESHOLDS)


def _load_variants(raw: str) -> dict[str, dict[str, Any]]:
    if not str(raw or "").strip():
        return dict(DEFAULT_RETRIEVAL_VARIANTS)
    path = Path(raw)
    obj = _load_json(path) if path.exists() else json.loads(raw)
    return {str(k): dict(v) for k, v in (obj or {}).items() if isinstance(v, dict)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("NEXT_PUBLIC_API_URL") or "http://127.0.0.1:8000/api/v1")
    parser.add_argument("--tenant-id", default=os.getenv("NEXT_PUBLIC_TENANT_ID") or "00000000-0000-0000-0000-000000000000")
    parser.add_argument("--user-id", default=os.getenv("NEXT_PUBLIC_USER_ID") or "deepdoc-quality-gate")
    parser.add_argument("--bearer", default="")
    parser.add_argument("--dataset-id", default="")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--modes", default="retrieve,chat,kg")
    parser.add_argument("--retrieval-variants", default="", help="JSON object or file path. Empty uses built-in DeepDoc matrix.")
    parser.add_argument("--chat-rag-config", default="", help="JSON object or file path. Empty uses expanded extractive defaults.")
    parser.add_argument("--thresholds", default="")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--out", default="artifacts/deepdoc-quality-gate/report.json")
    parser.add_argument("--include-diagnostics", action="store_true", help="Fetch dataset ingestion/KG quality diagnostics.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    cases_path = Path(str(args.cases)).expanduser().resolve()
    cases = load_cases(cases_path)
    if not cases:
        raise SystemExit(f"cases_empty: {cases_path}")

    dataset_id = str(args.dataset_id or "").strip()
    if not dataset_id:
        payload = _load_json(cases_path)
        if isinstance(payload, dict):
            dataset_id = str(payload.get("dataset_id") or "").strip()
    if not dataset_id:
        raise SystemExit("dataset_id_required")

    modes = {item.strip() for item in str(args.modes or "").split(",") if item.strip()}
    retrieval_variants = _load_variants(str(args.retrieval_variants or ""))
    if str(args.chat_rag_config or "").strip():
        raw = str(args.chat_rag_config)
        path = Path(raw)
        chat_rag_config = _load_json(path) if path.exists() else json.loads(raw)
    else:
        chat_rag_config = {
            "top_k": 20,
            "retrieval_profile": "expanded",
            "score_threshold": 0.0,
            "retrieval_mode": "hybrid",
            "enable_reranker": False,
            "enable_multi_query": False,
            "use_graph": False,
            "answer_mode": "extractive",
        }
    thresholds = _load_thresholds(str(args.thresholds or ""))

    if args.dry_run:
        print(
            json.dumps(
                {
                    "schema": "mimirq.deepdoc_quality_gate.plan.v1",
                    "dataset_id": dataset_id,
                    "case_count": len(cases),
                    "modes": sorted(modes),
                    "retrieval_variants": sorted(retrieval_variants),
                    "thresholds": thresholds,
                    "include_diagnostics": bool(args.include_diagnostics),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    rows = asyncio.run(
        run_gate(
            base_url=str(args.base_url),
            dataset_id=dataset_id,
            cases=cases,
            modes=modes,
            retrieval_variants=retrieval_variants,
            chat_rag_config=dict(chat_rag_config or {}),
            concurrency=int(args.concurrency or 1),
            headers=_headers(tenant_id=str(args.tenant_id or ""), user_id=str(args.user_id or ""), bearer=str(args.bearer or "")),
        )
    )
    summary = summarize_rows(rows)
    gate = evaluate_gate(summary, thresholds=thresholds)
    diagnostics = (
        asyncio.run(
            collect_dataset_diagnostics(
                base_url=str(args.base_url),
                dataset_id=dataset_id,
                headers=_headers(tenant_id=str(args.tenant_id or ""), user_id=str(args.user_id or ""), bearer=str(args.bearer or "")),
            )
        )
        if bool(args.include_diagnostics)
        else None
    )
    report = {
        "schema": "mimirq.deepdoc_quality_gate.v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_url": _api_v1_url(str(args.base_url)),
        "dataset_id": dataset_id,
        "case_count": len(cases),
        "modes": sorted(modes),
        "summary": summary,
        "diagnostics": diagnostics,
        "gate": gate,
        "rows": rows,
    }
    out_path = Path(str(args.out)).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[deepdoc-quality-gate] wrote {out_path}")
    if not bool(gate.get("passed")):
        for failure in gate.get("failures") or []:
            print(f"[deepdoc-quality-gate] FAIL: {failure}")
        return 2
    print("[deepdoc-quality-gate] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
