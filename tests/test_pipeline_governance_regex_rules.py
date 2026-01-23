from app.services.pipeline_config import build_pipeline_metadata, parse_pipeline_from_metadata
from app.types.pipeline import PipelineOptions


def test_pipeline_metadata_roundtrip_governance_regex_rules_sanitizes():
    opts = PipelineOptions(
        governance_regex_rules=[
            {"pattern": r"(?m)^\s*Page\s+\d+\s*$", "repl": "", "flags": 0},
            # Suspicious nested-quantifier pattern should be dropped by sanitizer.
            {"pattern": r"(.*)+", "repl": "", "flags": 0},
            # Unsupported flags should be dropped.
            {"pattern": r"foo", "repl": "", "flags": 999999},
        ]
    )

    meta = build_pipeline_metadata(opts)
    parsed = parse_pipeline_from_metadata({"pipeline": meta})

    assert isinstance(parsed.governance_regex_rules, list)
    assert len(parsed.governance_regex_rules) == 1
    assert parsed.governance_regex_rules[0]["pattern"].startswith("(?m)")

