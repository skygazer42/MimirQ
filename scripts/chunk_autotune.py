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


def _score_token_p50(metrics: dict[str, Any], targets: dict[str, int]) -> tuple[int, list[str]]:
    p50 = int(metrics.get("token_p50") or 0)
    p50_min = int(targets["token_p50_min"])
    p50_max = int(targets["token_p50_max"])
    if p50 <= 0:
        return 5000, ["token_p50_missing"]
    if p50 < p50_min:
        return (p50_min - p50) * 2, ["token_p50_too_small"]
    if p50 > p50_max:
        return (p50 - p50_max) * 2, ["token_p50_too_large"]
    return 0, []


def _score_high_pct(
    value: int,
    *,
    warn_threshold: int,
    fail_threshold: int,
    warn_multiplier: int,
    fail_penalty: int,
    warn_reason: str,
    fail_reason: str,
) -> tuple[int, list[str]]:
    if value >= fail_threshold:
        return fail_penalty, [fail_reason]
    if value >= warn_threshold:
        return (value - warn_threshold) * warn_multiplier, [warn_reason]
    return 0, []


def _score_coverage(metrics: dict[str, Any], targets: dict[str, int]) -> tuple[int, list[str]]:
    cov_pct = int(metrics.get("coverage_pct") or 0)
    if cov_pct <= 0:
        return 0, []

    fail_threshold = int(targets["coverage_p50_fail"])
    warn_threshold = int(targets["coverage_p50_warn"])
    if cov_pct < fail_threshold:
        return 2000, ["coverage_fail"]
    if cov_pct < warn_threshold:
        return (warn_threshold - cov_pct) * 20, ["coverage_warn"]
    return 0, []


def _score_chunk_count(metrics: dict[str, Any]) -> tuple[int, list[str]]:
    chunks = int(metrics.get("total_chunks") or 0)
    if chunks > 10_000:
        return 250, ["too_many_chunks"]
    return 0, []


def _score(metrics: dict[str, Any], targets: dict[str, int]) -> tuple[int, list[str]]:
    """
    Lower score is better.

    This is not a scientific objective; it's a pragmatic heuristic for tuning.
    """
    reasons: list[str] = []
    score = 0
    scoring_steps = (
        _score_token_p50(metrics, targets),
        _score_high_pct(
            int(metrics.get("short_pct") or 0),
            warn_threshold=int(targets["short_pct_warn"]),
            fail_threshold=int(targets["short_pct_fail"]),
            warn_multiplier=10,
            fail_penalty=3000,
            warn_reason="short_pct_warn",
            fail_reason="short_pct_fail",
        ),
        _score_high_pct(
            int(metrics.get("long_pct") or 0),
            warn_threshold=int(targets["long_pct_warn"]),
            fail_threshold=int(targets["long_pct_fail"]),
            warn_multiplier=10,
            fail_penalty=3000,
            warn_reason="long_pct_warn",
            fail_reason="long_pct_fail",
        ),
        _score_high_pct(
            int(metrics.get("overlap_waste_pct") or 0),
            warn_threshold=int(targets["overlap_waste_p50_warn"]),
            fail_threshold=int(targets["overlap_waste_p50_fail"]),
            warn_multiplier=5,
            fail_penalty=2000,
            warn_reason="overlap_waste_warn",
            fail_reason="overlap_waste_fail",
        ),
        _score_coverage(metrics, targets),
        _score_chunk_count(metrics),
    )
    for delta, step_reasons in scoring_steps:
        score += delta
        reasons.extend(step_reasons)
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Auto-tune chunking params to match per-dataset chunk target spec (v2)."
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://localhost:8000",
        help="API base URL (default: %(default)s)",
    )
    parser.add_argument("--tenant-id", type=str, default="", help="X-Tenant-ID header value (optional)")
    parser.add_argument("--user-id", type=str, default="", help="X-User-ID header value (optional)")
    parser.add_argument("--bearer", type=str, default="", help="Authorization Bearer token (optional)")
    parser.add_argument(
        "--dataset-id",
        type=str,
        default="",
        help="Dataset UUID (optional; used to fetch chunk_targets_v2)",
    )
    parser.add_argument(
        "--file",
        type=str,
        required=True,
        help="Path to a local file to upload once (warms parse cache)",
    )
    parser.add_argument(
        "--parser-backend",
        type=str,
        default="auto",
        help="parser_backend form field (default: %(default)s)",
    )
    parser.add_argument(
        "--strategies",
        type=str,
        default="markdown_aware,markdown_header,outline,langchain_recursive,semantic_sentence",
        help="Comma-separated chunk_strategy candidates",
    )
    parser.add_argument(
        "--chunk-sizes",
        type=str,
        default="800,1000,1200,1600",
        help="Comma-separated chunk_size candidates (chars for most strategies)",
    )
    parser.add_argument(
        "--overlap-ratios",
        type=str,
        default="0.1,0.2,0.3",
        help="Comma-separated overlap ratios (chunk_overlap = chunk_size * ratio)",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default="chunk_autotune_out",
        help="Output directory (default: %(default)s)",
    )
    return parser


