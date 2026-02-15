from pathlib import Path


def test_perf_harness_script_exists():
    path = Path("scripts/perf/run_perf_suite.py")
    assert path.exists()

