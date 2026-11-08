import pytest

from app.services.pipeline_config import (
    build_pipeline_metadata,
    merge_pipeline_options,
    parse_pipeline_from_metadata,
    upsert_pipeline_metadata,
)
from app.types.pipeline import PipelineOptions


@pytest.mark.parametrize(
    "field,inherited,empty",
    [
        ("chunk_strategy_params", {"window": 3}, {}),
        ("chunk_python_params", {"batch": 2}, {}),
        ("kg_python_params", {"limit": 10}, {}),
        ("governance_python_params", {"mode": "strict"}, {}),
        ("governance_rule_packs", ["pack-a"], []),
        ("governance_regex_rules", [{"pattern": "alpha", "repl": "beta", "flags": 0}], []),
    ],
)
def test_pipeline_empty_override_survives_persistence_and_clears_inheritance(field: str, inherited, empty) -> None:
    inherited_options = PipelineOptions(**{field: inherited})
    metadata = {}
    assert upsert_pipeline_metadata(metadata, options=PipelineOptions(**{field: empty}))

    stored_options = parse_pipeline_from_metadata(metadata)
    effective = merge_pipeline_options(inherited_options, stored_options)

    assert getattr(stored_options, field) == empty
    assert getattr(effective, field) == empty
    assert getattr(inherited_options, field) == inherited


def test_pipeline_omitted_parameters_keep_inherited_values() -> None:
    inherited = PipelineOptions(chunk_strategy_params={"window": 3})

    stored_options = parse_pipeline_from_metadata({})
    effective = merge_pipeline_options(inherited, stored_options)

    assert stored_options.chunk_strategy_params is None
    assert effective.chunk_strategy_params == {"window": 3}


def test_pipeline_parameter_roundtrip_keeps_primitive_values_and_rejects_nested_values() -> None:
    metadata = build_pipeline_metadata(
        PipelineOptions(chunk_strategy_params={"enabled": False, "window": 0, "nested": {"unexpected": True}})
    )

    assert metadata["chunk_strategy_params"] == {"enabled": False, "window": 0}
    assert parse_pipeline_from_metadata({"pipeline": metadata}).chunk_strategy_params == {"enabled": False, "window": 0}


@pytest.mark.parametrize(
    "field,inherited,invalid,metadata_field",
    [
        (
            "chunk_strategy_params",
            {"window": 3},
            {"nested": {}},
            {"chunk_strategy_params": {"nested": {}}},
        ),
        (
            "governance_rule_packs",
            ["pack-a"],
            ["invalid name"],
            {"governance": {"rule_packs": ["invalid name"]}},
        ),
        (
            "governance_regex_rules",
            [{"pattern": "alpha", "repl": "beta", "flags": 0}],
            [{"pattern": "(a+)+", "repl": "", "flags": 0}],
            {"governance": {"regex_rules": [{"pattern": "(a+)+", "repl": "", "flags": 0}]}},
        ),
    ],
)
def test_rejected_stored_overrides_do_not_clear_inherited_safe_configuration(
    field: str, inherited, invalid, metadata_field
) -> None:
    base = PipelineOptions(**{field: inherited})

    parsed = parse_pipeline_from_metadata({"pipeline": metadata_field})
    merged = merge_pipeline_options(base, parsed)
    rejected_metadata = build_pipeline_metadata(PipelineOptions(**{field: invalid}))

    assert getattr(parsed, field) is None
    assert getattr(merged, field) == inherited
    assert rejected_metadata == {}
