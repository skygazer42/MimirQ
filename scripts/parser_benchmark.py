import argparse
import difflib
import hashlib
import json
import math
import re
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.parsing.quality.grits import compute_table_collection_grits  # noqa: E402


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    path: Path
    golden_markdown_path: Path | None = None
    golden_specialty_elements: dict[str, int] | None = None
    golden_image_visual_kinds: dict[str, int] | None = None
    golden_image_code_values: dict[str, list[str]] | None = None
    golden_table_continuity: dict[str, Any] | None = None
    governance_rule_packs: list[str] | None = None


@dataclass(frozen=True, slots=True)
class RunConfig:
    args: argparse.Namespace
    input_dir: Path
    manifest_path: Path | None
    baseline_path: Path | None
    strict_profile_path: Path | None
    strict_profile: dict[str, Any]
    strict_thresholds: dict[str, float]
    out_path: Path
    backends: list[str]
    cases: list[BenchmarkCase]


@dataclass(frozen=True, slots=True)
class BenchmarkDependencies:
    parser_factory: Any
    merge_cross_page_documents: Any
    score_document_parse_quality: Any
    score_pdf_quality: Any
    score_parsed_text_quality: Any


@dataclass(frozen=True, slots=True)
class CaseGoldenData:
    markdown: str
    structure: dict[str, Any] | None
    plain_chars: int
    image_refs: int
    specialty: dict[str, Any] | None
    image_visual_kinds: dict[str, Any] | None
    image_code_values: dict[str, Any] | None
    table_continuity: dict[str, Any] | None
    missing_input_assets: list[str]
    missing_local_assets: list[str]


_HEADING_RE = re.compile(r"(?m)^#{1,6}\s+\S+")
_LIST_ITEM_RE = re.compile(r"(?m)^\s*(?:[-*+]|\d+\.)\s+\S+")
_FENCE_RE = re.compile(r"(?m)^\s*```")
_TABLE_SEP_RE = re.compile(r"(?m)^\s*\|?(?:\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?\s*$")
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_MD_IMAGE_CAPTURE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)")
_HTML_IMG_RE = re.compile(r"(?i)<img\\b[^>]*>")
_HTML_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_HTML_IMG_ATTR_RE = re.compile(r"(src)\s*=\s*([\"'])(.*?)\2", re.IGNORECASE)
_POSITION_TAG_INLINE_RE = re.compile(r"@@[0-9-]+\t[0-9.]+\t[0-9.]+\t[0-9.]+\t[0-9.]+##")
_STRICT_PROFILE_SCHEMA_V1 = "mimirq.parser_benchmark_strict_profile.v1"
_SPECIALTY_KINDS = ("seal", "equation", "table", "image")
_IMAGE_VISUAL_KINDS = ("chart", "qr", "barcode", "diagram")
_STRICT_THRESHOLD_FIELDS = (
    ("ok_rate", "strict_max_ok_rate_drop"),
    ("parse_score_mean", "strict_max_parse_score_drop"),
    ("golden_similarity_mean", "strict_max_golden_similarity_drop"),
    ("golden_coverage_ratio_mean", "strict_max_golden_coverage_drop"),
    ("golden_image_ref_recall_mean", "strict_max_golden_image_ref_recall_drop"),
    ("mean_seal_recall", "strict_max_seal_recall_drop"),
    ("mean_equation_recall", "strict_max_equation_recall_drop"),
    ("mean_table_recall", "strict_max_table_recall_drop"),
    ("mean_image_recall", "strict_max_image_recall_drop"),
    ("mean_chart_image_recall", "strict_max_chart_image_recall_drop"),
    ("mean_qr_image_recall", "strict_max_qr_image_recall_drop"),
    ("mean_barcode_image_recall", "strict_max_barcode_image_recall_drop"),
    ("mean_diagram_image_recall", "strict_max_diagram_image_recall_drop"),
    ("mean_qr_code_value_recall", "strict_max_qr_code_value_recall_drop"),
    ("mean_barcode_code_value_recall", "strict_max_barcode_code_value_recall_drop"),
)
_BASELINE_REGRESSION_METRICS = (
    "ok_rate",
    "elapsed_ms_p50",
    "elapsed_ms_p90",
    "parse_score_mean",
    "golden_similarity_mean",
    "golden_coverage_ratio_mean",
    "golden_image_ref_recall_mean",
    "mean_seal_recall",
    "mean_equation_recall",
    "mean_table_recall",
    "mean_image_recall",
    "mean_chart_image_recall",
    "mean_qr_image_recall",
    "mean_barcode_image_recall",
    "mean_diagram_image_recall",
    "mean_qr_code_value_recall",
    "mean_barcode_code_value_recall",
)


