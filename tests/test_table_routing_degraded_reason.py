from __future__ import annotations

from pathlib import Path

from app.services.table_routing import decide_table_route


def test_table_route_xlsx_missing_openpyxl_sets_degraded_reason(monkeypatch, tmp_path: Path):
    import app.services.table_routing as mod

    monkeypatch.setattr(mod, "_get_openpyxl", lambda: None)
    p = tmp_path / "a.xlsx"
    p.write_bytes(b"fake xlsx")

    d = decide_table_route(
        p,
        auto_route=True,
        file_bytes_threshold=0,
        row_threshold=5000,
        col_threshold=80,
        sheet_threshold=5,
    )
    assert d.route == "rag"
    assert d.reason == "shape_unknown"
    assert "dependency_missing:openpyxl" in str(d.stats.get("degraded_reason") or "")

