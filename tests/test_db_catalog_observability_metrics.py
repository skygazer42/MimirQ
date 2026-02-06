import app.services.db_catalog_observability as obs


def test_emit_db_catalog_sync_completed_emits_structured_event(monkeypatch):
    calls = []

    def fake_log_metrics(payload):
        calls.append(payload)

    monkeypatch.setattr(obs, "log_metrics", fake_log_metrics)

    obs.emit_db_catalog_sync_completed(
        tenant_id="t1",
        dataset_id="d1",
        run_id="r1",
        connector_id="mysql_catalog",
        elapsed_sec=1.23,
        result={"engine": "mysql", "tables": 2, "tables_upserted": 2, "columns_upserted": 10, "profiles_written": 2},
    )

    assert calls
    assert calls[0]["event"] == "db_catalog.sync.completed"
    assert calls[0]["success"] is True
    assert calls[0]["connector_id"] == "mysql_catalog"
    assert calls[0]["result"]["tables"] == 2
