from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    path: Path
    golden_markdown_path: Path | None = None
    golden_specialty_elements: dict[str, int] | None = None
    golden_image_visual_kinds: dict[str, int] | None = None


_HEADING_RE = re.compile(r"(?m)^#{1,6}\s+\S+")
_LIST_ITEM_RE = re.compile(r"(?m)^\s*(?:[-*+]|\d+\.)\s+\S+")
_FENCE_RE = re.compile(r"(?m)^\s*```")
_TABLE_SEP_RE = re.compile(r"(?m)^\s*\|?(?:\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?\s*$")
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_MD_IMAGE_CAPTURE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)")
_HTML_IMG_RE = re.compile(r"(?i)<img\\b[^>]*>")
_HTML_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_HTML_IMG_ATTR_RE = re.compile(r"(src)\s*=\s*([\"'])(.*?)\2", re.IGNORECASE)
_STRICT_PROFILE_SCHEMA_V1 = "mimirq.parser_benchmark_strict_profile.v1"
_SPECIALTY_KINDS = ("seal", "equation", "table", "image")
_IMAGE_VISUAL_KINDS = ("chart", "qr", "barcode", "diagram")


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


def _stable_hash_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()[:24]


def _stable_hash_bytes(data: bytes) -> str:
    return hashlib.sha256(bytes(data or b"")).hexdigest()[:24]


def _stable_hash_file(path: Path) -> str:
    return _stable_hash_bytes(path.read_bytes())


def _stable_hash_obj(obj: Any) -> str:
    return _stable_hash_text(json.dumps(obj, ensure_ascii=False, sort_keys=True))


def _coerce_specialty_elements(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    out: dict[str, int] = {}
    for kind in _SPECIALTY_KINDS:
        raw = value.get(kind)
        if raw is None:
            continue
        try:
            out[kind] = max(0, int(raw))
        except Exception:
            continue
    return out or None


def _coerce_count_map(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    out: dict[str, int] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or "").strip().lower()
        if not key:
            continue
        try:
            out[key] = max(0, int(raw_value))
        except Exception:
            continue
    return out or None


def _load_specialty_payload(input_dir: Path, row: dict[str, Any]) -> dict[str, Any] | None:
    inline = row.get("specialty_elements")
    if isinstance(inline, dict):
        return dict(inline)
    rel = str(row.get("specialty_elements_path") or "").strip()
    if not rel:
        return None
    path = (input_dir / rel).resolve()
    if not path.exists():
        return None
    try:
        payload = json.loads(_read_text(path))
    except Exception:
        return None
    return dict(payload) if isinstance(payload, dict) else None


def _load_specialty_elements(input_dir: Path, row: dict[str, Any]) -> dict[str, int] | None:
    payload = _load_specialty_payload(input_dir, row)
    return _coerce_specialty_elements(payload)


def _load_image_visual_kinds(input_dir: Path, row: dict[str, Any]) -> dict[str, int] | None:
    payload = _load_specialty_payload(input_dir, row)
    return _coerce_count_map((payload or {}).get("image_visual_kinds"))


def _join_documents_to_markdown(documents: Iterable[Any]) -> str:
    parts: list[str] = []
    for d in documents or []:
        parts.append(str(getattr(d, "page_content", "") or ""))
    return "\n\n".join(parts).strip()


def _count_specialty_elements(documents: Iterable[Any]) -> dict[str, int]:
    from app.parsing.utils.document_elements import normalize_document_elements

    counts = {kind: 0 for kind in _SPECIALTY_KINDS}
    for item in normalize_document_elements(documents):
        kind = str((item or {}).get("kind") or "").strip().lower()
        if kind in counts:
            counts[kind] += 1
    return counts


def _count_image_visual_kinds(documents: Iterable[Any]) -> dict[str, int]:
    from app.parsing.utils.document_elements import normalize_document_elements

    counts: dict[str, int] = {}
    for item in normalize_document_elements(documents):
        if str((item or {}).get("kind") or "").strip().lower() != "image":
            continue
        visual_kind = str((item or {}).get("visual_kind") or "").strip().lower()
        if not visual_kind:
            continue
        counts[visual_kind] = int(counts.get(visual_kind, 0) or 0) + 1
    return counts


def _build_fixture_hash(*, cases: list[BenchmarkCase], manifest_path: Path | None) -> str:
    payload: list[dict[str, Any]] = []
    if manifest_path and manifest_path.exists():
        payload.append(
            {
                "manifest_path": str(manifest_path),
                "manifest_hash": _stable_hash_file(manifest_path),
            }
        )

    for case in cases:
        case_root = case.path.parent.parent if case.path.parent.name in {"input", "golden"} else case.path.parent
        case_files: list[dict[str, Any]] = []
        if case_root.exists():
            for item in sorted(case_root.rglob("*")):
                if not item.is_file():
                    continue
                case_files.append(
                    {
                        "path": str(item.relative_to(case_root)),
                        "hash": _stable_hash_file(item),
                    }
                )
        row: dict[str, Any] = {
            "id": str(case.case_id),
            "path": str(case.path),
            "path_hash": _stable_hash_file(case.path) if case.path.exists() else None,
            "golden_markdown_path": (str(case.golden_markdown_path) if case.golden_markdown_path else None),
            "golden_markdown_hash": (
                _stable_hash_file(case.golden_markdown_path)
                if case.golden_markdown_path and case.golden_markdown_path.exists()
                else None
            ),
            "golden_specialty_elements": dict(case.golden_specialty_elements or {}) if isinstance(case.golden_specialty_elements, dict) else None,
            "golden_image_visual_kinds": dict(case.golden_image_visual_kinds or {}) if isinstance(case.golden_image_visual_kinds, dict) else None,
            "case_root": str(case_root),
            "case_files": case_files,
        }
        payload.append(row)
    return _stable_hash_obj(payload)


def _build_profile_hash(
    *,
    strict_profile: dict[str, Any] | None,
    strict_thresholds: dict[str, float],
    backends: list[str],
    max_files: int,
) -> str:
    payload = {
        "strict_profile": dict(strict_profile or {}) if isinstance(strict_profile, dict) else {},
        "strict_thresholds": dict(strict_thresholds or {}),
        "backends": list(backends or []),
        "max_files": int(max_files or 0),
    }
    return _stable_hash_obj(payload)


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
        "image_refs": int(len(_MD_IMAGE_RE.findall(md)) + len(_HTML_IMG_RE.findall(md))),
    }


