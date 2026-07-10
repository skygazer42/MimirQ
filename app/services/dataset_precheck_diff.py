"""
Dataset precheck diff helpers (pure functions).

Goal: compare two scan-run summaries and return objective deltas for reporting.
"""


from datetime import UTC, datetime
from typing import Any
from uuid import UUID


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _as_int(v: Any) -> int:
    try:
        return int(v or 0)
    except Exception:
        return 0


def _diff_item(*, key: str, before: Any, after: Any) -> dict[str, Any]:
    b = _as_int(before)
    a = _as_int(after)
    return {"key": str(key), "before": b, "after": a, "delta": int(a - b)}


def diff_precheck_summaries(
    *,
    base_scan_run_id: UUID,
    target_scan_run_id: UUID,
    base_summary: dict[str, Any],
    target_summary: dict[str, Any],
) -> dict[str, Any]:
    """
    Compute a stable diff payload between two summaries.

    The input summaries are raw DB JSON blobs (best-effort).
    """
    base_types = base_summary.get("by_file_type") if isinstance(base_summary.get("by_file_type"), dict) else {}
    target_types = target_summary.get("by_file_type") if isinstance(target_summary.get("by_file_type"), dict) else {}
    type_keys = sorted({str(k) for k in (base_types.keys() | target_types.keys())})

    base_pdf = base_summary.get("pdf_scan") if isinstance(base_summary.get("pdf_scan"), dict) else {}
    target_pdf = target_summary.get("pdf_scan") if isinstance(target_summary.get("pdf_scan"), dict) else {}

    def _finding_map(summary: dict[str, Any]) -> dict[str, int]:
        out: dict[str, int] = {}
        raw = summary.get("findings")
        if not isinstance(raw, list):
            return out
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            if not key:
                continue
            out[key] = _as_int(item.get("count"))
        return out

    base_findings = _finding_map(base_summary)
    target_findings = _finding_map(target_summary)
    finding_keys = sorted({*base_findings.keys(), *target_findings.keys()})

    by_file_type = [_diff_item(key=k, before=base_types.get(k), after=target_types.get(k)) for k in type_keys]
    by_file_type.sort(key=lambda d: (-abs(int(d.get("delta") or 0)), str(d.get("key") or "")))

    findings = [_diff_item(key=k, before=base_findings.get(k), after=target_findings.get(k)) for k in finding_keys]
    findings.sort(key=lambda d: (-abs(int(d.get("delta") or 0)), str(d.get("key") or "")))

    return {
        "base_scan_run_id": str(base_scan_run_id),
        "target_scan_run_id": str(target_scan_run_id),
        "generated_at": _now_utc().isoformat(),
        "total_files": _diff_item(
            key="total_files",
            before=base_summary.get("total_files"),
            after=target_summary.get("total_files"),
        ),
        "total_size_bytes": _diff_item(
            key="total_size_bytes",
            before=base_summary.get("total_size_bytes"),
            after=target_summary.get("total_size_bytes"),
        ),
        "pdf_scanned": _diff_item(
            key="pdf_scanned",
            before=base_pdf.get("scanned"),
            after=target_pdf.get("scanned"),
        ),
        "pdf_unknown": _diff_item(
            key="pdf_unknown",
            before=base_pdf.get("unknown"),
            after=target_pdf.get("unknown"),
        ),
        "by_file_type": by_file_type,
        "findings": findings,
    }


__all__ = ["diff_precheck_summaries"]

