
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.rag.preprocessing.pii_anonymizer import anonymize_pii
from app.rag.preprocessing.secrets import redact_secrets
from app.rag.tools.pre_poc_scanner.format_distribution import summarize_format_distribution
from app.rag.tools.pre_poc_scanner.length_distribution import summarize_length_distribution

_SCHEMA = "mimirq.ingest_pre_poc_quality_gate.v1"
_TEXT_EXTS = {".txt", ".md", ".markdown", ".csv", ".json", ".jsonl", ".html", ".htm", ".xml", ".yaml", ".yml"}


def _read_text_sample(path: Path, *, max_bytes: int) -> str:
    if path.suffix.lower() not in _TEXT_EXTS:
        return ""
    data = path.read_bytes()[: max(0, int(max_bytes or 0))]
    if not data:
        return ""
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return data.decode(encoding, errors="ignore")
        except Exception:
            continue
    return data.decode("utf-8", errors="ignore")


def evaluate_ingest_pre_poc_quality_gate(
    file_path: Path,
    *,
    enabled: bool | None = None,
    mode: str | None = None,
    text_sample_bytes: int | None = None,
    pii_max_hits: int | None = None,
    secrets_max_hits: int | None = None,
) -> dict[str, Any]:
    effective_enabled = bool(
        getattr(settings, "INGEST_PRE_POC_SCANNER_ENABLED", False) if enabled is None else enabled
    )
    mode_norm = str(
        getattr(settings, "INGEST_PRE_POC_QUALITY_GATE_MODE", "warn") if mode is None else mode
    ).strip().lower() or "warn"
    if mode_norm not in {"off", "warn", "strict"}:
        mode_norm = "warn"
    path = Path(file_path)
    out: dict[str, Any] = {
        "schema": _SCHEMA,
        "enabled": effective_enabled,
        "mode": mode_norm,
        "status": "skipped",
        "blocked": False,
        "findings": [],
    }
    if not effective_enabled or mode_norm == "off":
        return out

    size_bytes = int(path.stat().st_size) if path.exists() else 0
    sample_bytes = (
        int(getattr(settings, "INGEST_PRE_POC_TEXT_SAMPLE_BYTES", 200_000) or 200_000)
        if text_sample_bytes is None
        else int(text_sample_bytes or 0)
    )
    sample = _read_text_sample(path, max_bytes=sample_bytes)
    pii_threshold = (
        int(settings.INGEST_PRE_POC_PII_MAX_HITS)
        if pii_max_hits is None
        else int(pii_max_hits)
    )
    secret_threshold = (
        int(getattr(settings, "INGEST_PRE_POC_SECRETS_MAX_HITS", 0) or 0)
        if secrets_max_hits is None
        else int(secrets_max_hits)
    )

    findings: list[dict[str, Any]] = []
    pii_hits: dict[str, int] = {}
    secrets_hits: dict[str, int] = {}
    if sample:
        pii = anonymize_pii(sample, enabled=True, mode="mask")
        pii_hits = {str(k): int(v) for k, v in (pii.hits or {}).items() if int(v or 0) > 0}
        sec = redact_secrets(sample, enabled=True, mode="mask")
        secrets_hits = {str(k): int(v) for k, v in (sec.hits or {}).items() if int(v or 0) > 0}
        pii_total = sum(pii_hits.values())
        secret_total = sum(secrets_hits.values())
        if pii_threshold >= 0 and pii_total > pii_threshold:
            findings.append({"key": "pii_threshold_exceeded", "severity": "high", "count": int(pii_total)})
        if secret_threshold >= 0 and secret_total > secret_threshold:
            findings.append({"key": "secrets_threshold_exceeded", "severity": "blocker", "count": int(secret_total)})

    blocked = mode_norm == "strict" and any(
        item.get("key") in {"pii_threshold_exceeded", "secrets_threshold_exceeded"} for item in findings
    )
    out.update(
        {
            "status": "fail" if blocked else ("warn" if findings else "pass"),
            "blocked": bool(blocked),
            "file": {
                "extension": path.suffix.lower().lstrip(".") or "unknown",
                "size_bytes": size_bytes,
            },
            "format_distribution": summarize_format_distribution([str(path)]),
            "length_distribution": summarize_length_distribution([len(sample)] if sample else []),
            "pii_hits_total": pii_hits,
            "secrets_hits_total": secrets_hits,
            "findings": findings,
        }
    )
    return out


__all__ = ["evaluate_ingest_pre_poc_quality_gate"]