def _find_missing_local_markdown_assets(markdown_path: Path | None) -> list[str]:
    if markdown_path is None or not markdown_path.exists():
        return []
    text = _read_text(markdown_path)
    missing: list[str] = []
    refs: list[str] = list(_MD_IMAGE_CAPTURE_RE.findall(text))
    for tag in _HTML_IMG_TAG_RE.findall(text):
        for key, _q, val in _HTML_IMG_ATTR_RE.findall(tag):
            if str(key or "").strip().lower() == "src":
                refs.append(str(val or ""))

    for raw_ref in refs:
        ref = str(raw_ref or "").strip()
        if not ref or ref.startswith(("http://", "https://", "data:")):
            continue
        candidate = (markdown_path.parent / ref).resolve()
        if not candidate.exists():
            missing.append(ref)
    return sorted(set(missing))


def _similarity(a: str, b: str) -> float:
    aa = _markdown_to_plain_text(a)
    bb = _markdown_to_plain_text(b)
    if not aa and not bb:
        return 1.0
    if not aa or not bb:
        return 0.0
    return float(difflib.SequenceMatcher(None, aa, bb).ratio())


def _load_cases(input_dir: Path, *, manifest_path: Path | None, max_files: int) -> list[BenchmarkCase]:
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
            cases.append(
                BenchmarkCase(
                    case_id=cid,
                    path=src,
                    golden_markdown_path=golden,
                    golden_specialty_elements=_load_specialty_elements(input_dir, row),
                    golden_image_visual_kinds=_load_image_visual_kinds(input_dir, row),
                )
            )
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