def _resolve_targets(
    client: httpx.Client,
    *,
    base_url: str,
    dataset_id: str,
) -> dict[str, int]:
    targets = _default_targets()
    if not dataset_id:
        return targets

    try:
        response = client.get(f"{base_url}/api/v1/datasets/{dataset_id}")
        if response.status_code == 200:
            dataset_payload = response.json()
            raw = dataset_payload.get("chunk_targets_v2")
            return _merge_targets(targets, raw if isinstance(raw, dict) else None)
        print(
            f"[chunk_autotune] WARN: failed to fetch dataset: {response.status_code} {response.text[:200]}",
            file=sys.stderr,
        )
    except Exception as exc:
        print(
            f"[chunk_autotune] WARN: failed to fetch dataset: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    return targets


def _upload_base_preview(
    client: httpx.Client,
    *,
    base_url: str,
    file_path: Path,
    dataset_id: str,
    parser_backend: str,
) -> tuple[dict[str, Any], str, str, int, int]:
    start = time.perf_counter()
    files = {"file": (file_path.name, file_path.read_bytes(), "application/octet-stream")}
    data: dict[str, Any] = {
        "parser_backend": parser_backend,
        "chunk_strategy": "langchain_recursive",
    }
    if dataset_id:
        data["dataset_id"] = dataset_id

    response = client.post(
        f"{base_url}/api/v1/documents/chunk-preview?"
        "chunk_size=1000&chunk_overlap=200&include_chunks=false&include_original_text=false",
        data=data,
        files=files,
    )
    _require(
        response.status_code == 200,
        f"chunk-preview upload failed: {response.status_code} {response.text[:200]}",
    )
    body = response.json()
    sha = str(body.get("file_sha256") or "").strip().lower()
    _require(len(sha) == 64, "chunk-preview did not return file_sha256")

    file_type = (file_path.suffix or "").lstrip(".").lower() or "txt"
    try:
        file_size = int(file_path.stat().st_size)
    except Exception:
        file_size = 0

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return body, sha, file_type, file_size, elapsed_ms


def _parse_int_values(raw: str) -> list[int]:
    values: list[int] = []
    for item in str(raw or "").split(","):
        try:
            values.append(int(float(item.strip())))
        except Exception:
            continue
    return values


def _parse_float_values(raw: str) -> list[float]:
    values: list[float] = []
    for item in str(raw or "").split(","):
        try:
            values.append(float(item.strip()))
        except Exception:
            continue
    return values


def _build_candidates(args: argparse.Namespace) -> list[dict[str, Any]]:
    strategies = [s.strip() for s in str(args.strategies or "").split(",") if s.strip()]
    chunk_sizes = _parse_int_values(str(args.chunk_sizes or ""))
    overlap_ratios = _parse_float_values(str(args.overlap_ratios or ""))
    _require(bool(strategies), "No strategies provided")
    _require(bool(chunk_sizes), "No chunk sizes provided")
    _require(bool(overlap_ratios), "No overlap ratios provided")

    candidates = _candidate_grid(
        strategies=strategies,
        chunk_sizes=chunk_sizes,
        overlap_ratios=overlap_ratios,
    )
    _require(bool(candidates), "No candidates generated")
    return candidates


def _build_candidate_row(
    response: httpx.Response,
    *,
    candidate: dict[str, Any],
    targets: dict[str, int],
) -> dict[str, Any]:
    if response.status_code != 200:
        return {
            "rank": None,
            "candidate": candidate,
            "score": 9_999_999,
            "score_reasons": ["http_error"],
            "metrics": {},
            "http_status": int(response.status_code),
            "http_error": (response.text or "")[:200],
        }

    body = response.json()
    metrics = _extract_metrics(body if isinstance(body, dict) else {})
    score, reasons = _score(metrics, targets)
    return {
        "rank": None,
        "candidate": candidate,
        "score": int(score),
        "score_reasons": reasons,
        "metrics": metrics,
        "http_status": int(response.status_code),
    }


def _candidate_sort_key(row: dict[str, Any]) -> tuple[int, str]:
    return int(row.get("score") or 9_999_999), str(row.get("candidate") or "")


def _evaluate_candidates(
    client: httpx.Client,
    *,
    base_url: str,
    candidates: list[dict[str, Any]],
    sha: str,
    file_path: Path,
    file_type: str,
    file_size: int,
    parser_backend: str,
    dataset_id: str,
    targets: dict[str, int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, candidate in enumerate(candidates, start=1):
        query = (
            "chunk_size="
            + str(candidate["chunk_size"])
            + "&chunk_overlap="
            + str(candidate["chunk_overlap"])
            + "&include_chunks=false&include_original_text=false"
        )
        form: dict[str, Any] = {
            "file_sha256": sha,
            "file_type": file_type,
            "filename": file_path.name,
            "file_size": file_size,
            "parser_backend": parser_backend,
            "chunk_strategy": str(candidate["chunk_strategy"]),
        }
        if dataset_id:
            form["dataset_id"] = dataset_id

        response = client.post(
            f"{base_url}/api/v1/documents/chunk-preview/by-sha?{query}",
            data=form,
        )
        rows.append(
            _build_candidate_row(
                response,
                candidate=candidate,
                targets=targets,
            )
        )

        if idx % 10 == 0:
            print(f"[chunk_autotune] progress {idx}/{len(candidates)}")

    rows.sort(key=_candidate_sort_key)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def _build_preset_patch(best: dict[str, Any], targets: dict[str, int]) -> dict[str, Any]:
    return {
        "default_chunk_strategy": str(best.get("candidate", {}).get("chunk_strategy") or ""),
        "pipeline": {
            "chunk_size": int(best.get("candidate", {}).get("chunk_size") or 0),
            "chunk_overlap": int(best.get("candidate", {}).get("chunk_overlap") or 0),
        },
        "chunk_targets_v2": targets,
    }


def _build_diff(
    *,
    base_body: dict[str, Any],
    best: dict[str, Any],
    targets: dict[str, int],
) -> dict[str, Any]:
    base_metrics = _extract_metrics(base_body if isinstance(base_body, dict) else {})
    best_metrics = best.get("metrics") if isinstance(best.get("metrics"), dict) else {}
    return {
        "base": {
            "candidate": {
                "chunk_strategy": "langchain_recursive",
                "chunk_size": 1000,
                "chunk_overlap": 200,
            },
            "metrics": base_metrics,
        },
        "best": {
            "candidate": best.get("candidate"),
            "metrics": best_metrics,
            "score": best.get("score"),
            "score_reasons": best.get("score_reasons"),
        },
        "targets": targets,
    }


def _write_outputs(
    *,
    out_dir: Path,
    targets: dict[str, int],
    rows: list[dict[str, Any]],
    best: dict[str, Any],
    base_body: dict[str, Any],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "targets.json", targets)
    _write_json(out_dir / "leaderboard.json", {"targets": targets, "rows": rows})
    _write_json(out_dir / "preset_patch.json", _build_preset_patch(best, targets))
    _write_json(
        out_dir / "diff.json",
        _build_diff(base_body=base_body, best=best, targets=targets),
    )


def main() -> None:
    args = _build_parser().parse_args()
    base_url = str(args.base_url or "").rstrip("/")
    _require(bool(base_url), "--base-url is required")

    file_path = Path(str(args.file))
    _require(file_path.exists(), f"file not found: {file_path}")

    dataset_id = str(args.dataset_id or "").strip()
    out_dir = Path(str(args.out_dir or "chunk_autotune_out"))

    with httpx.Client(timeout=60.0, headers=_headers(args)) as client:
        targets = _resolve_targets(client, base_url=base_url, dataset_id=dataset_id)
        base_body, sha, file_type, file_size, elapsed_ms = _upload_base_preview(
            client,
            base_url=base_url,
            file_path=file_path,
            dataset_id=dataset_id,
            parser_backend=str(args.parser_backend),
        )
        print(f"[chunk_autotune] upload ok sha={sha[:10]}… elapsed_ms={elapsed_ms}")

        candidates = _build_candidates(args)
        rows = _evaluate_candidates(
            client,
            base_url=base_url,
            candidates=candidates,
            sha=sha,
            file_path=file_path,
            file_type=file_type,
            file_size=file_size,
            parser_backend=str(args.parser_backend),
            dataset_id=dataset_id,
            targets=targets,
        )
        best = rows[0] if rows else None
        _require(best is not None, "No candidates evaluated")
        _write_outputs(
            out_dir=out_dir,
            targets=targets,
            rows=rows,
            best=best,
            base_body=base_body,
        )
        print(f"[chunk_autotune] done. candidates={len(rows)} best_score={best.get('score')} out_dir={out_dir}")


if __name__ == "__main__":
    main()