def _dict_copy_or_none(value: Any) -> dict[str, Any] | None:
    return dict(value or {}) if isinstance(value, dict) else None


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _average_or_none(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _nested_metric_map(value: Any) -> dict[str, list[float]]:
    return value if isinstance(value, dict) else {}


def _image_source_content_type(item: dict[str, Any]) -> str:
    attributes = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
    return str((attributes or {}).get("source_content_type") or "").strip().lower()


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


def _stable_path_id(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


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


def _load_image_code_values(input_dir: Path, row: dict[str, Any]) -> dict[str, list[str]] | None:
    payload = _load_specialty_payload(input_dir, row)
    raw = (payload or {}).get("image_code_values")
    if not isinstance(raw, dict):
        return None
    out: dict[str, list[str]] = {}
    for raw_key, raw_values in raw.items():
        key = str(raw_key or "").strip().lower()
        if not key or not isinstance(raw_values, list):
            continue
        values = [str(item).strip() for item in raw_values if str(item).strip()]
        if values:
            out[key] = values
    return out or None


def _load_table_continuity(input_dir: Path, row: dict[str, Any]) -> dict[str, Any] | None:
    payload = _load_specialty_payload(input_dir, row)
    raw = (payload or {}).get("table_continuity")
    if not isinstance(raw, dict):
        return None
    header = str(raw.get("header") or "").strip()
    rows = raw.get("rows")
    header_occurrences = raw.get("header_occurrences")
    out: dict[str, Any] = {}
    if header:
        out["header"] = header
    try:
        if rows is not None:
            out["rows"] = max(0, int(rows))
    except Exception:
        pass
    try:
        if header_occurrences is not None:
            out["header_occurrences"] = max(0, int(header_occurrences))
    except Exception:
        pass
    return out or None


def _load_governance_rule_packs(row: dict[str, Any]) -> list[str] | None:
    raw = row.get("governance_rule_packs")
    if not isinstance(raw, list):
        return None
    out = [str(item).strip() for item in raw if str(item).strip()]
    return out or None


def _apply_governance_cleaning(*, markdown: str, governance_rule_packs: list[str] | None) -> str:
    packs = [str(item).strip() for item in (governance_rule_packs or []) if str(item).strip()]
    if not packs:
        return str(markdown or "")

    from app.rag.preprocessing.cleaning import clean_markdown
    from app.rag.preprocessing.rules import build_governance_rules

    result = clean_markdown(
        str(markdown or ""),
        rules=build_governance_rules([], rule_packs=packs),
        remove_toc_lines=False,
        remove_noise_lines=False,
        unwrap_lines=False,
        remove_common_lines=False,
        collapse_blank_lines=True,
    )
    return str(result.markdown or markdown or "")


def _join_documents_to_markdown(documents: Iterable[Any]) -> str:
    parts: list[str] = []
    saw_image_ref = False
    for d in documents or []:
        text = str(getattr(d, "page_content", "") or "")
        if _MD_IMAGE_RE.search(text) or _HTML_IMG_RE.search(text):
            saw_image_ref = True
        meta = getattr(d, "metadata", None)
        if isinstance(meta, dict):
            doc_type = str(meta.get("doc_type_kwd") or meta.get("content_type") or "").strip().lower()
            has_image_ref = bool(_MD_IMAGE_RE.search(text) or _HTML_IMG_RE.search(text))
            if doc_type == "image" and not has_image_ref and not saw_image_ref:
                visual_kind = str(meta.get("visual_kind") or "").strip().lower() or "image"
                page = str(meta.get("page") or "na").strip() or "na"
                image_index = str(meta.get("image_index") or 0).strip() or "0"
                synthetic_ref = f"embedded-page-{page}-image-{image_index}.png"
                text = f"![{visual_kind}]({synthetic_ref})" + (f"\n\n{text}" if text else "")
                saw_image_ref = True
        parts.append(text)
    return "\n\n".join(parts).strip()


def _table_continuity_recall(*, golden_markdown: str, parsed_markdown: str) -> float | None:
    golden_blocks = _extract_markdown_table_blocks(golden_markdown)
    if not golden_blocks:
        return None
    target = golden_blocks[0]
    expectation = {
        "header": str(target[0] or "").strip() if target else "",
        "rows": max(0, len(target) - 2) if len(target) >= 2 else 0,
        "header_occurrences": 1,
    }
    return _score_table_continuity(parsed_markdown, expectation)


def _reading_order_score(markdown: str) -> float | None:
    from app.parsing.quality.reading_order import score_reading_order

    result = score_reading_order(markdown)
    if not isinstance(result, dict):
        return None
    raw = result.get("score")
    try:
        return None if raw is None else round(float(raw), 4)
    except Exception:
        return None


def _count_specialty_elements(documents: Iterable[Any]) -> dict[str, int]:
    from app.parsing.utils.document_elements import normalize_document_elements

    counts = {kind: 0 for kind in _SPECIALTY_KINDS}
    for item in normalize_document_elements(documents):
        kind = str((item or {}).get("kind") or "").strip().lower()
        if kind in counts:
            counts[kind] += 1
    return counts


def _count_image_visual_kinds(documents: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in _benchmark_image_elements(documents):
        visual_kind = str((item or {}).get("visual_kind") or "").strip().lower()
        if not visual_kind:
            continue
        counts[visual_kind] = int(counts.get(visual_kind, 0) or 0) + 1
    return counts


def _collect_image_code_values(documents: Iterable[Any]) -> dict[str, list[str]]:
    values_by_kind: dict[str, list[str]] = {}
    for item in _benchmark_image_elements(documents):
        visual_kind = str((item or {}).get("visual_kind") or "").strip().lower()
        text = str((item or {}).get("text") or "").strip()
        if visual_kind not in {"qr", "barcode"} or not text:
            continue
        bucket = values_by_kind.setdefault(visual_kind, [])
        if text not in bucket:
            bucket.append(text)
    return values_by_kind


def _benchmark_image_elements(documents: Iterable[Any]) -> list[dict[str, Any]]:
    from app.parsing.utils.document_elements import normalize_document_elements

    images = [
        dict(item)
        for item in normalize_document_elements(documents)
        if str((item or {}).get("kind") or "").strip().lower() == "image"
    ]
    if not images:
        return []

    grouped: dict[tuple[int | None, str], list[dict[str, Any]]] = {}
    for item in images:
        key = (
            item.get("page") if isinstance(item.get("page"), int) else None,
            str(item.get("visual_kind") or "").strip().lower(),
        )
        grouped.setdefault(key, []).append(item)

    deduped: list[dict[str, Any]] = []
    for group in grouped.values():
        explicit = [item for item in group if _image_source_content_type(item) != "markdown_image"]
        deduped.extend(explicit or group)
    return deduped


def _augment_documents_with_inline_image_codes(*, documents: list[Any], markdown: str, origin_path: Path) -> list[Any]:
    from app.parsing.enrich.image_code import add_image_code_blocks

    try:
        _next_markdown, added, audit = add_image_code_blocks(markdown, origin_path=origin_path)
    except Exception:
        return list(documents or [])
    if int(added or 0) <= 0:
        return list(documents or [])

    derived = list(documents or [])
    existing_signatures: set[tuple[str, str]] = set()
    for item in list(documents or []):
        meta = getattr(item, "metadata", None)
        if not isinstance(meta, dict):
            continue
        if str(meta.get("doc_type_kwd") or meta.get("element_kind") or "").strip().lower() != "image":
            continue
        visual_kind = str(meta.get("visual_kind") or "").strip().lower()
        text = str(meta.get("image_code_text") or getattr(item, "page_content", "") or "").strip()
        if visual_kind and text:
            existing_signatures.add((visual_kind, text))
    for item in list(getattr(audit, "code_elements", None) or []):
        if not isinstance(item, dict):
            continue
        visual_kind = str(item.get("visual_kind") or "").strip().lower()
        text = str(item.get("text") or "").strip()
        if visual_kind and text and (visual_kind, text) in existing_signatures:
            continue
        metadata = {
            "element_kind": str(item.get("kind") or "image"),
            "element_text": str(item.get("text") or ""),
            "element_id": str(item.get("id") or ""),
            "page": item.get("page"),
            "visual_kind": item.get("visual_kind"),
            "element_attributes": dict(item.get("attributes") or {}),
        }
        derived.append(Document(page_content=str(item.get("text") or ""), metadata=metadata))
    return derived


def _augment_markdown_with_inline_image_ocr(*, markdown: str, origin_path: Path) -> str:
    from app.parsing.enrich.image_ocr import add_image_ocr_blocks

    try:
        next_markdown, _added, _audit = add_image_ocr_blocks(markdown, origin_path=origin_path)
    except Exception:
        return str(markdown or "")
    return str(next_markdown or markdown or "")


def _extract_markdown_table_blocks(markdown: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for raw_line in str(markdown or "").splitlines():
        line = _POSITION_TAG_INLINE_RE.sub("", raw_line).rstrip()
        stripped = line.strip()
        is_table_row = stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2
        if is_table_row:
            current.append(stripped)
            continue
        if current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def _table_block_to_grid(block: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for index, line in enumerate(block):
        if index == 1 and _TABLE_SEP_RE.match(line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells:
            rows.append(cells)
    return rows


def _extract_markdown_tables(markdown: str) -> list[list[list[str]]]:
    return [_table_block_to_grid(block) for block in _extract_markdown_table_blocks(markdown) if block]


def _score_table_continuity(markdown: str, expectation: dict[str, Any] | None) -> float | None:
    if not isinstance(expectation, dict):
        return None
    blocks = _extract_markdown_table_blocks(markdown)
    if not blocks:
        return 0.0

    header = str(expectation.get("header") or "").strip()
    expected_rows = expectation.get("rows")
    expected_header_occurrences = expectation.get("header_occurrences")

    target = blocks[0]
    if header:
        for block in blocks:
            if block and block[0] == header:
                target = block
                break

    scores: list[float] = []
    if header:
        actual_occurrences = str(markdown or "").count(header)
        target_occurrences = max(1, int(expected_header_occurrences or 1))
        header_score = 1.0 if actual_occurrences == target_occurrences else 0.0
        scores.append(float(header_score))

    try:
        expected_rows_i = max(0, int(expected_rows))
    except Exception:
        expected_rows_i = 0
    if expected_rows_i > 0:
        actual_rows = max(0, len(target) - 2) if len(target) >= 2 else 0
        row_score = min(float(actual_rows) / float(expected_rows_i), 1.0)
        scores.append(float(row_score))

    scores.append(1.0 if target else 0.0)
    return round(sum(scores) / float(len(scores)), 4) if scores else None


def _build_fixture_hash(*, cases: list[BenchmarkCase], manifest_path: Path | None) -> str:
    payload: list[dict[str, Any]] = []
    if manifest_path and manifest_path.exists():
        payload.append(
            {
                "manifest_path": _stable_path_id(manifest_path),
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
            "path": _stable_path_id(case.path),
            "path_hash": _stable_hash_file(case.path) if case.path.exists() else None,
            "golden_markdown_path": (_stable_path_id(case.golden_markdown_path) if case.golden_markdown_path else None),
            "golden_markdown_hash": (
                _stable_hash_file(case.golden_markdown_path)
                if case.golden_markdown_path and case.golden_markdown_path.exists()
                else None
            ),
            "golden_specialty_elements": _dict_copy_or_none(case.golden_specialty_elements),
            "golden_image_visual_kinds": _dict_copy_or_none(case.golden_image_visual_kinds),
            "golden_image_code_values": _dict_copy_or_none(case.golden_image_code_values),
            "governance_rule_packs": list(case.governance_rule_packs or []),
            "case_root": _stable_path_id(case_root),
            "case_files": case_files,
        }
        if isinstance(case.golden_table_continuity, dict) and case.golden_table_continuity:
            row["golden_table_continuity"] = dict(case.golden_table_continuity or {})
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
    s = _POSITION_TAG_INLINE_RE.sub("", s)
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
                    golden_image_code_values=_load_image_code_values(input_dir, row),
                    golden_table_continuity=_load_table_continuity(input_dir, row),
                    governance_rule_packs=_load_governance_rule_packs(row),
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


def _resolve_regression_metrics(
    *,
    max_drop_by_metric: dict[str, float],
    failures: list[str],
) -> list[tuple[str, float]]:
    metrics: list[tuple[str, float]] = []
    for raw_metric, max_drop in (max_drop_by_metric or {}).items():
        metric = str(raw_metric).strip()
        if not metric:
            continue
        allowed_drop = _finite_float(abs(float(max_drop)) if _finite_float(max_drop) is not None else None)
        if allowed_drop is None:
            failures.append(f"{metric} has a non-numeric maximum drop")
            continue
        metrics.append((metric, allowed_drop))
    return metrics


def _missing_regression_metric_failure(
    *,
    metric: str,
    before: Any,
    after: Any,
    reason: str,
) -> dict[str, Any]:
    return {
        "metric": metric,
        "before": before,
        "after": after,
        "reason": reason,
    }


def _evaluate_regression_metric(
    *,
    backend: str,
    metric: str,
    allowed_drop: float,
    before: dict[str, Any],
    after: dict[str, Any],
    failures: list[str],
) -> dict[str, Any] | None:
    baseline_value = before.get(metric)
    current_value = after.get(metric)
    if baseline_value is None:
        failures.append(f"{backend}.{metric} is missing from the baseline summary")
        return _missing_regression_metric_failure(
            metric=metric,
            before=None,
            after=current_value,
            reason="missing_baseline_metric",
        )
    if current_value is None:
        failures.append(f"{backend}.{metric} is missing from the current summary")
        return _missing_regression_metric_failure(
            metric=metric,
            before=baseline_value,
            after=None,
            reason="missing_metric",
        )

    baseline_number = _finite_float(baseline_value)
    if baseline_number is None:
        failures.append(f"{backend}.{metric} has a non-numeric baseline value")
        return _missing_regression_metric_failure(
            metric=metric,
            before=baseline_value,
            after=current_value,
            reason="invalid_baseline_metric",
        )

    current_number = _finite_float(current_value)
    if current_number is None:
        failures.append(f"{backend}.{metric} has a non-numeric current value")
        return _missing_regression_metric_failure(
            metric=metric,
            before=baseline_value,
            after=current_value,
            reason="invalid_current_metric",
        )

    delta = float(current_number - baseline_number)
    if delta >= (0.0 - allowed_drop):
        return None
    failures.append(
        f"{backend}.{metric} regressed by {delta:.4f} "
        f"(before={baseline_number:.4f}, after={current_number:.4f}, "
        f"allowed_drop={allowed_drop:.4f})"
    )
    return {
        "metric": metric,
        "before": baseline_number,
        "after": current_number,
        "delta": round(delta, 6),
        "max_drop": allowed_drop,
    }


def _evaluate_backend_regressions(
    *,
    backend: str,
    before: dict[str, Any],
    after: dict[str, Any],
    metrics: list[tuple[str, float]],
    failures: list[str],
) -> list[dict[str, Any]]:
    backend_failures: list[dict[str, Any]] = []
    for metric, allowed_drop in metrics:
        failure = _evaluate_regression_metric(
            backend=backend,
            metric=metric,
            allowed_drop=allowed_drop,
            before=before,
            after=after,
            failures=failures,
        )
        if failure is not None:
            backend_failures.append(failure)
    return backend_failures


def _resolve_severity_thresholds(severity_bands: dict[str, float] | None) -> dict[str, float]:
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
    return {
        "critical": max(critical_at, high_at, medium_at, low_at),
        "high": max(high_at, medium_at, low_at),
        "medium": max(medium_at, low_at),
        "low": low_at,
    }


def _resolve_regression_level(ratio: float, thresholds: dict[str, float]) -> str | None:
    if ratio >= float(thresholds["critical"]):
        return "critical"
    if ratio >= float(thresholds["high"]):
        return "high"
    if ratio >= float(thresholds["medium"]):
        return "medium"
    if ratio >= float(thresholds["low"]):
        return "low"
    return None


def _build_regression_severity_item(
    *,
    backend: str,
    metric: str,
    before: dict[str, Any],
    after: dict[str, Any],
    max_drop: float,
    thresholds: dict[str, float],
) -> dict[str, Any] | None:
    try:
        allowed = abs(float(max_drop))
    except Exception:
        return None
    if allowed <= 0:
        return None
    try:
        baseline_number = float(before.get(metric))
        current_number = float(after.get(metric))
    except Exception:
        return None
    delta = float(current_number - baseline_number)
    if delta >= 0.0:
        return None
    ratio = abs(delta) / allowed
    level = _resolve_regression_level(ratio, thresholds)
    if level is None:
        return None
    return {
        "backend": backend,
        "metric": metric,
        "before": baseline_number,
        "after": current_number,
        "delta": round(delta, 6),
        "max_drop": round(float(allowed), 6),
        "ratio": round(float(ratio), 6),
        "level": level,
    }


def evaluate_strict_regressions(
    *,
    current_summary: dict[str, Any],
    baseline_summary: dict[str, Any],
    max_drop_by_metric: dict[str, float],
) -> dict[str, Any]:
    failures: list[str] = []
    by_backend: dict[str, Any] = {}
    if not baseline_summary:
        return {
            "passed": False,
            "failures": ["baseline summary is missing or empty"],
            "by_backend": {},
        }

    metrics = _resolve_regression_metrics(
        max_drop_by_metric=max_drop_by_metric,
        failures=failures,
    )

    for backend, before in (baseline_summary or {}).items():
        if not isinstance(before, dict):
            failures.append(f"{backend} backend has an invalid baseline summary")
            by_backend[str(backend)] = [{"reason": "invalid_baseline_backend"}]
            continue
        after = current_summary.get(backend)
        if not isinstance(after, dict):
            failures.append(f"{backend} backend is missing from the current summary")
            by_backend[str(backend)] = [{"reason": "missing_backend"}]
            continue

        backend_failures = _evaluate_backend_regressions(
            backend=str(backend),
            before=before,
            after=after,
            metrics=metrics,
            failures=failures,
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
        if not current:
            mismatches.append(f"{key} missing from current report")
            continue
        if not baseline:
            mismatches.append(f"{key} missing from baseline report")
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
        raise ValueError(
            f"strict_profile_invalid_schema: expected {_STRICT_PROFILE_SCHEMA_V1}, got {schema or '<empty>'}"
        )
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

    return {metric: _pick(metric, float(getattr(args, attr_name))) for metric, attr_name in _STRICT_THRESHOLD_FIELDS}


def build_regression_severity_summary(
    *,
    current_summary: dict[str, Any],
    baseline_summary: dict[str, Any],
    max_drop_by_metric: dict[str, float],
    severity_bands: dict[str, float] | None = None,
) -> dict[str, Any]:
    thresholds = _resolve_severity_thresholds(severity_bands)

    items: list[dict[str, Any]] = []
    levels = {"critical": 0, "high": 0, "medium": 0, "low": 0}

    for backend, after in (current_summary or {}).items():
        if not isinstance(after, dict):
            continue
        before = baseline_summary.get(backend)
        if not isinstance(before, dict):
            continue
        for metric, max_drop in (max_drop_by_metric or {}).items():
            item = _build_regression_severity_item(
                backend=str(backend),
                metric=str(metric),
                before=before,
                after=after,
                max_drop=max_drop,
                thresholds=thresholds,
            )
            if item is None:
                continue
            level = str(item.get("level") or "")
            levels[level] = int(levels.get(level, 0) or 0) + 1
            items.append(item)

    items.sort(
        key=lambda row: (
            -float(row.get("ratio") or 0.0),
            str(row.get("backend") or ""),
            str(row.get("metric") or ""),
        )
    )
    return {
        "schema": "mimirq.parser_benchmark_regression_severity.v1",
        "levels": {k: int(levels.get(k, 0) or 0) for k in ("critical", "high", "medium", "low")},
        "items": items[:200],
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Parser benchmark harness (golden set optional).")
    ap.add_argument(
        "--input-dir",
        required=True,
        help="Directory containing input files (and optional golden markdown files).",
    )
    ap.add_argument(
        "--manifest",
        default="",
        help="Optional JSON manifest describing cases + golden markdown paths.",
    )
    ap.add_argument("--out", default="runs/parser_benchmark.json", help="Output JSON path.")
    ap.add_argument(
        "--baseline",
        default="",
        help="Optional previous report JSON to diff against (adds report.regressions).",
    )
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
        "--strict-max-qr-code-value-recall-drop",
        type=float,
        default=0.10,
        help="Allowed maximum drop for summary.<backend>.mean_qr_code_value_recall under --strict.",
    )
    ap.add_argument(
        "--strict-max-barcode-code-value-recall-drop",
        type=float,
        default=0.10,
        help="Allowed maximum drop for summary.<backend>.mean_barcode_code_value_recall under --strict.",
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
    return ap


def _resolve_optional_path(raw_value: Any) -> Path | None:
    raw = str(raw_value or "").strip()
    return Path(raw).resolve() if raw else None


def _resolve_backends(raw_value: Any) -> list[str]:
    return [item.strip().lower() for item in str(raw_value or "").split(",") if item.strip()]


def _build_run_config(args: argparse.Namespace) -> RunConfig:
    input_dir = Path(args.input_dir).resolve()
    if not input_dir.exists():
        raise SystemExit(f"input_dir_not_found: {input_dir}")

    manifest_path = _resolve_optional_path(args.manifest)
    baseline_path = _resolve_optional_path(args.baseline)
    strict_profile_path = _resolve_optional_path(args.strict_profile)
    strict_profile = load_strict_profile(strict_profile_path) if strict_profile_path else {}
    strict_thresholds = resolve_strict_thresholds(args=args, strict_profile=strict_profile)
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    backends = _resolve_backends(args.backends)
    if not backends:
        raise SystemExit("backends_empty")

    cases = _load_cases(
        input_dir,
        manifest_path=manifest_path,
        max_files=int(args.max_files or 0),
    )
    if not cases:
        raise SystemExit("no_cases_found")

    return RunConfig(
        args=args,
        input_dir=input_dir,
        manifest_path=manifest_path,
        baseline_path=baseline_path,
        strict_profile_path=strict_profile_path,
        strict_profile=strict_profile,
        strict_thresholds=strict_thresholds,
        out_path=out_path,
        backends=backends,
        cases=cases,
    )


def _load_benchmark_dependencies() -> BenchmarkDependencies:
    from app.parsing.factory import parser_factory
    from app.parsing.processors.cross_page_merge import merge_cross_page_documents
    from app.parsing.quality.document_quality import score_document_parse_quality
    from app.parsing.quality.scorer import score_pdf_quality
    from app.parsing.quality.text_quality import score_parsed_text_quality

    return BenchmarkDependencies(
        parser_factory=parser_factory,
        merge_cross_page_documents=merge_cross_page_documents,
        score_document_parse_quality=score_document_parse_quality,
        score_pdf_quality=score_pdf_quality,
        score_parsed_text_quality=score_parsed_text_quality,
    )


def _build_report(config: RunConfig, *, started_at: datetime) -> dict[str, Any]:
    return {
        "schema": "mimirq.parser_benchmark.v1",
        "generated_at": started_at.isoformat(),
        "input_dir": str(config.input_dir),
        "manifest": str(config.manifest_path) if config.manifest_path else None,
        "baseline": str(config.baseline_path) if config.baseline_path else None,
        "strict_profile": str(config.strict_profile_path) if config.strict_profile_path else None,
        "fixture_hash": _build_fixture_hash(cases=config.cases, manifest_path=config.manifest_path),
        "profile_hash": _build_profile_hash(
            strict_profile=(config.strict_profile if isinstance(config.strict_profile, dict) else {}),
            strict_thresholds=config.strict_thresholds,
            backends=config.backends,
            max_files=int(config.args.max_files or 0),
        ),
        "backends": config.backends,
        "fixture_issues": [],
        "cases": [],
        "summary": {},
    }


def _build_backend_stats(backends: list[str]) -> dict[str, dict[str, Any]]:
    return {
        backend: {
            "attempts": 0,
            "ok": 0,
            "elapsed_ms": [],
            "parse_score": [],
            "similarity": [],
            "coverage_ratio": [],
            "image_ref_recall": [],
            "table_continuity_recall": [],
            "table_grits_topology": [],
            "table_grits_content": [],
            "table_grits_f1": [],
            "reading_order_score": [],
            "specialty_recall": {kind: [] for kind in _SPECIALTY_KINDS},
            "specialty_image_visual_kind_recall": {},
            "specialty_image_code_value_recall": {},
        }
        for backend in backends
    }


def _score_pdf_quality(case: BenchmarkCase, dependencies: BenchmarkDependencies) -> dict[str, Any] | None:
    if case.path.suffix.lower() != ".pdf":
        return None
    try:
        return dependencies.score_pdf_quality(case.path)
    except Exception:
        return None


def _load_case_golden_data(case: BenchmarkCase) -> CaseGoldenData:
    golden_markdown = ""
    if case.golden_markdown_path and case.golden_markdown_path.exists():
        golden_markdown = _read_text(case.golden_markdown_path)
    golden_structure = _structure_metrics(golden_markdown) if golden_markdown else None
    return CaseGoldenData(
        markdown=golden_markdown,
        structure=golden_structure,
        plain_chars=int(golden_structure.get("plain_chars") or 0) if isinstance(golden_structure, dict) else 0,
        image_refs=int(golden_structure.get("image_refs") or 0) if isinstance(golden_structure, dict) else 0,
        specialty=_dict_copy_or_none(case.golden_specialty_elements),
        image_visual_kinds=_dict_copy_or_none(case.golden_image_visual_kinds),
        image_code_values=_dict_copy_or_none(case.golden_image_code_values),
        table_continuity=_dict_copy_or_none(case.golden_table_continuity),
        missing_input_assets=_find_missing_local_markdown_assets(case.path),
        missing_local_assets=_find_missing_local_markdown_assets(case.golden_markdown_path),
    )


def _golden_case_payload(golden: CaseGoldenData) -> dict[str, Any] | None:
    fields = (
        golden.structure,
        golden.specialty,
        golden.image_visual_kinds,
        golden.image_code_values,
        golden.table_continuity,
    )
    if not any(fields):
        return None
    return {
        "structure": golden.structure,
        "specialty_elements": golden.specialty,
        "image_visual_kinds": golden.image_visual_kinds,
        "image_code_values": golden.image_code_values,
        "table_continuity": golden.table_continuity,
        "missing_local_assets": golden.missing_local_assets or None,
    }


def _build_case_row(case: BenchmarkCase, golden: CaseGoldenData) -> dict[str, Any]:
    return {
        "id": case.case_id,
        "path": str(case.path),
        "file_type": case.path.suffix.lower().lstrip("."),
        "input_missing_local_assets": golden.missing_input_assets or None,
        "golden_markdown_path": str(case.golden_markdown_path) if case.golden_markdown_path else None,
        "golden": _golden_case_payload(golden),
        "attempts": [],
    }


def _append_fixture_issue(
    report: dict[str, Any],
    *,
    case_id: str,
    stage: str,
    items: list[str],
) -> None:
    if not items:
        return
    report["fixture_issues"].append(
        {
            "case_id": case_id,
            "type": "missing_local_assets",
            "stage": stage,
            "items": list(items),
        }
    )


def _record_case_fixture_issues(
    report: dict[str, Any],
    *,
    case: BenchmarkCase,
    golden: CaseGoldenData,
) -> None:
    _append_fixture_issue(
        report,
        case_id=str(case.case_id),
        stage="input",
        items=golden.missing_input_assets,
    )
    _append_fixture_issue(
        report,
        case_id=str(case.case_id),
        stage="golden",
        items=golden.missing_local_assets,
    )


def _parse_case_backend(
    *,
    case: BenchmarkCase,
    backend: str,
    pdf_quality: dict[str, Any] | None,
    dependencies: BenchmarkDependencies,
) -> tuple[dict[str, Any], str, dict[str, Any], list[Any], str]:
    docs, resolved_backend, provenance = dependencies.parser_factory.parse_with_provenance(
        case.path,
        parser_backend=backend,
        pdf_quality=pdf_quality,
    )
    docs = dependencies.merge_cross_page_documents(list(docs or []))
    markdown = _join_documents_to_markdown(docs)
    markdown = _augment_markdown_with_inline_image_ocr(markdown=markdown, origin_path=case.path)
    markdown = _apply_governance_cleaning(
        markdown=markdown,
        governance_rule_packs=case.governance_rule_packs,
    )
    metric_docs = _augment_documents_with_inline_image_codes(
        documents=list(docs or []),
        markdown=markdown,
        origin_path=case.path,
    )
    text_quality = dependencies.score_parsed_text_quality(markdown).to_dict()
    parse_quality = dependencies.score_document_parse_quality(
        pdf_quality=pdf_quality,
        parsed_text_quality=text_quality,
    )
    attempt = {
        "ok": True,
        "resolved_backend": resolved_backend,
        "provenance": provenance,
        "text_quality": text_quality,
        "parse_quality": parse_quality,
        "structure": _structure_metrics(markdown),
        "reading_order_score": _reading_order_score(markdown),
        "specialty_elements": _count_specialty_elements(metric_docs),
        "specialty_image_visual_kinds": _count_image_visual_kinds(metric_docs),
        "specialty_image_code_values": _collect_image_code_values(metric_docs),
    }
    return attempt, markdown, parse_quality, metric_docs, resolved_backend


def _record_table_grits(
    *,
    attempt: dict[str, Any],
    stats: dict[str, Any],
    markdown: str,
    golden_markdown: str,
) -> None:
    table_grits = compute_table_collection_grits(
        pred_tables=_extract_markdown_tables(markdown),
        gold_tables=_extract_markdown_tables(golden_markdown),
    )
    if not any(value is not None for value in table_grits.values()):
        return
    attempt["table_grits"] = table_grits
    for key, stats_key in (
        ("topology", "table_grits_topology"),
        ("content", "table_grits_content"),
        ("f1", "table_grits_f1"),
    ):
        value = table_grits.get(key)
        if value is not None:
            stats[stats_key].append(float(value))


def _record_golden_metrics(
    *,
    attempt: dict[str, Any],
    stats: dict[str, Any],
    markdown: str,
    golden: CaseGoldenData,
) -> None:
    if not golden.markdown:
        return

    similarity = _similarity(markdown, golden.markdown)
    attempt["golden_similarity"] = round(float(similarity), 4)
    _record_table_grits(
        attempt=attempt,
        stats=stats,
        markdown=markdown,
        golden_markdown=golden.markdown,
    )
    if golden.plain_chars > 0:
        coverage = float(attempt["structure"].get("plain_chars") or 0) / float(golden.plain_chars)
        attempt["golden_coverage_ratio"] = round(float(coverage), 4)
        stats["coverage_ratio"].append(float(coverage))
    stats["similarity"].append(float(similarity))
    if golden.image_refs > 0:
        image_recall = float(attempt["structure"].get("image_refs") or 0) / float(golden.image_refs)
        attempt["golden_image_ref_recall"] = round(float(image_recall), 4)
        stats["image_ref_recall"].append(float(image_recall))

    table_continuity = _score_table_continuity(markdown, golden.table_continuity)
    if table_continuity is None:
        table_continuity = _table_continuity_recall(
            golden_markdown=golden.markdown,
            parsed_markdown=markdown,
        )
    if table_continuity is not None:
        attempt["table_continuity_recall"] = round(float(table_continuity), 4)
        stats["table_continuity_recall"].append(float(table_continuity))


def _record_specialty_recall(
    *,
    attempt: dict[str, Any],
    stats: dict[str, Any],
    golden: CaseGoldenData,
) -> None:
    if not golden.specialty:
        return
    specialty_recall: dict[str, float] = {}
    specialty_counts = dict(attempt.get("specialty_elements") or {})
    for kind in _SPECIALTY_KINDS:
        golden_count = int(golden.specialty.get(kind) or 0)
        if golden_count <= 0:
            continue
        recall = min(float(specialty_counts.get(kind) or 0) / float(golden_count), 1.0)
        specialty_recall[kind] = round(float(recall), 4)
        stats["specialty_recall"][kind].append(float(recall))
    if specialty_recall:
        attempt["specialty_recall"] = specialty_recall


def _record_image_visual_kind_recall(
    *,
    attempt: dict[str, Any],
    stats: dict[str, Any],
    golden: CaseGoldenData,
) -> None:
    if not golden.image_visual_kinds:
        return
    subtype_recall: dict[str, float] = {}
    subtype_stats = _nested_metric_map(stats.get("specialty_image_visual_kind_recall"))
    counts = dict(attempt.get("specialty_image_visual_kinds") or {})
    for visual_kind, golden_count in golden.image_visual_kinds.items():
        count = int(golden_count or 0)
        if count <= 0:
            continue
        recall = min(float(counts.get(visual_kind) or 0) / float(count), 1.0)
        subtype_recall[visual_kind] = round(float(recall), 4)
        subtype_stats.setdefault(visual_kind, []).append(float(recall))
    stats["specialty_image_visual_kind_recall"] = subtype_stats
    if subtype_recall:
        attempt["specialty_image_visual_kind_recall"] = subtype_recall


def _record_image_code_value_recall(
    *,
    attempt: dict[str, Any],
    stats: dict[str, Any],
    golden: CaseGoldenData,
) -> None:
    if not golden.image_code_values:
        return
    code_recall: dict[str, float] = {}
    code_stats = _nested_metric_map(stats.get("specialty_image_code_value_recall"))
    actual_values = attempt.get("specialty_image_code_values")
    actual_values = actual_values if isinstance(actual_values, dict) else {}
    for visual_kind, expected_values in golden.image_code_values.items():
        expected = [str(item).strip() for item in expected_values if str(item).strip()]
        if not expected:
            continue
        actual = set(actual_values.get(visual_kind) or [])
        matched = sum(1 for item in expected if item in actual)
        recall = float(matched) / float(len(expected))
        code_recall[visual_kind] = round(recall, 4)
        code_stats.setdefault(visual_kind, []).append(float(recall))
    stats["specialty_image_code_value_recall"] = code_stats
    if code_recall:
        attempt["specialty_image_code_value_recall"] = code_recall


def _record_success_metrics(
    *,
    attempt: dict[str, Any],
    stats: dict[str, Any],
    markdown: str,
    golden: CaseGoldenData,
    parse_quality: dict[str, Any],
) -> None:
    reading_order_score = attempt.get("reading_order_score")
    if reading_order_score is not None:
        stats["reading_order_score"].append(float(reading_order_score))
    _record_golden_metrics(attempt=attempt, stats=stats, markdown=markdown, golden=golden)
    _record_specialty_recall(attempt=attempt, stats=stats, golden=golden)
    _record_image_visual_kind_recall(attempt=attempt, stats=stats, golden=golden)
    _record_image_code_value_recall(attempt=attempt, stats=stats, golden=golden)
    stats["ok"] += 1
    stats["parse_score"].append(float(parse_quality.get("score") or 0.0))


def _run_backend_attempt(
    *,
    case: BenchmarkCase,
    backend: str,
    pdf_quality: dict[str, Any] | None,
    golden: CaseGoldenData,
    stats: dict[str, Any],
    dependencies: BenchmarkDependencies,
) -> dict[str, Any]:
    stats["attempts"] += 1
    started = time.perf_counter()
    attempt: dict[str, Any] = {"backend": backend, "ok": False}
    try:
        parsed_attempt, markdown, parse_quality, _metric_docs, _resolved_backend = _parse_case_backend(
            case=case,
            backend=backend,
            pdf_quality=pdf_quality,
            dependencies=dependencies,
        )
        attempt.update(parsed_attempt)
        _record_success_metrics(
            attempt=attempt,
            stats=stats,
            markdown=markdown,
            golden=golden,
            parse_quality=parse_quality,
        )
    except Exception as exc:
        attempt.update(
            {
                "ok": False,
                "error_type": exc.__class__.__name__,
                "error_message": str(exc)[:200],
            }
        )
    elapsed_ms = int(round((time.perf_counter() - started) * 1000))
    attempt["elapsed_ms"] = elapsed_ms
    stats["elapsed_ms"].append(int(elapsed_ms))
    return attempt


def _run_case(
    *,
    case: BenchmarkCase,
    report: dict[str, Any],
    by_backend: dict[str, dict[str, Any]],
    backends: list[str],
    dependencies: BenchmarkDependencies,
) -> None:
    golden = _load_case_golden_data(case)
    case_row = _build_case_row(case, golden)
    _record_case_fixture_issues(report, case=case, golden=golden)
    pdf_quality = _score_pdf_quality(case, dependencies)
    for backend in backends:
        attempt = _run_backend_attempt(
            case=case,
            backend=backend,
            pdf_quality=pdf_quality,
            golden=golden,
            stats=by_backend[backend],
            dependencies=dependencies,
        )
        case_row["attempts"].append(attempt)
    report["cases"].append(case_row)


def _percentile_value(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    index = int(round((percentile / 100.0) * (len(values) - 1)))
    index = max(0, min(index, len(values) - 1))
    return int(values[index])


def _numeric_list(values: Any) -> list[float]:
    return [float(item) for item in values] if isinstance(values, list) else []


def _build_backend_summary(stats: dict[str, Any]) -> dict[str, Any]:
    elapsed = sorted(int(item) for item in stats.get("elapsed_ms") or [])
    parse_scores = _numeric_list(stats.get("parse_score"))
    similarities = _numeric_list(stats.get("similarity"))
    coverage = _numeric_list(stats.get("coverage_ratio"))
    image_recall = _numeric_list(stats.get("image_ref_recall"))
    table_continuity = _numeric_list(stats.get("table_continuity_recall"))
    table_grits_topology = _numeric_list(stats.get("table_grits_topology"))
    table_grits_content = _numeric_list(stats.get("table_grits_content"))
    table_grits_f1 = _numeric_list(stats.get("table_grits_f1"))
    reading_order_scores = _numeric_list(stats.get("reading_order_score"))
    specialty_recalls = _nested_metric_map(stats.get("specialty_recall"))
    image_visual_kind_recalls = _nested_metric_map(stats.get("specialty_image_visual_kind_recall"))
    image_code_value_recalls = _nested_metric_map(stats.get("specialty_image_code_value_recall"))

    row = {
        "attempts": int(stats.get("attempts") or 0),
        "ok": int(stats.get("ok") or 0),
        "ok_rate": round((float(stats.get("ok") or 0) / float(stats.get("attempts") or 1)), 4),
        "elapsed_ms_p50": _percentile_value(elapsed, 50.0),
        "elapsed_ms_p90": _percentile_value(elapsed, 90.0),
        "parse_score_mean": _average_or_none(parse_scores),
        "golden_similarity_mean": _average_or_none(similarities),
        "golden_coverage_ratio_mean": _average_or_none(coverage),
        "golden_image_ref_recall_mean": _average_or_none(image_recall),
        "mean_table_continuity_recall": _average_or_none(table_continuity),
        "mean_table_grits_topology": _average_or_none(table_grits_topology),
        "mean_table_grits_content": _average_or_none(table_grits_content),
        "mean_table_grits_f1": _average_or_none(table_grits_f1),
        "mean_reading_order_score": _average_or_none(reading_order_scores),
    }
    for kind in _SPECIALTY_KINDS:
        row[f"mean_{kind}_recall"] = _average_or_none(_numeric_list(specialty_recalls.get(kind)))

    subtype_summary: dict[str, float] = {}
    for visual_kind, values in image_visual_kind_recalls.items():
        numeric = _numeric_list(values)
        if numeric:
            subtype_summary[str(visual_kind)] = round(sum(numeric) / len(numeric), 4)
    if subtype_summary:
        row["mean_image_visual_kind_recall"] = subtype_summary

    for visual_kind in _IMAGE_VISUAL_KINDS:
        row[f"mean_{visual_kind}_image_recall"] = subtype_summary.get(visual_kind)
    for visual_kind in ("qr", "barcode"):
        row[f"mean_{visual_kind}_code_value_recall"] = _average_or_none(
            _numeric_list(image_code_value_recalls.get(visual_kind))
        )
    return row


def _build_summary(by_backend: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {backend: _build_backend_summary(stats) for backend, stats in by_backend.items()}


def _load_baseline_report(baseline_path: Path | None) -> dict[str, Any]:
    if baseline_path is None or not baseline_path.exists():
        return {}
    try:
        payload = json.loads(_read_text(baseline_path))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _baseline_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload, dict) else {}
    return summary if isinstance(summary, dict) else {}


def _metric_delta(before: dict[str, Any], after: dict[str, Any], key: str) -> dict[str, Any] | None:
    before_value = before.get(key)
    after_value = after.get(key)
    if before_value is None and after_value is None:
        return None
    delta = None
    if before_value is not None and after_value is not None:
        try:
            delta = float(after_value) - float(before_value)
        except Exception:
            delta = None
    if isinstance(delta, float):
        delta = round(delta, 6)
    return {"before": before_value, "after": after_value, "delta": delta}


def _build_backend_regression_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        metric: diff
        for metric in _BASELINE_REGRESSION_METRICS
        if (diff := _metric_delta(before, after, metric)) is not None
    }


def _attach_baseline_regressions(
    *,
    report: dict[str, Any],
    summary: dict[str, Any],
    config: RunConfig,
) -> dict[str, Any]:
    baseline_obj = _load_baseline_report(config.baseline_path)
    if config.baseline_path is None or not config.baseline_path.exists():
        return baseline_obj

    baseline_summary = _baseline_summary(baseline_obj)
    report["regressions"] = {
        "baseline": str(config.baseline_path),
        "compatibility": evaluate_baseline_compatibility(
            current_report=report,
            baseline_report=baseline_obj,
        ),
        "by_backend": {
            backend: _build_backend_regression_diff(
                before=baseline_summary.get(backend) if isinstance(baseline_summary.get(backend), dict) else {},
                after=after,
            )
            for backend, after in summary.items()
        },
    }
    severity_bands = config.strict_profile.get("severity_bands") if isinstance(config.strict_profile, dict) else {}
    report["regression_severity"] = build_regression_severity_summary(
        current_summary=summary,
        baseline_summary=baseline_summary,
        max_drop_by_metric=config.strict_thresholds,
        severity_bands=severity_bands if isinstance(severity_bands, dict) else None,
    )
    return baseline_obj


def _strict_requires_baseline(config: RunConfig) -> bool:
    return bool(config.args.strict) and not (config.baseline_path and config.baseline_path.exists())


def _build_fixture_issue_failure(item: dict[str, Any]) -> str:
    missing_items = ", ".join(str(value) for value in (item.get("items") or []))
    case_id = str(item.get("case_id") or "unknown")
    return f"{case_id}: missing_local_assets -> {missing_items}"


def _fixture_issue_failures(report: dict[str, Any]) -> list[str]:
    return [
        _build_fixture_issue_failure(item)
        for item in list(report.get("fixture_issues") or [])
        if str(item.get("type") or "") == "missing_local_assets"
    ]


def _apply_strict_gate(
    *,
    report: dict[str, Any],
    summary: dict[str, Any],
    config: RunConfig,
    baseline_obj: dict[str, Any],
) -> int:
    if not bool(config.args.strict):
        return 0

    baseline_summary = _baseline_summary(baseline_obj)
    strict_result = evaluate_strict_regressions(
        current_summary=summary,
        baseline_summary=baseline_summary,
        max_drop_by_metric=config.strict_thresholds,
    )
    compatibility = evaluate_baseline_compatibility(
        current_report=report,
        baseline_report=baseline_obj,
    )
    compatibility_mismatches = list(compatibility.get("mismatches") or [])
    fixture_issue_failures = _fixture_issue_failures(report)
    passed = bool(strict_result.get("passed"))
    passed = passed and not compatibility_mismatches and not fixture_issue_failures
    failures = list(strict_result.get("failures") or [])
    failures.extend(compatibility_mismatches)
    failures.extend(fixture_issue_failures)
    report["strict_gate"] = {
        "enabled": True,
        "thresholds": dict(config.strict_thresholds or {}),
        "passed": passed,
        "failures": failures,
        "by_backend": dict(strict_result.get("by_backend") or {}),
        "compatibility": compatibility,
        "fixture_issues": list(report.get("fixture_issues") or []),
    }
    return 0 if passed else 2


def _write_report(out_path: Path, report: dict[str, Any]) -> None:
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[parser-benchmark] wrote {out_path}")


def main() -> int:
    config = _build_run_config(_build_arg_parser().parse_args())
    dependencies = _load_benchmark_dependencies()
    report = _build_report(config, started_at=datetime.now(timezone.utc))
    by_backend = _build_backend_stats(config.backends)

    for case in config.cases:
        _run_case(
            case=case,
            report=report,
            by_backend=by_backend,
            backends=config.backends,
            dependencies=dependencies,
        )

    summary = _build_summary(by_backend)
    report["summary"] = summary
    if _strict_requires_baseline(config):
        report["strict_gate"] = {
            "enabled": True,
            "passed": False,
            "reason": "baseline_required",
            "failures": ["strict mode requires --baseline to exist"],
        }
        _write_report(config.out_path, report)
        print("[parser-benchmark] strict gate failed: baseline_required")
        return 2

    baseline_obj = _attach_baseline_regressions(report=report, summary=summary, config=config)
    exit_code = _apply_strict_gate(
        report=report,
        summary=summary,
        config=config,
        baseline_obj=baseline_obj,
    )
    _write_report(config.out_path, report)
    if exit_code:
        print("[parser-benchmark] strict gate failed")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
