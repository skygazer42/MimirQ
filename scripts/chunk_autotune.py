#!/usr/bin/env python3
"""
Chunking auto-tuner (dataset-focused).

Goal:
- Search (chunk_strategy, chunk_size, chunk_overlap) candidates to better match
  a token-distribution target spec (P50 range, short/long ratios) and cost signals
  (overlap waste, coverage).
- Export reproducible presets + a base-vs-best diff report.

This script is intentionally deterministic and CI-friendly:
- stable candidate ordering
- no interactive prompts
"""


import argparse
import itertools
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx


def _require(cond: bool, msg: str) -> None:
    if cond:
        return
    print(f"[chunk_autotune] ERROR: {msg}", file=sys.stderr)
    raise SystemExit(2)


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _headers(args: argparse.Namespace) -> dict[str, str]:
    h: dict[str, str] = {}
    if args.tenant_id:
        h["X-Tenant-ID"] = str(args.tenant_id)
    if args.user_id:
        h["X-User-ID"] = str(args.user_id)
    if args.bearer:
        h["Authorization"] = f"Bearer {args.bearer}"
    return h


def _default_targets() -> dict[str, int]:
    # Keep aligned with app/services/dataset_profile_service.py defaults.
    return {
        "token_p50_min": 200,
        "token_p50_max": 400,
        "short_pct_warn": 20,  # <=100 tokens
        "short_pct_fail": 35,
        "long_pct_warn": 10,  # >=800 tokens
        "long_pct_fail": 20,
        "overlap_waste_p50_warn": 35,  # %
        "overlap_waste_p50_fail": 60,
        "coverage_p50_warn": 98,  # %
        "coverage_p50_fail": 90,
    }


def _merge_targets(base: dict[str, int], override: dict[str, Any] | None) -> dict[str, int]:
    out = dict(base)
    o = override if isinstance(override, dict) else {}
    for k, v in o.items():
        if k not in out:
            continue
        try:
            if v is None or isinstance(v, bool):
                continue
            out[k] = int(v)
        except Exception:
            continue
    # Minimal sanity.
    if out["token_p50_min"] > out["token_p50_max"]:
        out["token_p50_min"], out["token_p50_max"] = out["token_p50_max"], out["token_p50_min"]
    out["short_pct_warn"] = max(0, min(100, out["short_pct_warn"]))
    out["short_pct_fail"] = max(0, min(100, out["short_pct_fail"]))
    if out["short_pct_warn"] > out["short_pct_fail"]:
        out["short_pct_warn"], out["short_pct_fail"] = out["short_pct_fail"], out["short_pct_warn"]
    out["long_pct_warn"] = max(0, min(100, out["long_pct_warn"]))
    out["long_pct_fail"] = max(0, min(100, out["long_pct_fail"]))
    if out["long_pct_warn"] > out["long_pct_fail"]:
        out["long_pct_warn"], out["long_pct_fail"] = out["long_pct_fail"], out["long_pct_warn"]
    out["overlap_waste_p50_warn"] = max(0, min(100, out["overlap_waste_p50_warn"]))
    out["overlap_waste_p50_fail"] = max(0, min(100, out["overlap_waste_p50_fail"]))
    if out["overlap_waste_p50_warn"] > out["overlap_waste_p50_fail"]:
        out["overlap_waste_p50_warn"], out["overlap_waste_p50_fail"] = (
            out["overlap_waste_p50_fail"],
            out["overlap_waste_p50_warn"],
        )
    out["coverage_p50_warn"] = max(0, min(100, out["coverage_p50_warn"]))
    out["coverage_p50_fail"] = max(0, min(100, out["coverage_p50_fail"]))
    # Coverage is higher-is-better: fail threshold should be <= warn threshold.
    if out["coverage_p50_fail"] > out["coverage_p50_warn"]:
        out["coverage_p50_fail"] = out["coverage_p50_warn"]
    return out


def _hist_counts(token_stats: dict[str, Any]) -> tuple[int, int, int]:
    """
    Return (total, short<=100 count, long>=800 count) from a token stats histogram.

    Expects bin labels aligned with app/services/dataset_profile_utils.py:CHUNK_TOKEN_BINS.
    """
    try:
        total = int(token_stats.get("count") or 0)
    except Exception:
        total = 0

    hist = token_stats.get("histogram")
    if not isinstance(hist, list) or not hist:
        return total, 0, 0

    by_label: dict[str, int] = {}
    for b in hist:
        if not isinstance(b, dict):
            continue
        lab = str(b.get("label") or "").strip()
        if not lab:
            continue
        try:
            by_label[lab] = int(b.get("count") or 0)
        except Exception:
            by_label[lab] = 0

    short_cnt = int(by_label.get("0-50", 0) + by_label.get("50-100", 0))
    long_cnt = int(by_label.get("800+", 0))
    return total, short_cnt, long_cnt


