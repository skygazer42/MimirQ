import os

import pytest

from scripts.perf import run_perf_suite


def test_llm_mock_flag_sets_env(monkeypatch, tmp_path):
    monkeypatch.delenv("LLM_MOCK_ENABLED", raising=False)

    out_path = tmp_path / "perf.json"
    try:
        rc = run_perf_suite.main(["--out", str(out_path), "--llm-mock"])
    except SystemExit as exc:
        pytest.fail(f"perf harness should accept --llm-mock (SystemExit={exc.code})")

    assert rc == 0
    assert os.environ.get("LLM_MOCK_ENABLED") == "1"
    assert out_path.exists()
