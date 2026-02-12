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


def _structure_metrics(markdown: str) -> dict[str, Any]:
    md = str(markdown or "")
    return {
        "chars": int(len(md)),
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Parser benchmark harness (golden set optional).")
    ap.add_argument("--input-dir", required=True, help="Directory containing input files (and optional golden markdown files).")
    ap.add_argument("--manifest", default="", help="Optional JSON manifest describing cases + golden markdown paths.")
    ap.add_argument("--out", default="runs/parser_benchmark.json", help="Output JSON path.")
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
        "backends": backends,
        "cases": [],
        "summary": {},
    }

    by_backend: dict[str, dict[str, Any]] = {b: {"attempts": 0, "ok": 0, "elapsed_ms": [], "parse_score": [], "similarity": []} for b in backends}

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

        case_row: dict[str, Any] = {
            "id": case.case_id,
            "path": str(case.path),
            "file_type": file_ext.lstrip("."),
            "golden_markdown_path": str(case.golden_markdown_path) if case.golden_markdown_path else None,
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

                attempt.update(
                    {
                        "ok": True,
                        "resolved_backend": resolved_backend,
                        "provenance": prov,
                        "text_quality": tq,
                        "parse_quality": pq,
                        "structure": _structure_metrics(md),
                    }
                )
                if golden_md:
                    sim = _similarity(md, golden_md)
                    attempt["golden_similarity"] = round(float(sim), 4)
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
        }

    report["summary"] = summary

    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[parser-benchmark] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

