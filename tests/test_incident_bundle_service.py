from __future__ import annotations

import json
import zipfile
from pathlib import Path


def test_write_incident_bundle_zip(tmp_path: Path):  # noqa: ANN001
    from app.services.incident_bundle_service import write_incident_bundle_zip

    out_path = tmp_path / "bundle.zip"
    result_path = write_incident_bundle_zip(
        out_path=out_path,
        request_id="req-1",
        base_url="http://example.com",
        tenant_id="00000000-0000-0000-0000-000000000000",
        meta={"name": "MimirQ"},
        health_ready={"status": "ok"},
        config_snapshot={"schema": "mimirq.ops_config_snapshot.v1", "fingerprint": "abc", "config": {}},
        trace_bundle={"request_id": "req-1", "records": []},
    )

    assert result_path == out_path
    assert out_path.exists()

    with zipfile.ZipFile(out_path, "r") as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "meta.json" in names
        assert "health_ready.json" in names
        assert "config_snapshot.json" in names
        assert "trace_bundle.json" in names

        manifest = json.loads(zf.read("manifest.json"))
        assert manifest.get("request_id") == "req-1"
        assert manifest.get("base_url") == "http://example.com"

