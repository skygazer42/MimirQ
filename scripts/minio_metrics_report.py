import argparse
import json
import os
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _percent(v: float) -> str:
    try:
        return f"{v * 100.0:.2f}%"
    except Exception:
        return "n/a"


def _coerce_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    if q <= 0:
        return xs[0]
    if q >= 1:
        return xs[-1]
    i = int(round((len(xs) - 1) * q))
    i = max(0, min(len(xs) - 1, i))
    return xs[i]


def _read_jsonl(path: Path, *, tail: int = 0) -> Iterable[dict[str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []

    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if tail and tail > 0:
        lines = lines[-int(tail) :]

    out: list[dict[str, Any]] = []
    for ln in lines:
        try:
            rec = json.loads(ln)
        except Exception:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


@dataclass(frozen=True)
class OpSummary:
    op: str
    total: int
    success: int
    failed: int
    failure_rate: float
    p50_ms: float | None
    p90_ms: float | None
    p99_ms: float | None


def _summarize_ops(records: Iterable[dict[str, Any]]) -> tuple[list[OpSummary], list[str]]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "success": 0, "failed": 0})
    latencies: dict[str, list[float]] = defaultdict(list)
    errors: list[str] = []

    for r in records:
        op = str(r.get("op") or "").strip() or "unknown"
        ok = bool(r.get("success"))
        counts[op]["total"] += 1
        counts[op]["success" if ok else "failed"] += 1

        ms = _coerce_float(r.get("elapsed_ms"))
        if ms is not None:
            latencies[op].append(float(ms))

        err = r.get("error")
        if not ok and isinstance(err, str) and err.strip():
            errors.append(f"{op}: {err.strip()[:200]}")

    out: list[OpSummary] = []
    for op, c in sorted(counts.items(), key=lambda kv: (-kv[1]["total"], kv[0])):
        total = int(c["total"])
        failed = int(c["failed"])
        success = int(c["success"])
        failure_rate = (failed / total) if total else 0.0
        xs = latencies.get(op) or []
        out.append(
            OpSummary(
                op=op,
                total=total,
                success=success,
                failed=failed,
                failure_rate=failure_rate,
                p50_ms=_quantile(xs, 0.50),
                p90_ms=_quantile(xs, 0.90),
                p99_ms=_quantile(xs, 0.99),
            )
        )

    return out, errors


def _filter_since(records: Iterable[dict[str, Any]], *, since_ts: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in records:
        ts = _coerce_float(r.get("ts"))
        if ts is None:
            continue
        if ts >= since_ts:
            out.append(r)
    return out


def _print_table(summaries: list[OpSummary]) -> None:
    if not summaries:
        print("[minio-metrics] (no records)")
        return

    cols = ["op", "total", "failed", "failure_rate", "p50_ms", "p90_ms", "p99_ms"]
    widths = {c: len(c) for c in cols}
    rows: list[dict[str, str]] = []
    for s in summaries:
        row = {
            "op": s.op,
            "total": str(s.total),
            "failed": str(s.failed),
            "failure_rate": _percent(s.failure_rate),
            "p50_ms": f"{s.p50_ms:.2f}" if s.p50_ms is not None else "-",
            "p90_ms": f"{s.p90_ms:.2f}" if s.p90_ms is not None else "-",
            "p99_ms": f"{s.p99_ms:.2f}" if s.p99_ms is not None else "-",
        }
        rows.append(row)
        for k, v in row.items():
            widths[k] = max(widths[k], len(v))

    header = "  ".join(c.ljust(widths[c]) for c in cols)
    print(header)
    print("-" * len(header))
    for r in rows:
        print("  ".join(r[c].ljust(widths[c]) for c in cols))


def _maybe_bucket_stats(*, enabled: bool, prefix: str, max_objects: int) -> None:
    if not enabled:
        return

    try:
        from minio import Minio  # type: ignore
    except Exception:
        print("[minio-metrics] bucket stats skipped: minio package not installed")
        return

    endpoint = str(os.getenv("MINIO_ENDPOINT") or "").strip()
    access_key = str(os.getenv("MINIO_ACCESS_KEY") or "").strip()
    secret_key = str(os.getenv("MINIO_SECRET_KEY") or "").strip()
    bucket = str(os.getenv("MINIO_BUCKET_NAME") or "").strip()
    secure_raw = str(os.getenv("MINIO_USE_SSL") or "").strip().lower()
    secure = secure_raw in {"1", "true", "yes", "y", "on"}

    if not endpoint or not access_key or not secret_key or not bucket:
        print(
            "[minio-metrics] bucket stats skipped: set MINIO_ENDPOINT/MINIO_ACCESS_KEY/MINIO_SECRET_KEY/MINIO_BUCKET_NAME"
        )
        return

    client = Minio(endpoint=endpoint, access_key=access_key, secret_key=secret_key, secure=secure)

    t0 = time.perf_counter()
    count = 0
    total_bytes = 0
    try:
        for obj in client.list_objects(bucket_name=bucket, prefix=prefix, recursive=True):
            count += 1
            total_bytes += int(getattr(obj, "size", 0) or 0)
            if max_objects and count >= max_objects:
                break
    except Exception as exc:  # noqa: BLE001
        print(f"[minio-metrics] bucket stats failed: {exc}")
        return

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    truncated = bool(max_objects and count >= max_objects)
    trunc_note = " (truncated)" if truncated else ""
    print(
        f"[minio-metrics] bucket stats{trunc_note}: prefix={prefix!r} objects={count} bytes={total_bytes} elapsed_ms={elapsed_ms}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize MinIO JSONL metrics (uploads/presign/deletes).")
    parser.add_argument(
        "--path",
        default=str(os.getenv("MINIO_METRICS_LOG_PATH") or "./logs/minio_metrics.jsonl"),
        help="Path to JSONL metrics file (default: env MINIO_METRICS_LOG_PATH or ./logs/minio_metrics.jsonl)",
    )
    parser.add_argument(
        "--since-sec",
        type=float,
        default=float(os.getenv("MINIO_METRICS_SINCE_SEC") or "0"),
        help="Only include records newer than now-since-sec (0 = include all)",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=int(os.getenv("MINIO_METRICS_TAIL") or "0"),
        help="Only read last N lines from the metrics file (0 = read all)",
    )
    parser.add_argument("--show-errors", action="store_true", help="Print recent failure error strings (best-effort)")
    parser.add_argument(
        "--bucket-stats",
        action="store_true",
        help="Also compute bucket prefix object count/bytes (requires MINIO_* env vars)",
    )
    parser.add_argument("--prefix", default="images/", help="Bucket prefix for --bucket-stats (default: images/)")
    parser.add_argument(
        "--max-objects", type=int, default=0, help="Max objects to scan for bucket stats (0 = unlimited)"
    )
    args = parser.parse_args()

    path = Path(str(args.path))
    if not path.exists():
        print(f"[minio-metrics] file not found: {path}")
        return 1

    records = list(_read_jsonl(path, tail=int(args.tail or 0)))
    if float(args.since_sec or 0) > 0:
        since_ts = time.time() - float(args.since_sec)
        records = _filter_since(records, since_ts=since_ts)

    summaries, errors = _summarize_ops(records)
    print(f"[minio-metrics] records={len(records)} file={path}")
    _print_table(summaries)

    if bool(args.show_errors) and errors:
        print("\n[minio-metrics] recent failures:")
        for e in errors[-20:]:
            print(f"  - {e}")

    _maybe_bucket_stats(
        enabled=bool(args.bucket_stats), prefix=str(args.prefix or "images/"), max_objects=int(args.max_objects or 0)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
