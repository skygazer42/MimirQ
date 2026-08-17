#!/usr/bin/env python3
"""
Mine PII-safe hard negatives (near-miss citations above first positive) from rag_trace bundles.

Inputs:
- Regression cases bundle (mimirq.regression_cases.v1 or legacy shapes) provides:
  - question (raw, kept only in-memory)
  - reference_sources.chunk_id (ground truth)
- Trace bundle (metrics JSONL, rag_trace events) provides:
  - question_hash/query_hash
  - retrieval.retrieval_config_hash
  - citations[] with identifiers + scores (PII-safe by default)

Output:
- JSONL with schema mimirq.hard_negatives.v1
- PII-safe by construction: NO raw query text is written.
"""

import argparse
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.rag.core.hashing import stable_hash
from app.rag.evaluation.hard_negative_mining import (
    merge_hard_negative_records,
    mine_hard_negatives_for_case_from_trace,
)


def _load_json(path: Path) -> Any:
    # PowerShell commonly writes UTF-8 JSON with BOM; `utf-8-sig` handles both BOM/no-BOM.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def coerce_case_bundle(obj: Any) -> tuple[str, list[dict[str, Any]]]:
    """
    Normalize case bundle payloads into: (dataset_id, items[]).

    Supported shapes:
    - Export bundle v1: {"schema":"mimirq.regression_cases.v1","dataset_id":"...","items":[...]}
    - Minimal bundle: {"dataset_id":"...","items":[...]}
    - Legacy: [{"dataset_id":"...","question":"...","reference_sources":[...], ...}, ...]
    """
    if isinstance(obj, dict) and isinstance(obj.get("items"), list):
        ds = str(obj.get("dataset_id") or "").strip()
        if ds:
            items = [x for x in obj.get("items") if isinstance(x, dict)]
            cleaned = [{k: v for k, v in it.items() if k != "dataset_id"} for it in items]
            return ds, cleaned
        return coerce_case_bundle(list(obj.get("items") or []))

    if isinstance(obj, list):
        items = [x for x in obj if isinstance(x, dict)]
        dsids: list[str] = []
        for it in items:
            ds = str(it.get("dataset_id") or "").strip()
            if ds and ds not in dsids:
                dsids.append(ds)
        if not dsids:
            raise ValueError("dataset_id is required in cases bundle")
        if len(dsids) > 1:
            raise ValueError("mixed dataset_id in cases bundle")
        dsid = dsids[0]
        cleaned = [{k: v for k, v in it.items() if k != "dataset_id"} for it in items]
        return dsid, cleaned

    raise ValueError("cases file must be a JSON array, or an object with { dataset_id, items: [...] }")


def _iter_trace_records(path: Path, *, max_records: int = 0) -> Iterator[dict[str, Any]]:
    """
    Yield parsed rag_trace JSON objects (best-effort).

    Note: This keeps memory bounded (streams the file) and supports max_records.
    """
    with path.open("r", encoding="utf-8", errors="replace") as f:
        emitted = 0
        for line in f:
            if max_records and emitted >= int(max_records):
                break
            line = (line or "").strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            if str(obj.get("event") or "") != "rag_trace":
                continue
            yield obj
            emitted += 1


def _iter_feedback_event_rows(path: Path, *, max_records: int = 0) -> Iterator[dict[str, Any]]:
    """
    Yield parsed feedback/training export rows from JSONL (best-effort).

    Supported row shapes:
    - mimirq.training_export_row.v1 (feedback source rows)
    - lightweight custom rows containing {question, reference_sources, trace_snapshot}
    """
    with path.open("r", encoding="utf-8", errors="replace") as f:
        emitted = 0
        for line in f:
            if max_records and emitted >= int(max_records):
                break
            line = (line or "").strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            yield obj
            emitted += 1