def evaluate_baseline_compatibility(
    *,
    current_report: dict[str, Any],
    baseline_report: dict[str, Any],
) -> dict[str, Any]:
    mismatches: list[str] = []
    for key in ("fixture_hash", "profile_hash"):
        current = str((current_report or {}).get(key) or "").strip()
        baseline = str((baseline_report or {}).get(key) or "").strip()
        if not current or not baseline:
            continue
        if current != baseline:
            mismatches.append(f"{key} mismatch (current={current}, baseline={baseline})")
    return {"compatible": bool(len(mismatches) == 0), "mismatches": mismatches}


def load_strict_profile(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    if not path.exists():
        raise ValueError(f"strict_profile_not_found: {path}")
    obj = json.loads(_read_text(path))
    if not isinstance(obj, dict):
        raise ValueError("strict_profile_invalid: expected JSON object")
    schema = str(obj.get("schema") or "").strip()
    if schema != _STRICT_PROFILE_SCHEMA_V1:
        raise ValueError(f"strict_profile_invalid_schema: expected {_STRICT_PROFILE_SCHEMA_V1}, got {schema or '<empty>'}")
    return obj


def resolve_strict_thresholds(
    *,
    args: argparse.Namespace,
    strict_profile: dict[str, Any] | None,
) -> dict[str, float]:
    profile = strict_profile if isinstance(strict_profile, dict) else {}
    raw = profile.get("thresholds")
    raw = raw if isinstance(raw, dict) else {}

    def _pick(metric: str, cli_default: float) -> float:
        v = raw.get(metric)
        if v is None:
            return float(cli_default)
        try:
            return abs(float(v))
        except Exception:
            return float(cli_default)

    return {
        "ok_rate": _pick("ok_rate", float(args.strict_max_ok_rate_drop)),
        "parse_score_mean": _pick("parse_score_mean", float(args.strict_max_parse_score_drop)),
        "golden_similarity_mean": _pick("golden_similarity_mean", float(args.strict_max_golden_similarity_drop)),
        "golden_coverage_ratio_mean": _pick("golden_coverage_ratio_mean", float(args.strict_max_golden_coverage_drop)),
        "golden_image_ref_recall_mean": _pick("golden_image_ref_recall_mean", float(args.strict_max_golden_image_ref_recall_drop)),
        "mean_seal_recall": _pick("mean_seal_recall", float(args.strict_max_seal_recall_drop)),
        "mean_equation_recall": _pick("mean_equation_recall", float(args.strict_max_equation_recall_drop)),
        "mean_table_recall": _pick("mean_table_recall", float(args.strict_max_table_recall_drop)),
        "mean_image_recall": _pick("mean_image_recall", float(args.strict_max_image_recall_drop)),
        "mean_chart_image_recall": _pick("mean_chart_image_recall", float(args.strict_max_chart_image_recall_drop)),
        "mean_qr_image_recall": _pick("mean_qr_image_recall", float(args.strict_max_qr_image_recall_drop)),
        "mean_barcode_image_recall": _pick("mean_barcode_image_recall", float(args.strict_max_barcode_image_recall_drop)),
        "mean_diagram_image_recall": _pick("mean_diagram_image_recall", float(args.strict_max_diagram_image_recall_drop)),
    }


def build_regression_severity_summary(
    *,
    current_summary: dict[str, Any],
    baseline_summary: dict[str, Any],
    max_drop_by_metric: dict[str, float],
    severity_bands: dict[str, float] | None = None,
) -> dict[str, Any]:
    bands_raw = severity_bands if isinstance(severity_bands, dict) else {}

    def _band(name: str, default: float) -> float:
        try:
            return max(0.0, float(bands_raw.get(name, default)))
        except Exception:
            return float(default)

    critical_at = _band("critical", 3.0)
    high_at = _band("high", 1.5)
    medium_at = _band("medium", 1.0)
    low_at = _band("low", 0.5)
    # Keep monotonic thresholds.
    critical_at = max(critical_at, high_at, medium_at, low_at)
    high_at = max(high_at, medium_at, low_at)
    medium_at = max(medium_at, low_at)

    items: list[dict[str, Any]] = []
    levels = {"critical": 0, "high": 0, "medium": 0, "low": 0}

    for backend, after in (current_summary or {}).items():
        if not isinstance(after, dict):
            continue
        before = baseline_summary.get(backend)
        if not isinstance(before, dict):
            continue
        for metric, max_drop in (max_drop_by_metric or {}).items():
            try:
                allowed = abs(float(max_drop))
            except Exception:
                continue
            if allowed <= 0:
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
            if delta >= 0.0:
                continue
            ratio = abs(delta) / allowed

            level = None
            if ratio >= critical_at:
                level = "critical"
            elif ratio >= high_at:
                level = "high"
            elif ratio >= medium_at:
                level = "medium"
            elif ratio >= low_at:
                level = "low"
            if level is None:
                continue

            levels[level] = int(levels.get(level, 0) or 0) + 1
            items.append(
                {
                    "backend": str(backend),
                    "metric": str(metric),
                    "before": b,
                    "after": a,
                    "delta": round(delta, 6),
                    "max_drop": round(float(allowed), 6),
                    "ratio": round(float(ratio), 6),
                    "level": str(level),
                }
            )

    items.sort(key=lambda row: (-float(row.get("ratio") or 0.0), str(row.get("backend") or ""), str(row.get("metric") or "")))
    return {
        "schema": "mimirq.parser_benchmark_regression_severity.v1",
        "levels": {k: int(levels.get(k, 0) or 0) for k in ("critical", "high", "medium", "low")},
        "items": items[:200],
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
    ap.add_argument(
        "--strict-max-golden-image-ref-recall-drop",
        type=float,
        default=0.05,
        help="Allowed maximum drop for summary.<backend>.golden_image_ref_recall_mean under --strict.",
    )
    ap.add_argument(
        "--strict-max-seal-recall-drop",
        type=float,
        default=0.10,
        help="Allowed maximum drop for summary.<backend>.mean_seal_recall under --strict.",
    )
    ap.add_argument(
        "--strict-max-equation-recall-drop",
        type=float,
        default=0.10,
        help="Allowed maximum drop for summary.<backend>.mean_equation_recall under --strict.",
    )
    ap.add_argument(
        "--strict-max-table-recall-drop",
        type=float,
        default=0.10,
        help="Allowed maximum drop for summary.<backend>.mean_table_recall under --strict.",
    )
    ap.add_argument(
        "--strict-max-image-recall-drop",
        type=float,
        default=0.10,
        help="Allowed maximum drop for summary.<backend>.mean_image_recall under --strict.",
    )
    ap.add_argument(
        "--strict-max-chart-image-recall-drop",
        type=float,
        default=0.10,
        help="Allowed maximum drop for summary.<backend>.mean_chart_image_recall under --strict.",
    )
    ap.add_argument(
        "--strict-max-qr-image-recall-drop",
        type=float,
        default=0.10,
        help="Allowed maximum drop for summary.<backend>.mean_qr_image_recall under --strict.",
    )
    ap.add_argument(
        "--strict-max-barcode-image-recall-drop",
        type=float,
        default=0.10,
        help="Allowed maximum drop for summary.<backend>.mean_barcode_image_recall under --strict.",
    )
    ap.add_argument(
        "--strict-max-diagram-image-recall-drop",
        type=float,
        default=0.10,
        help="Allowed maximum drop for summary.<backend>.mean_diagram_image_recall under --strict.",
    )
    ap.add_argument(
        "--strict-profile",
        default="",
        help=(
            "Optional strict profile JSON (schema: mimirq.parser_benchmark_strict_profile.v1). "
            "When set, threshold values are loaded from profile.thresholds."
        ),
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
    strict_profile_path = Path(str(args.strict_profile)).resolve() if str(args.strict_profile or "").strip() else None
    strict_profile = load_strict_profile(strict_profile_path) if strict_profile_path else {}
    strict_thresholds = resolve_strict_thresholds(args=args, strict_profile=strict_profile)
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
        "strict_profile": str(strict_profile_path) if strict_profile_path else None,
        "fixture_hash": _build_fixture_hash(cases=cases, manifest_path=manifest_path),
        "profile_hash": _build_profile_hash(
            strict_profile=(strict_profile if isinstance(strict_profile, dict) else {}),
            strict_thresholds=strict_thresholds,
            backends=backends,
            max_files=int(args.max_files or 0),
        ),
        "backends": backends,
        "fixture_issues": [],
        "cases": [],
        "summary": {},
    }

    by_backend: dict[str, dict[str, Any]] = {
        b: {
            "attempts": 0,
            "ok": 0,
            "elapsed_ms": [],
            "parse_score": [],
            "similarity": [],
            "coverage_ratio": [],
            "image_ref_recall": [],
            "specialty_recall": {kind: [] for kind in _SPECIALTY_KINDS},
            "specialty_image_visual_kind_recall": {},
        }
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
        golden_image_refs = int(golden_struct.get("image_refs") or 0) if isinstance(golden_struct, dict) else 0
        golden_specialty = dict(case.golden_specialty_elements or {}) if isinstance(case.golden_specialty_elements, dict) else None
        golden_image_visual_kinds = (
            dict(case.golden_image_visual_kinds or {}) if isinstance(case.golden_image_visual_kinds, dict) else None
        )
        missing_input_assets = _find_missing_local_markdown_assets(case.path)
        missing_local_assets = _find_missing_local_markdown_assets(case.golden_markdown_path)

        case_row: dict[str, Any] = {
            "id": case.case_id,
            "path": str(case.path),
            "file_type": file_ext.lstrip("."),
            "input_missing_local_assets": missing_input_assets or None,
            "golden_markdown_path": str(case.golden_markdown_path) if case.golden_markdown_path else None,
            "golden": (
                {
                    "structure": golden_struct,
                    "specialty_elements": golden_specialty,
                    "image_visual_kinds": golden_image_visual_kinds,
                    "missing_local_assets": missing_local_assets or None,
                }
                if golden_struct or golden_specialty or golden_image_visual_kinds
                else None
            ),
            "attempts": [],
        }
        if missing_input_assets:
            report["fixture_issues"].append(
                {
                    "case_id": str(case.case_id),
                    "type": "missing_local_assets",
                    "stage": "input",
                    "items": list(missing_input_assets),
                }
            )
        if missing_local_assets:
            report["fixture_issues"].append(
                {
                    "case_id": str(case.case_id),
                    "type": "missing_local_assets",
                    "stage": "golden",
                    "items": list(missing_local_assets),
                }
            )

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
                specialty_counts = _count_specialty_elements(docs)
                image_visual_kind_counts = _count_image_visual_kinds(docs)

                attempt.update(
                    {
                        "ok": True,
                        "resolved_backend": resolved_backend,
                        "provenance": prov,
                        "text_quality": tq,
                        "parse_quality": pq,
                        "structure": struct,
                        "specialty_elements": specialty_counts,
                        "specialty_image_visual_kinds": image_visual_kind_counts,
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
                    if golden_image_refs > 0:
                        img_recall = float(struct.get("image_refs") or 0) / float(golden_image_refs)
                        attempt["golden_image_ref_recall"] = round(float(img_recall), 4)
                        by_backend[backend]["image_ref_recall"].append(float(img_recall))
                if golden_specialty:
                    specialty_recall: dict[str, float] = {}
                    for kind in _SPECIALTY_KINDS:
                        golden_count = int(golden_specialty.get(kind) or 0)
                        if golden_count <= 0:
                            continue
                        recall = min(float(specialty_counts.get(kind) or 0) / float(golden_count), 1.0)
                        specialty_recall[kind] = round(float(recall), 4)
                        by_backend[backend]["specialty_recall"][kind].append(float(recall))
                    if specialty_recall:
                        attempt["specialty_recall"] = specialty_recall
                if golden_image_visual_kinds:
                    subtype_recall: dict[str, float] = {}
                    subtype_stats = by_backend[backend]["specialty_image_visual_kind_recall"]
                    if not isinstance(subtype_stats, dict):
                        subtype_stats = {}
                        by_backend[backend]["specialty_image_visual_kind_recall"] = subtype_stats
                    for visual_kind, golden_count in golden_image_visual_kinds.items():
                        count = int(golden_count or 0)
                        if count <= 0:
                            continue
                        recall = min(float(image_visual_kind_counts.get(visual_kind) or 0) / float(count), 1.0)
                        subtype_recall[visual_kind] = round(float(recall), 4)
                        subtype_stats.setdefault(visual_kind, []).append(float(recall))
                    if subtype_recall:
                        attempt["specialty_image_visual_kind_recall"] = subtype_recall

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
        img_recalls = [float(x) for x in stats.get("image_ref_recall") or []]
        specialty_recalls = stats.get("specialty_recall") if isinstance(stats.get("specialty_recall"), dict) else {}
        image_visual_kind_recalls = (
            stats.get("specialty_image_visual_kind_recall") if isinstance(stats.get("specialty_image_visual_kind_recall"), dict) else {}
        )

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
            "golden_image_ref_recall_mean": (round(sum(img_recalls) / len(img_recalls), 4) if img_recalls else None),
        }
        for kind in _SPECIALTY_KINDS:
            values = specialty_recalls.get(kind) if isinstance(specialty_recalls, dict) else None
            values = [float(x) for x in values] if isinstance(values, list) else []
            summary[backend][f"mean_{kind}_recall"] = (round(sum(values) / len(values), 4) if values else None)
        subtype_summary: dict[str, float] = {}
        for visual_kind, values in (image_visual_kind_recalls or {}).items():
            numeric = [float(x) for x in values] if isinstance(values, list) else []
            if not numeric:
                continue
            subtype_summary[str(visual_kind)] = round(sum(numeric) / len(numeric), 4)
        if subtype_summary:
            summary[backend]["mean_image_visual_kind_recall"] = subtype_summary
        for visual_kind in _IMAGE_VISUAL_KINDS:
            value = subtype_summary.get(visual_kind) if isinstance(subtype_summary, dict) else None
            summary[backend][f"mean_{visual_kind}_image_recall"] = value if value is not None else None

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
                    ("golden_image_ref_recall_mean", _metric(before, after, "golden_image_ref_recall_mean")),
                    ("mean_seal_recall", _metric(before, after, "mean_seal_recall")),
                    ("mean_equation_recall", _metric(before, after, "mean_equation_recall")),
                    ("mean_table_recall", _metric(before, after, "mean_table_recall")),
                    ("mean_image_recall", _metric(before, after, "mean_image_recall")),
                    ("mean_chart_image_recall", _metric(before, after, "mean_chart_image_recall")),
                    ("mean_qr_image_recall", _metric(before, after, "mean_qr_image_recall")),
                    ("mean_barcode_image_recall", _metric(before, after, "mean_barcode_image_recall")),
                    ("mean_diagram_image_recall", _metric(before, after, "mean_diagram_image_recall")),
                )
                if v is not None
            }

        report["regressions"] = {
            "baseline": str(baseline_path),
            "compatibility": evaluate_baseline_compatibility(current_report=report, baseline_report=baseline_obj),
            "by_backend": diffs,
        }
        severity_bands = strict_profile.get("severity_bands") if isinstance(strict_profile, dict) else {}
        report["regression_severity"] = build_regression_severity_summary(
            current_summary=summary,
            baseline_summary=baseline_summary,
            max_drop_by_metric=strict_thresholds,
            severity_bands=(severity_bands if isinstance(severity_bands, dict) else None),
        )
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
            max_drop_by_metric=strict_thresholds,
        )
        compatibility = evaluate_baseline_compatibility(current_report=report, baseline_report=baseline_obj)
        compatibility_mismatches = list(compatibility.get("mismatches") or [])
        fixture_issue_failures = [
            f"{str(item.get('case_id') or 'unknown')}: missing_local_assets -> {', '.join(str(x) for x in (item.get('items') or []))}"
            for item in list(report.get("fixture_issues") or [])
            if str(item.get("type") or "") == "missing_local_assets"
        ]
        passed = bool(strict_result.get("passed")) and len(compatibility_mismatches) == 0 and len(fixture_issue_failures) == 0
        failures = list(strict_result.get("failures") or []) + compatibility_mismatches + fixture_issue_failures
        report["strict_gate"] = {
            "enabled": True,
            "thresholds": dict(strict_thresholds or {}),
            "passed": passed,
            "failures": failures,
            "by_backend": dict(strict_result.get("by_backend") or {}),
            "compatibility": compatibility,
            "fixture_issues": list(report.get("fixture_issues") or []),
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
