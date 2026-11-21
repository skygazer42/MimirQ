import argparse
import ast
from pathlib import Path
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONVERTER_SCRIPTS = (
    "apply_fusion_weights_to_dataset.py",
    "backfill_kg_event_vector_metadata.py",
    "embedding_blue_green_migrate.py",
    "embedding_drift_monitor.py",
    "replay_index_drift.py",
    "run_nightly_ablations.py",
    "run_periodic_audit_jobs.py",
    "run_stale_report_jobs.py",
)


def _argument_parser(script_name: str) -> argparse.ArgumentParser:
    source = ROOT / "scripts" / script_name
    tree = ast.parse(source.read_text(encoding="utf-8"))
    converter = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_parse_uuid")
    namespace = {"UUID": UUID, "argparse": argparse}
    exec(compile(ast.Module(body=[converter], type_ignores=[]), str(source), "exec"), namespace)
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=namespace["_parse_uuid"], required=True)
    return parser


@pytest.mark.parametrize("script_name", CONVERTER_SCRIPTS)
def test_cli_uuid_converter_returns_a_uuid_for_valid_argument_text(script_name: str) -> None:
    value = "12345678-1234-5678-9012-123456789abc"

    parsed = _argument_parser(script_name).parse_args(["--id", value])

    assert parsed.id == UUID(value)
    assert isinstance(parsed.id, UUID)


@pytest.mark.parametrize("script_name", CONVERTER_SCRIPTS)
def test_cli_uuid_converter_keeps_explicit_invalid_input_errors(
    script_name: str, capsys: pytest.CaptureFixture
) -> None:
    with pytest.raises(SystemExit) as exc:
        _argument_parser(script_name).parse_args(["--id", "not-a-uuid"])

    assert exc.value.code == 2
    assert "valid UUID" in capsys.readouterr().err