def _feedback_row_to_trace_record(row: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(row, dict):
        return None
    question = str(row.get("question") or row.get("query") or "").strip()
    if not question:
        return None
    trace = row.get("trace_snapshot")
    if not isinstance(trace, dict):
        extra = row.get("extra")
        if isinstance(extra, dict):
            trace = extra.get("retrieval_trace")
    if not isinstance(trace, dict):
        return None

    record = dict(trace)
    qh = str(record.get("question_hash") or record.get("query_hash") or row.get("question_hash") or "").strip()
    if not qh:
        qh = stable_hash(question, length=16)
    record.setdefault("question_hash", qh)
    record.setdefault("event", "rag_trace")

    if not isinstance(record.get("citations"), list):
        citations = row.get("citations")
        if isinstance(citations, list):
            record["citations"] = citations

    return qh, record


class _CliError(RuntimeError):
    pass


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Mine PII-safe hard negatives from rag_trace bundles.")
    p.add_argument("--cases", required=True, help="Path to regression cases JSON (bundle v1 or legacy array)")
    p.add_argument("--traces", required=True, help="Path to metrics JSONL containing rag_trace events")
    p.add_argument(
        "--feedback-events",
        default="",
        help=(
            "Optional JSONL with feedback/training rows (e.g. mimirq.training_export_row.v1) "
            "that include trace_snapshot citations; mined negatives are merged with trace JSONL results."
        ),
    )
    p.add_argument("--out", required=True, help="Write mined hard negatives JSONL to this path")

    p.add_argument(
        "--retrieval-config-hash",
        default="",
        help="Only use trace records matching this retrieval_config_hash (optional)",
    )
    p.add_argument("--tenant-id", default="", help="Only use trace records matching this tenant_id (optional)")
    p.add_argument("--max-cases", type=int, default=0, help="Limit cases processed (default: all)")
    p.add_argument("--max-traces", type=int, default=0, help="Limit trace records read (default: all)")
    p.add_argument("--max-hard-negatives", type=int, default=10, help="Hard negatives per case (default: %(default)s)")
    p.add_argument(
        "--max-negatives-per-document", type=int, default=2, help="Cap negatives per document_id (default: %(default)s)"
    )
    return p


def _resolve_paths(args: argparse.Namespace) -> tuple[Path, Path, Path | None, Path]:
    cases_path = Path(args.cases)
    traces_path = Path(args.traces)
    feedback_path = Path(str(args.feedback_events)) if str(args.feedback_events or "").strip() else None
    if not cases_path.exists():
        raise _CliError(f"cases file not found: {cases_path}")
    if not traces_path.exists():
        raise _CliError(f"traces file not found: {traces_path}")
    if feedback_path is not None and not feedback_path.exists():
        raise _CliError(f"feedback events file not found: {feedback_path}")
    return cases_path, traces_path, feedback_path, Path(args.out)


def _load_case_items(args: argparse.Namespace, cases_path: Path) -> list[dict[str, Any]]:
    try:
        raw_cases = _load_json(cases_path)
        _dataset_id, items = coerce_case_bundle(raw_cases)
    except Exception as exc:  # noqa: BLE001
        raise _CliError(f"failed to parse cases: {str(exc)[:200]}") from exc
    if args.max_cases and int(args.max_cases) > 0:
        return list(items)[: int(args.max_cases)]
    return items


def _build_target_hashes(items: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], int]:
    target_hashes: dict[str, dict[str, Any]] = {}
    skipped = 0
    for item in items:
        if not isinstance(item, dict):
            skipped += 1
            continue
        question = str(item.get("question") or item.get("query") or "").strip()
        if not question:
            skipped += 1
            continue
        question_hash = stable_hash(question, length=16)
        if question_hash in target_hashes:
            raise _CliError(f"duplicate case question hash: {question_hash}")
        target_hashes[question_hash] = item
    return target_hashes, skipped


def _record_config_hash(record: dict[str, Any], *, allow_top_level: bool) -> str:
    retrieval = record.get("retrieval")
    value = str(retrieval.get("retrieval_config_hash") or "").strip() if isinstance(retrieval, dict) else ""
    if not value and allow_top_level:
        return str(record.get("retrieval_config_hash") or "").strip()
    return value


def _matching_trace_hash(
    record: dict[str, Any],
    *,
    target_hashes: dict[str, dict[str, Any]],
    wanted_tenant: str | None,
    wanted_config: str | None,
) -> str | None:
    if wanted_tenant and str(record.get("tenant_id") or "").strip() != wanted_tenant:
        return None
    question_hash = str(record.get("question_hash") or record.get("query_hash") or "").strip()
    if not question_hash or question_hash not in target_hashes:
        return None
    if wanted_config and _record_config_hash(record, allow_top_level=False) != wanted_config:
        return None
    return question_hash


def _index_trace_records(
    path: Path,
    *,
    max_records: int,
    target_hashes: dict[str, dict[str, Any]],
    wanted_tenant: str | None,
    wanted_config: str | None,
) -> tuple[dict[str, list[dict[str, Any]]], int, int]:
    traces_by_hash: dict[str, list[dict[str, Any]]] = {}
    total = 0
    matched = 0
    for record in _iter_trace_records(path, max_records=max_records):
        total += 1
        question_hash = _matching_trace_hash(
            record,
            target_hashes=target_hashes,
            wanted_tenant=wanted_tenant,
            wanted_config=wanted_config,
        )
        if question_hash is None:
            continue
        traces_by_hash.setdefault(question_hash, []).append(record)
        matched += 1
    return traces_by_hash, total, matched


def _feedback_matches_tenant(row: dict[str, Any], record: dict[str, Any], wanted_tenant: str | None) -> bool:
    if not wanted_tenant:
        return True
    source_metadata = row.get("source_metadata")
    candidates = [
        record.get("tenant_id"),
        row.get("tenant_id"),
        source_metadata.get("tenant_id") if isinstance(source_metadata, dict) else None,
    ]
    return any(str(candidate or "").strip() == wanted_tenant for candidate in candidates)


