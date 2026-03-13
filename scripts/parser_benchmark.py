from __future__ import annotations

import argparse
import difflib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    path: Path
    golden_markdown_path: Optional[Path] = None


_HEADING_RE = re.compile(r"(?m)^#{1,6}\s+\S+")
_LIST_ITEM_RE = re.compile(r"(?m)^\s*(?:[-*+]|[0-9]+\.)\s+\S+")
_FENCE_RE = re.compile(r"(?m)^\s*```")
_TABLE_SEP_RE = re.compile(r"(?m)^\s*\|?(?:\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?\s*$")


def _iter_files(root: Path, *, exts: Iterable[str]) -> list[Path]:
    allowed = {str(e).lower() for e in exts}
    out: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in allowed:
            continue
        out.append(p)
    out.sort()
    return out


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _join_documents_to_markdown(documents: Iterable[Any]) -> str:
    parts: list[str] = []
    for d in documents or []:
        parts.append(str(getattr(d, "page_content", "") or ""))
    return "\n\n".join(parts).strip()


def _markdown_to_plain_text(markdown: str) -> str:
    s = str(markdown or "")
    # Drop fenced code blocks (cheap).
    s = re.sub(r"```[\s\S]*?```", " ", s)
    # Inline code.
    s = re.sub(r"`[^`]*`", " ", s)
    # Links: [text](url) -> text
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    # Remove common punctuation/markdown tokens.
    s = re.sub(r"[#>*_\-=`|]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _plain_chars(markdown: str) -> int:
    return int(len(_markdown_to_plain_text(markdown)))


def _structure_metrics(markdown: str) -> dict[str, Any]:
    md = str(markdown or "")
    return {
        "chars": int(len(md)),
        "plain_chars": _plain_chars(md),
        "headings": int(len(_HEADING_RE.findall(md))),
        "list_items": int(len(_LIST_ITEM_RE.findall(md))),
        "fences": int(len(_FENCE_RE.findall(md))),
        "table_separators": int(len(_TABLE_SEP_RE.findall(md))),
    }


def _similarity(a: str, b: str) -> float:
    aa = _markdown_to_plain_text(a)
    bb = _markdown_to_plain_text(b)
    if not aa and not bb:
        return 1.0
    if not aa or not bb:
        return 0.0
    return float(difflib.SequenceMatcher(None, aa, bb).ratio())


def _load_cases(input_dir: Path, *, manifest_path: Optional[Path], max_files: int) -> list[BenchmarkCase]:
    if manifest_path:
        obj = json.loads(_read_text(manifest_path))
        rows = obj.get("cases") if isinstance(obj, dict) else obj
        if not isinstance(rows, list):
            raise ValueError("manifest_invalid: expected {'cases': [...]} or [...]")
        cases: list[BenchmarkCase] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            cid = str(row.get("id") or row.get("case_id") or "").strip()
            rel = str(row.get("path") or "").strip()
            if not cid or not rel:
                continue
            src = (input_dir / rel).resolve()
            golden_rel = str(row.get("golden_markdown") or row.get("golden_markdown_path") or "").strip()
            golden = (input_dir / golden_rel).resolve() if golden_rel else None
            cases.append(BenchmarkCase(case_id=cid, path=src, golden_markdown_path=golden))
        return cases[: max(0, int(max_files or 0))]

    from app.core.config import settings

    paths = _iter_files(input_dir, exts=getattr(settings, "allowed_extensions_list", [".pdf", ".md", ".txt"]))
    cases = [
        BenchmarkCase(case_id=str(p.relative_to(input_dir)).replace("\\", "/"), path=p)
        for p in paths[: max(0, int(max_files or 0))]
    ]
    return cases


def evaluate_strict_regressions(
    *,
    current_summary: dict[str, Any],
    baseline_summary: dict[str, Any],
    max_drop_by_metric: dict[str, float],
) -> dict[str, Any]:
    failures: list[str] = []
    by_backend: dict[str, Any] = {}
    metrics = [
        str(m).strip()
        for m in (max_drop_by_metric or {}).keys()
        if str(m).strip()
    ]
    for backend, after in (current_summary or {}).items():
        if not isinstance(after, dict):
            continue
        before = baseline_summary.get(backend)
        if not isinstance(before, dict):
            continue

        backend_failures: list[dict[str, Any]] = []
        for metric in metrics:
            max_drop = max_drop_by_metric.get(metric)
            try:
                allowed_drop = abs(float(max_drop))
            except Exception:
                continue

            b_raw = before.get(metric)
            a_raw = after.get(metric)
            if b_raw is None or a_raw is None:
                continue
            try:
                b = float(b_raw)
                a = float(a_raw)
            except Exception:
                continue
            delta = float(a - b)
            if delta < (0.0 - allowed_drop):
                backend_failures.append(
                    {
                        "metric": metric,
                        "before": b,
                        "after": a,
                        "delta": round(delta, 6),
                        "max_drop": allowed_drop,
                    }
                )
                failures.append(
                    f"{backend}.{metric} regressed by {delta:.4f} (before={b:.4f}, after={a:.4f}, allowed_drop={allowed_drop:.4f})"
                )

        if backend_failures:
            by_backend[str(backend)] = backend_failures

    return {
        "passed": bool(len(failures) == 0),
        "failures": failures,
        "by_backend": by_backend,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Parser benchmark harness (golden set optional).")
    ap.add_argument("--input-dir", required=True, help="Directory containing input files (and optional golden markdown files).")
    ap.add_argument("--manifest", default="", help="Optional JSON manifest describing cases + golden markdown paths.")
    ap.add_argument("--out", default="runs/parser_benchmark.json", help="Output JSON path.")
    ap.add_argument("--baseline", default="", help="Optional previous report JSON to diff against (adds report.regressions).")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Fail with non-zero exit when baseline diff exceeds strict regression thresholds.",
    )
    ap.add_argument(
        "--strict-max-ok-rate-drop",
        type=float,
        default=0.02,
        help="Allowed maximum drop for summary.<backend>.ok_rate under --strict.",
    )
    ap.add_argument(
        "--strict-max-parse-score-drop",
        type=float,
        default=0.03,
        help="Allowed maximum drop for summary.<backend>.parse_score_mean under --strict.",
    )
    ap.add_argument(
        "--strict-max-golden-similarity-drop",
        type=float,
        default=0.03,
        help="Allowed maximum drop for summary.<backend>.golden_similarity_mean under --strict.",
    )
    ap.add_argument(
        "--strict-max-golden-coverage-drop",
        type=float,
        default=0.05,
        help="Allowed maximum drop for summary.<backend>.golden_coverage_ratio_mean under --strict.",
    )
    ap.add_argument("--max-files", type=int, default=50, help="Max number of files/cases to run.")
    ap.add_argument(
        "--backends",
        default="auto,basic,deepdoc,docling,mineru,marker,markitdown,pandoc",
        help="Comma-separated parser backends to try per case.",
    )

    args = ap.parse_args()

    input_dir = Path(args.input_dir).resolve()
    if not input_dir.exists():
        raise SystemExit(f"input_dir_not_found: {input_dir}")

    manifest_path = Path(str(args.manifest)).resolve() if str(args.manifest or "").strip() else None
    baseline_path = Path(str(args.baseline)).resolve() if str(args.baseline or "").strip() else None
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    backends = [b.strip().lower() for b in str(args.backends or "").split(",") if b.strip()]
    if not backends:
        raise SystemExit("backends_empty")

    cases = _load_cases(input_dir, manifest_path=manifest_path, max_files=int(args.max_files or 0))
    if not cases:
        raise SystemExit("no_cases_found")

    from app.parsing.factory import parser_factory
    from app.parsing.quality.document_quality import score_document_parse_quality
    from app.parsing.quality.scorer import score_pdf_quality
    from app.parsing.quality.text_quality import score_parsed_text_quality

    started_at = datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "schema": "mimirq.parser_benchmark.v1",
        "generated_at": started_at.isoformat(),
        "input_dir": str(input_dir),
        "manifest": str(manifest_path) if manifest_path else None,
        "baseline": str(baseline_path) if baseline_path else None,
        "backends": backends,
        "cases": [],
        "summary": {},
    }

    by_backend: dict[str, dict[str, Any]] = {
        b: {"attempts": 0, "ok": 0, "elapsed_ms": [], "parse_score": [], "similarity": [], "coverage_ratio": []}
        for b in backends
    }

    for case in cases:
        file_ext = case.path.suffix.lower()
        pdf_quality: dict[str, Any] | None = None
        if file_ext == ".pdf":
            try:
                pdf_quality = score_pdf_quality(case.path)
            except Exception:
                pdf_quality = None

        golden_md = ""
        if case.golden_markdown_path and case.golden_markdown_path.exists():
            golden_md = _read_text(case.golden_markdown_path)
        golden_struct = _structure_metrics(golden_md) if golden_md else None
        golden_plain_chars = int(golden_struct.get("plain_chars") or 0) if isinstance(golden_struct, dict) else 0

        case_row: dict[str, Any] = {
            "id": case.case_id,
            "path": str(case.path),
            "file_type": file_ext.lstrip("."),
            "golden_markdown_path": str(case.golden_markdown_path) if case.golden_markdown_path else None,
            "golden": ({"structure": golden_struct} if golden_struct else None),
            "attempts": [],
        }

        for backend in backends:
            by_backend[backend]["attempts"] += 1
            t0 = time.perf_counter()
            attempt: dict[str, Any] = {"backend": backend, "ok": False}
            try:
                docs, resolved_backend, prov = parser_factory.parse_with_provenance(
                    case.path,
                    parser_backend=backend,
                    pdf_quality=pdf_quality,
                )
                md = _join_documents_to_markdown(docs)
                tq = score_parsed_text_quality(md).to_dict()
                pq = score_document_parse_quality(pdf_quality=pdf_quality, parsed_text_quality=tq)
                struct = _structure_metrics(md)

                attempt.update(
                    {
                        "ok": True,
                        "resolved_backend": resolved_backend,
                        "provenance": prov,
                        "text_quality": tq,
                        "parse_quality": pq,
                        "structure": struct,
                    }
                )
                if golden_md:
                    sim = _similarity(md, golden_md)
                    attempt["golden_similarity"] = round(float(sim), 4)
                    if golden_plain_chars > 0:
                        cov = float(struct.get("plain_chars") or 0) / float(golden_plain_chars)
                        attempt["golden_coverage_ratio"] = round(float(cov), 4)
                        by_backend[backend]["coverage_ratio"].append(float(cov))
                    by_backend[backend]["similarity"].append(float(sim))

                by_backend[backend]["ok"] += 1
                by_backend[backend]["parse_score"].append(float(pq.get("score") or 0.0))
            except Exception as exc:
                attempt.update(
                    {
                        "ok": False,
                        "error_type": exc.__class__.__name__,
                        "error_message": str(exc)[:200],
                    }
                )
            finally:
                elapsed_ms = int(round((time.perf_counter() - t0) * 1000))
                attempt["elapsed_ms"] = elapsed_ms
                by_backend[backend]["elapsed_ms"].append(int(elapsed_ms))
                case_row["attempts"].append(attempt)

        report["cases"].append(case_row)

    # Aggregate summary.
    summary: dict[str, Any] = {}
    for backend, stats in by_backend.items():
        elapsed = sorted(int(x) for x in stats.get("elapsed_ms") or [])
        parse_scores = [float(x) for x in stats.get("parse_score") or []]
        sims = [float(x) for x in stats.get("similarity") or []]
        covs = [float(x) for x in stats.get("coverage_ratio") or []]

        def _pct(vals: list[int], p: float) -> int | None:
            if not vals:
                return None
            k = int(round((p / 100.0) * (len(vals) - 1)))
            k = max(0, min(k, len(vals) - 1))
            return int(vals[k])

        summary[backend] = {
            "attempts": int(stats.get("attempts") or 0),
            "ok": int(stats.get("ok") or 0),
            "ok_rate": round((float(stats.get("ok") or 0) / float(stats.get("attempts") or 1)), 4),
            "elapsed_ms_p50": _pct(elapsed, 50.0),
            "elapsed_ms_p90": _pct(elapsed, 90.0),
            "parse_score_mean": (round(sum(parse_scores) / len(parse_scores), 4) if parse_scores else None),
            "golden_similarity_mean": (round(sum(sims) / len(sims), 4) if sims else None),
            "golden_coverage_ratio_mean": (round(sum(covs) / len(covs), 4) if covs else None),
        }

    report["summary"] = summary

    # Optional: compute a simple baseline diff (best-effort).
    if baseline_path and baseline_path.exists():
        try:
            baseline_obj = json.loads(_read_text(baseline_path))
        except Exception:
            baseline_obj = {}
        baseline_summary = baseline_obj.get("summary") if isinstance(baseline_obj, dict) else {}
        baseline_summary = baseline_summary if isinstance(baseline_summary, dict) else {}

        def _metric(before: dict[str, Any], after: dict[str, Any], key: str) -> dict[str, Any] | None:
            b = before.get(key)
            a = after.get(key)
            if b is None and a is None:
                return None
            try:
                delta = (float(a) - float(b)) if a is not None and b is not None else None
            except Exception:
                delta = None
            return {"before": b, "after": a, "delta": (round(delta, 6) if isinstance(delta, float) else delta)}

        diffs: dict[str, Any] = {}
        for backend, after in summary.items():
            before = baseline_summary.get(backend) if isinstance(baseline_summary.get(backend), dict) else {}
            before = before if isinstance(before, dict) else {}
            diffs[backend] = {
                k: v
                for k, v in (
                    ("ok_rate", _metric(before, after, "ok_rate")),
                    ("elapsed_ms_p50", _metric(before, after, "elapsed_ms_p50")),
                    ("elapsed_ms_p90", _metric(before, after, "elapsed_ms_p90")),
                    ("parse_score_mean", _metric(before, after, "parse_score_mean")),
                    ("golden_similarity_mean", _metric(before, after, "golden_similarity_mean")),
                    ("golden_coverage_ratio_mean", _metric(before, after, "golden_coverage_ratio_mean")),
                )
                if v is not None
            }

        report["regressions"] = {
            "baseline": str(baseline_path),
            "by_backend": diffs,
        }
    elif bool(args.strict):
        report["strict_gate"] = {
            "enabled": True,
            "passed": False,
            "reason": "baseline_required",
            "failures": ["strict mode requires --baseline to exist"],
        }
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[parser-benchmark] wrote {out_path}")
        print("[parser-benchmark] strict gate failed: baseline_required")
        return 2

    if bool(args.strict):
        baseline_summary = (
            (baseline_obj.get("summary") if isinstance(baseline_obj, dict) else {})
            if baseline_path and baseline_path.exists()
            else {}
        )
        baseline_summary = baseline_summary if isinstance(baseline_summary, dict) else {}
        strict_result = evaluate_strict_regressions(
            current_summary=summary,
            baseline_summary=baseline_summary,
            max_drop_by_metric={
                "ok_rate": float(args.strict_max_ok_rate_drop),
                "parse_score_mean": float(args.strict_max_parse_score_drop),
                "golden_similarity_mean": float(args.strict_max_golden_similarity_drop),
                "golden_coverage_ratio_mean": float(args.strict_max_golden_coverage_drop),
            },
        )
        report["strict_gate"] = {
            "enabled": True,
            "thresholds": {
                "ok_rate": float(args.strict_max_ok_rate_drop),
                "parse_score_mean": float(args.strict_max_parse_score_drop),
                "golden_similarity_mean": float(args.strict_max_golden_similarity_drop),
                "golden_coverage_ratio_mean": float(args.strict_max_golden_coverage_drop),
            },
            "passed": bool(strict_result.get("passed")),
            "failures": list(strict_result.get("failures") or []),
            "by_backend": dict(strict_result.get("by_backend") or {}),
        }

    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[parser-benchmark] wrote {out_path}")
    if bool(args.strict):
        passed = bool(((report.get("strict_gate") or {}).get("passed")))
        if not passed:
            print("[parser-benchmark] strict gate failed")
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
