import json
import os

import pytest

from scripts.perf import run_perf_suite


def test_llm_mock_flag_sets_env(monkeypatch, tmp_path):
    original_llm_mock_env = os.environ.get("LLM_MOCK_ENABLED")
    monkeypatch.delenv("LLM_MOCK_ENABLED", raising=False)

    out_path = tmp_path / "perf.json"
    try:
        try:
            rc = run_perf_suite.main(["--out", str(out_path), "--llm-mock"])
        except SystemExit as exc:
            pytest.fail(f"perf harness should accept --llm-mock (SystemExit={exc.code})")

        assert rc == 0
        assert os.environ.get("LLM_MOCK_ENABLED") == "1"

        assert out_path.exists()
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        assert payload["llm_mock"] is True
        assert payload["llm_mock_env"] == "1"
    finally:
        if original_llm_mock_env is None:
            os.environ.pop("LLM_MOCK_ENABLED", None)
        else:
            os.environ["LLM_MOCK_ENABLED"] = original_llm_mock_env


def test_no_llm_mock_flag_unsets_env(monkeypatch, tmp_path):
    original_llm_mock_env = os.environ.get("LLM_MOCK_ENABLED")
    os.environ["LLM_MOCK_ENABLED"] = "1"

    out_path = tmp_path / "perf.json"
    try:
        try:
            rc = run_perf_suite.main(["--out", str(out_path), "--no-llm-mock"])
        except SystemExit as exc:
            pytest.fail(f"perf harness should accept --no-llm-mock (SystemExit={exc.code})")

        assert rc == 0
        assert os.environ.get("LLM_MOCK_ENABLED") is None

        assert out_path.exists()
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        assert payload["llm_mock"] is False
        assert payload["llm_mock_env"] is None
    finally:
        if original_llm_mock_env is None:
            os.environ.pop("LLM_MOCK_ENABLED", None)
        else:
            os.environ["LLM_MOCK_ENABLED"] = original_llm_mock_env
