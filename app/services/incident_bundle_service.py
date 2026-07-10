"""
Incident bundle helpers.

These are thin utilities intended for ops tooling (scripts/CLI) to package a small
set of diagnostics artifacts into a single zip file for sharing/debugging.
"""


import json
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class IncidentBundle:
    request_id: str
    base_url: str
    tenant_id: str | None
    created_at: str
    meta: dict[str, Any] | None
    health_ready: dict[str, Any] | None
    config_snapshot: dict[str, Any] | None
    trace_bundle: dict[str, Any] | None
    access_graph_summary: dict[str, Any] | None
    periodic_job_freshness: dict[str, Any] | None


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2, default=str)


def _zip_write_json(zf: zipfile.ZipFile, name: str, payload: Mapping[str, Any] | None) -> None:
    if payload is None:
        return
    zf.writestr(name, _json_dumps(dict(payload)))


def write_incident_bundle_zip(
    *,
    out_path: Path,
    request_id: str,
    base_url: str,
    tenant_id: str | None,
    meta: dict[str, Any] | None,
    health_ready: dict[str, Any] | None,
    config_snapshot: dict[str, Any] | None,
    trace_bundle: dict[str, Any] | None,
    access_graph_summary: dict[str, Any] | None = None,
    periodic_job_freshness: dict[str, Any] | None = None,
) -> Path:
    """
    Write a zip bundle with JSON artifacts.

    The bundle is best-effort and intentionally simple: each artifact is a JSON file.
    """

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    bundle = IncidentBundle(
        request_id=str(request_id or "").strip(),
        base_url=str(base_url or "").strip(),
        tenant_id=(str(tenant_id).strip() if tenant_id else None),
        created_at=_utc_now_iso(),
        meta=meta if isinstance(meta, dict) else None,
        health_ready=health_ready if isinstance(health_ready, dict) else None,
        config_snapshot=config_snapshot if isinstance(config_snapshot, dict) else None,
        trace_bundle=trace_bundle if isinstance(trace_bundle, dict) else None,
        access_graph_summary=access_graph_summary if isinstance(access_graph_summary, dict) else None,
        periodic_job_freshness=periodic_job_freshness if isinstance(periodic_job_freshness, dict) else None,
    )

    manifest: dict[str, Any] = {
        "schema": "mimirq.incident_bundle.v1",
        "created_at": bundle.created_at,
        "request_id": bundle.request_id,
        "base_url": bundle.base_url,
        "tenant_id": bundle.tenant_id,
        "files": {
            "meta": bool(bundle.meta),
            "health_ready": bool(bundle.health_ready),
            "config_snapshot": bool(bundle.config_snapshot),
            "trace_bundle": bool(bundle.trace_bundle),
            "access_graph_summary": bool(bundle.access_graph_summary),
            "periodic_job_freshness": bool(bundle.periodic_job_freshness),
        },
    }

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", _json_dumps(manifest))
        _zip_write_json(zf, "meta.json", bundle.meta)
        _zip_write_json(zf, "health_ready.json", bundle.health_ready)
        _zip_write_json(zf, "config_snapshot.json", bundle.config_snapshot)
        _zip_write_json(zf, "trace_bundle.json", bundle.trace_bundle)
        _zip_write_json(zf, "access_graph_summary.json", bundle.access_graph_summary)
        _zip_write_json(zf, "periodic_job_freshness.json", bundle.periodic_job_freshness)

    return out_path


__all__ = ["IncidentBundle", "write_incident_bundle_zip"]
