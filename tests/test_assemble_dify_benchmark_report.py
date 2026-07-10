import importlib.util
import sys
from pathlib import Path


def _load_module():
    path = Path("scripts/assemble_dify_benchmark_report.py")
    spec = importlib.util.spec_from_file_location("assemble_dify_benchmark_report", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_merge_run_payloads_combines_items_by_case_id() -> None:
    mod = _load_module()

    first = {
        "system": "dify_http_mimirq",
        "app": {"label": "dify_http_mimirq"},
        "summary": {"cases": 5, "succeeded": 1, "failed": 1, "pending": 3, "partial": True},
        "items": [
            {"case_id": "case-1", "ok": True, "answer": "ok-1"},
            {"case_id": "case-2", "ok": False, "error": "HTTP 504"},
        ],
    }
    second = {
        "system": "dify_http_mimirq",
        "app": {"label": "dify_http_mimirq"},
        "summary": {"cases": 2, "succeeded": 1, "failed": 1},
        "items": [
            {"case_id": "case-2", "ok": True, "answer": "ok-2"},
            {"case_id": "case-3", "ok": False, "error": "HTTP 504"},
        ],
    }

    merged = mod.merge_run_payloads([first, second], run_name="run_dify_http_mimirq.json")

    assert merged["system"] == "dify_http_mimirq"
    assert [item["case_id"] for item in merged["items"]] == ["case-1", "case-2", "case-3"]
    assert merged["items"][1]["answer"] == "ok-2"
    assert merged["summary"]["cases"] == 5
    assert merged["summary"]["succeeded"] == 2
    assert merged["summary"]["failed"] == 1
    assert merged["summary"]["pending"] == 2
    assert merged["summary"]["partial"] is True


def test_merge_run_payloads_uses_latest_payload_metadata() -> None:
    mod = _load_module()

    first = {
        "system": "dify_external_mimirq",
        "app": {"label": "dify_external_mimirq", "mode": "chat"},
        "source": {"endpoint": "https://old.example/v1"},
        "summary": {"cases": 2},
        "items": [{"case_id": "case-1", "ok": False, "error": "HTTP 504"}],
    }
    second = {
        "system": "dify_external_mimirq",
        "app": {"label": "dify_external_mimirq", "mode": "workflow"},
        "source": {"endpoint": "https://new.example/v1"},
        "summary": {"cases": 2},
        "items": [{"case_id": "case-1", "ok": True, "answer": "ok"}],
    }

    merged = mod.merge_run_payloads([first, second], run_name="run_dify_external_mimirq.json")

    assert merged["app"]["mode"] == "workflow"
    assert merged["source"]["endpoint"] == "https://new.example/v1"
    assert merged["summary"]["succeeded"] == 1
    assert merged["summary"]["failed"] == 0
