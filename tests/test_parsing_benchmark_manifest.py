from pathlib import Path

from scripts.run_parsing_benchmark import _load_cases


def test_parsing_benchmark_loads_repository_manifest() -> None:
    golden_dir = Path("tests/fixtures/parsing_golden_broader").resolve()

    cases = _load_cases(golden_dir=golden_dir, cases_json=golden_dir / "manifest.json")

    assert len(cases) == 21
    assert cases[0]["input_path"] == golden_dir / "chart_pdf/input/sample.pdf"