def _matching_feedback_record(
    row: dict[str, Any],
    *,
    target_hashes: dict[str, dict[str, Any]],
    wanted_tenant: str | None,
    wanted_config: str | None,
) -> tuple[str, dict[str, Any]] | None:
    transformed = _feedback_row_to_trace_record(row)
    if transformed is None:
        return None
    question_hash, record = transformed
    if not question_hash or question_hash not in target_hashes:
        return None
    if not _feedback_matches_tenant(row, record, wanted_tenant):
        return None
    if wanted_config and _record_config_hash(record, allow_top_level=True) != wanted_config:
        return None
    return question_hash, record


def _append_feedback_records(
    path: Path | None,
    *,
    max_records: int,
    target_hashes: dict[str, dict[str, Any]],
    wanted_tenant: str | None,
    wanted_config: str | None,
    traces_by_hash: dict[str, list[dict[str, Any]]],
) -> tuple[int, int]:
    if path is None:
        return 0, 0
    total = 0
    matched = 0
    for row in _iter_feedback_event_rows(path, max_records=max_records):
        total += 1
        transformed = _matching_feedback_record(
            row,
            target_hashes=target_hashes,
            wanted_tenant=wanted_tenant,
            wanted_config=wanted_config,
        )
        if transformed is None:
            continue
        question_hash, record = transformed
        traces_by_hash.setdefault(question_hash, []).append(record)
        matched += 1
    return total, matched


def _mine_case_records(
    *,
    case: dict[str, Any],
    question_hash: str,
    trace_records: list[dict[str, Any]],
    max_hard_negatives: int,
    max_negatives_per_document: int,
) -> dict[str, Any] | None:
    mined_rows: list[dict[str, Any]] = []
    for trace in trace_records:
        record = mine_hard_negatives_for_case_from_trace(
            case=case,
            trace_record=trace,
            query_hash=question_hash,
            max_hard_negatives=max_hard_negatives,
            max_negatives_per_document=max_negatives_per_document,
        )
        hard_negatives = record.get("hard_negatives") or []
        if isinstance(hard_negatives, list) and hard_negatives:
            mined_rows.append(record)
    if not mined_rows:
        return None
    return merge_hard_negative_records(records=mined_rows, max_hard_negatives=max_hard_negatives)


def _mine_all_cases(
    target_hashes: dict[str, dict[str, Any]],
    traces_by_hash: dict[str, list[dict[str, Any]]],
    *,
    max_hard_negatives: int,
    max_negatives_per_document: int,
) -> tuple[list[dict[str, Any]], int, int]:
    rows: list[dict[str, Any]] = []
    skipped = 0
    for question_hash, case in target_hashes.items():
        merged = _mine_case_records(
            case=case,
            question_hash=question_hash,
            trace_records=traces_by_hash.get(question_hash) or [],
            max_hard_negatives=max_hard_negatives,
            max_negatives_per_document=max_negatives_per_document,
        )
        if merged is None:
            skipped += 1
            continue
        rows.append(merged)
    return rows, len(rows), skipped


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")


def _print_summary(
    *,
    out_path: Path,
    cases_total: int,
    used: int,
    skipped: int,
    traces_total: int,
    matched_traces: int,
    feedback_total: int,
    feedback_matched: int,
) -> None:
    print(
        "[hard-negatives] OK"
        f" cases_total={cases_total}"
        f" cases_used={used}"
        f" cases_skipped={skipped}"
        f" traces_total={traces_total}"
        f" traces_matched={matched_traces}"
        f" feedback_events_total={feedback_total}"
        f" feedback_events_matched={feedback_matched}"
        f" out={out_path}",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        cases_path, traces_path, feedback_path, out_path = _resolve_paths(args)
        items = _load_case_items(args, cases_path)
        target_hashes, invalid_cases = _build_target_hashes(items)
    except _CliError as exc:
        print(f"[hard-negatives] ERROR: {exc}", file=sys.stderr)
        return 2

    if not target_hashes:
        print("[hard-negatives] ERROR: produced zero case hashes (missing questions?)", file=sys.stderr)
        return 2

    wanted_config = str(args.retrieval_config_hash or "").strip() or None
    wanted_tenant = str(args.tenant_id or "").strip() or None
    max_records = int(args.max_traces or 0)
    traces_by_hash, traces_total, matched_traces = _index_trace_records(
        traces_path,
        max_records=max_records,
        target_hashes=target_hashes,
        wanted_tenant=wanted_tenant,
        wanted_config=wanted_config,
    )
    feedback_total, feedback_matched = _append_feedback_records(
        feedback_path,
        max_records=max_records,
        target_hashes=target_hashes,
        wanted_tenant=wanted_tenant,
        wanted_config=wanted_config,
        traces_by_hash=traces_by_hash,
    )
    rows, used, skipped = _mine_all_cases(
        target_hashes,
        traces_by_hash,
        max_hard_negatives=int(args.max_hard_negatives or 0),
        max_negatives_per_document=int(args.max_negatives_per_document or 0),
    )
    skipped += invalid_cases
    _write_rows(out_path, rows)
    _print_summary(
        out_path=out_path,
        cases_total=len(items),
        used=used,
        skipped=skipped,
        traces_total=traces_total,
        matched_traces=matched_traces,
        feedback_total=feedback_total,
        feedback_matched=feedback_matched,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