def _pct(n: int, d: int) -> int:
    if d <= 0:
        return 0
    return int(round((max(0, int(n)) / float(d)) * 100.0))


def _extract_metrics(body: dict[str, Any]) -> dict[str, Any]:
    tok = body.get("chunking_stats_tokens")
    tokd = tok if isinstance(tok, dict) else {}

    total, short_cnt, long_cnt = _hist_counts(tokd)
    short_pct = _pct(short_cnt, total)
    long_pct = _pct(long_cnt, total)

    try:
        token_p50 = int(tokd.get("median") or 0)
    except Exception:
        token_p50 = 0

    st = body.get("stats")
    std = st if isinstance(st, dict) else {}
    try:
        waste_pct = int(round(float(std.get("overlap_waste_ratio") or 0.0) * 100.0))
    except Exception:
        waste_pct = 0
    try:
        cov_pct = int(round(float(std.get("coverage_ratio") or 0.0) * 100.0))
    except Exception:
        cov_pct = 0

    return {
        "token_p50": int(token_p50),
        "short_pct": int(short_pct),
        "long_pct": int(long_pct),
        "overlap_waste_pct": int(max(0, min(100, waste_pct))),
        "coverage_pct": int(max(0, min(100, cov_pct))),
        "total_chunks": int(body.get("total_chunks") or 0),
        "total_characters": int(body.get("total_characters") or 0),
    }


def _score(metrics: dict[str, Any], targets: dict[str, int]) -> tuple[int, list[str]]:
    """
    Lower score is better.

    This is not a scientific objective; it's a pragmatic heuristic for tuning.
    """
    reasons: list[str] = []
    score = 0

    p50 = int(metrics.get("token_p50") or 0)
    p50_min = int(targets["token_p50_min"])
    p50_max = int(targets["token_p50_max"])
    if p50 <= 0:
        score += 5000
        reasons.append("token_p50_missing")
    elif p50 < p50_min:
        score += (p50_min - p50) * 2
        reasons.append("token_p50_too_small")
    elif p50 > p50_max:
        score += (p50 - p50_max) * 2
        reasons.append("token_p50_too_large")

    short_pct = int(metrics.get("short_pct") or 0)
    if short_pct >= int(targets["short_pct_fail"]):
        score += 3000
        reasons.append("short_pct_fail")
    elif short_pct >= int(targets["short_pct_warn"]):
        score += (short_pct - int(targets["short_pct_warn"])) * 10
        reasons.append("short_pct_warn")

    long_pct = int(metrics.get("long_pct") or 0)
    if long_pct >= int(targets["long_pct_fail"]):
        score += 3000
        reasons.append("long_pct_fail")
    elif long_pct >= int(targets["long_pct_warn"]):
        score += (long_pct - int(targets["long_pct_warn"])) * 10
        reasons.append("long_pct_warn")

    waste_pct = int(metrics.get("overlap_waste_pct") or 0)
    if waste_pct >= int(targets["overlap_waste_p50_fail"]):
        score += 2000
        reasons.append("overlap_waste_fail")
    elif waste_pct >= int(targets["overlap_waste_p50_warn"]):
        score += (waste_pct - int(targets["overlap_waste_p50_warn"])) * 5
        reasons.append("overlap_waste_warn")

    cov_pct = int(metrics.get("coverage_pct") or 0)
    if cov_pct > 0:
        if cov_pct < int(targets["coverage_p50_fail"]):
            score += 2000
            reasons.append("coverage_fail")
        elif cov_pct < int(targets["coverage_p50_warn"]):
            score += (int(targets["coverage_p50_warn"]) - cov_pct) * 20
            reasons.append("coverage_warn")

    # Gentle cost bias: prefer fewer chunks, all else equal.
    chunks = int(metrics.get("total_chunks") or 0)
    if chunks > 10_000:
        score += 250
        reasons.append("too_many_chunks")

    return int(score), reasons


def _candidate_grid(
    *,
    strategies: list[str],
    chunk_sizes: list[int],
    overlap_ratios: list[float],
) -> list[dict[str, Any]]:
    # Stable ordering.
    out: list[dict[str, Any]] = []
    for strategy, size, ratio in itertools.product(strategies, chunk_sizes, overlap_ratios):
        s = str(strategy or "").strip()
        if not s:
            continue
        chunk_size = int(size)
        if chunk_size <= 0:
            continue
        # Overlap derived from ratio; keep within API guards.
        if s == "separator":
            overlap = 0
        else:
            overlap = int(round(chunk_size * float(ratio)))
            overlap = max(0, min(1000, overlap))
            if overlap >= chunk_size:
                overlap = max(0, chunk_size - 1)
        out.append(
            {
                "chunk_strategy": s,
                "chunk_size": int(chunk_size),
                "chunk_overlap": int(overlap),
            }
        )
    # Dedup (same overlap after clamping).
    seen: set[tuple[str, int, int]] = set()
    uniq: list[dict[str, Any]] = []
    for c in out:
        key = (str(c["chunk_strategy"]), int(c["chunk_size"]), int(c["chunk_overlap"]))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    return uniq


def main() -> None:
    p = argparse.ArgumentParser(description="Auto-tune chunking params to match per-dataset chunk target spec (v2).")
    p.add_argument("--base-url", type=str, default="http://localhost:8000", help="API base URL (default: %(default)s)")
    p.add_argument("--tenant-id", type=str, default="", help="X-Tenant-ID header value (optional)")
    p.add_argument("--user-id", type=str, default="", help="X-User-ID header value (optional)")
    p.add_argument("--bearer", type=str, default="", help="Authorization Bearer token (optional)")

    p.add_argument("--dataset-id", type=str, default="", help="Dataset UUID (optional; used to fetch chunk_targets_v2)")
    p.add_argument("--file", type=str, required=True, help="Path to a local file to upload once (warms parse cache)")
    p.add_argument("--parser-backend", type=str, default="auto", help="parser_backend form field (default: %(default)s)")

    p.add_argument("--strategies", type=str, default="markdown_aware,markdown_header,outline,langchain_recursive,semantic_sentence", help="Comma-separated chunk_strategy candidates")
    p.add_argument("--chunk-sizes", type=str, default="800,1000,1200,1600", help="Comma-separated chunk_size candidates (chars for most strategies)")
    p.add_argument("--overlap-ratios", type=str, default="0.1,0.2,0.3", help="Comma-separated overlap ratios (chunk_overlap = chunk_size * ratio)")

    p.add_argument("--out-dir", type=str, default="chunk_autotune_out", help="Output directory (default: %(default)s)")

    args = p.parse_args()
    base_url = str(args.base_url or "").rstrip("/")
    _require(bool(base_url), "--base-url is required")

    file_path = Path(str(args.file))
    _require(file_path.exists(), f"file not found: {file_path}")

    dataset_id = str(args.dataset_id or "").strip()
    out_dir = Path(str(args.out_dir or "chunk_autotune_out"))

    # Resolve per-dataset chunk targets (best-effort).
    targets = _default_targets()

    with httpx.Client(timeout=60.0, headers=_headers(args)) as client:
        dataset_payload: dict[str, Any] | None = None
        if dataset_id:
            try:
                r = client.get(f"{base_url}/api/v1/datasets/{dataset_id}")
                if r.status_code == 200:
                    dataset_payload = r.json()
                    raw = dataset_payload.get("chunk_targets_v2")
                    targets = _merge_targets(targets, raw if isinstance(raw, dict) else None)
                else:
                    print(f"[chunk_autotune] WARN: failed to fetch dataset: {r.status_code} {r.text[:200]}", file=sys.stderr)
            except Exception as exc:
                print(f"[chunk_autotune] WARN: failed to fetch dataset: {type(exc).__name__}: {exc}", file=sys.stderr)

        # Warm parse cache + get SHA by uploading once (include_chunks=false for smaller payload).
        t0 = time.perf_counter()
        files = {"file": (file_path.name, file_path.read_bytes(), "application/octet-stream")}
        data: dict[str, Any] = {"parser_backend": str(args.parser_backend), "chunk_strategy": "langchain_recursive"}
        if dataset_id:
            data["dataset_id"] = dataset_id

        base_preview = client.post(
            f"{base_url}/api/v1/documents/chunk-preview?chunk_size=1000&chunk_overlap=200&include_chunks=false&include_original_text=false",
            data=data,
            files=files,
        )
        _require(base_preview.status_code == 200, f"chunk-preview upload failed: {base_preview.status_code} {base_preview.text[:200]}")
        base_body = base_preview.json()
        sha = str(base_body.get("file_sha256") or "").strip().lower()
        _require(len(sha) == 64, "chunk-preview did not return file_sha256")

        file_type = (file_path.suffix or "").lstrip(".").lower() or "txt"
        try:
            file_size = int(file_path.stat().st_size)
        except Exception:
            file_size = 0

        print(f"[chunk_autotune] upload ok sha={sha[:10]}… elapsed_ms={int((time.perf_counter()-t0)*1000)}")

        # Candidate grid.
        strategies = [s.strip() for s in str(args.strategies or "").split(",") if s.strip()]
        chunk_sizes: list[int] = []
        for s in str(args.chunk_sizes or "").split(","):
            try:
                chunk_sizes.append(int(float(s.strip())))
            except Exception:
                continue
        overlap_ratios: list[float] = []
        for r in str(args.overlap_ratios or "").split(","):
            try:
                overlap_ratios.append(float(r.strip()))
            except Exception:
                continue
        _require(bool(strategies), "No strategies provided")
        _require(bool(chunk_sizes), "No chunk sizes provided")
        _require(bool(overlap_ratios), "No overlap ratios provided")

        candidates = _candidate_grid(strategies=strategies, chunk_sizes=chunk_sizes, overlap_ratios=overlap_ratios)
        _require(bool(candidates), "No candidates generated")

        rows: list[dict[str, Any]] = []
        for idx, cand in enumerate(candidates, start=1):
            qs = (
                "chunk_size="
                + str(cand["chunk_size"])
                + "&chunk_overlap="
                + str(cand["chunk_overlap"])
                + "&include_chunks=false&include_original_text=false"
            )
            form = {
                "file_sha256": sha,
                "file_type": file_type,
                "filename": file_path.name,
                "file_size": file_size,
                "parser_backend": str(args.parser_backend),
                "chunk_strategy": str(cand["chunk_strategy"]),
            }
            if dataset_id:
                form["dataset_id"] = dataset_id

            r = client.post(f"{base_url}/api/v1/documents/chunk-preview/by-sha?{qs}", data=form)
            if r.status_code != 200:
                rows.append(
                    {
                        "rank": None,
                        "candidate": cand,
                        "score": 9_999_999,
                        "score_reasons": ["http_error"],
                        "metrics": {},
                        "http_status": int(r.status_code),
                        "http_error": (r.text or "")[:200],
                    }
                )
                continue

            body = r.json()
            metrics = _extract_metrics(body if isinstance(body, dict) else {})
            score, reasons = _score(metrics, targets)
            rows.append(
                {
                    "rank": None,
                    "candidate": cand,
                    "score": int(score),
                    "score_reasons": reasons,
                    "metrics": metrics,
                    "http_status": int(r.status_code),
                }
            )

            if idx % 10 == 0:
                print(f"[chunk_autotune] progress {idx}/{len(candidates)}")

        rows.sort(key=lambda x: (int(x.get("score") or 9_999_999), str(x.get("candidate") or "")))
        for i, row in enumerate(rows, start=1):
            row["rank"] = i

        best = rows[0] if rows else None
        _require(best is not None, "No candidates evaluated")

        # Build a dataset patch payload (compatible with PATCH /api/v1/datasets/{id}).
        preset_patch: dict[str, Any] = {
            "default_chunk_strategy": str(best.get("candidate", {}).get("chunk_strategy") or ""),
            "pipeline": {
                "chunk_size": int(best.get("candidate", {}).get("chunk_size") or 0),
                "chunk_overlap": int(best.get("candidate", {}).get("chunk_overlap") or 0),
            },
            "chunk_targets_v2": targets,
        }

        out_dir.mkdir(parents=True, exist_ok=True)
        _write_json(out_dir / "targets.json", targets)
        _write_json(out_dir / "leaderboard.json", {"targets": targets, "rows": rows})
        _write_json(out_dir / "preset_patch.json", preset_patch)

        # Base-vs-best diff (best-effort): treat the first upload preview as "base".
        base_metrics = _extract_metrics(base_body if isinstance(base_body, dict) else {})
        best_metrics = best.get("metrics") if isinstance(best.get("metrics"), dict) else {}
        diff = {
            "base": {"candidate": {"chunk_strategy": "langchain_recursive", "chunk_size": 1000, "chunk_overlap": 200}, "metrics": base_metrics},
            "best": {"candidate": best.get("candidate"), "metrics": best_metrics, "score": best.get("score"), "score_reasons": best.get("score_reasons")},
            "targets": targets,
        }
        _write_json(out_dir / "diff.json", diff)

        print(f"[chunk_autotune] done. candidates={len(rows)} best_score={best.get('score')} out_dir={out_dir}")


if __name__ == "__main__":
    main()
