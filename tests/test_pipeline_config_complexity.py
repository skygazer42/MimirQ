import re

from app.services.pipeline_config import _sanitize_regex_rules, build_pipeline_metadata
from app.types.pipeline import PipelineOptions


def test_sanitize_regex_rules_skips_invalid_entries_and_truncates_replacement() -> None:
    sanitized = _sanitize_regex_rules(
        [
            "skip-me",
            {"pattern": "   ", "repl": "x", "flags": 0},
            {"pattern": "(a+)+", "repl": "x", "flags": 0},
            {"pattern": "[", "repl": "x", "flags": 0},
            {"pattern": "alpha", "repl": 123, "flags": re.IGNORECASE},
            {"pattern": "beta", "repl": "y" * 2500, "flags": int(re.MULTILINE)},
            {"pattern": "gamma", "repl": "x", "flags": object()},
        ]
    )

    assert sanitized == [
        {"pattern": "alpha", "repl": "123", "flags": re.IGNORECASE},
        {"pattern": "beta", "repl": "y" * 2000, "flags": re.MULTILINE},
    ]


def test_build_pipeline_metadata_preserves_order_and_omits_empty_sanitized_values() -> None:
    metadata = build_pipeline_metadata(
        PipelineOptions(
            governance_enabled=True,
            parse_fallback_enabled=False,
            chunk_size=128,
            chunk_strategy_params={"window": 3, "ignored": ["nested"]},
            chunk_python_plugin="  ",
            table_store_enabled=True,
            image_ocr_enabled=False,
            ingest_pre_poc_scanner_enabled=True,
            governance_remove_images="all",
            governance_rule_packs=[" Pack-A ", "pack-a", "invalid space"],
            governance_regex_rules=[
                {"pattern": "   alpha   ", "repl": 1, "flags": re.IGNORECASE},
                {"pattern": "(a+)+", "repl": "drop", "flags": 0},
            ],
            governance_pii_mask="[MASKED]",
            governance_python_plugin="plugin:demo-service@1.0.0:governance",
            governance_python_params={"mode": "strict", "drop": {"nested": True}},
            near_dedup_enabled=True,
            chunk_vector_enabled=False,
        )
    )

    assert metadata is not None
    assert list(metadata) == [
        "governance_enabled",
        "parse_fallback_enabled",
        "chunk_size",
        "chunk_strategy_params",
        "tables",
        "images",
        "pre_poc",
        "governance",
        "dedup",
        "index",
    ]
    assert "chunk_python_plugin" not in metadata
    assert metadata["chunk_strategy_params"] == {"window": 3}
    assert metadata["tables"] == {"enabled": True}
    assert metadata["images"] == {"ocr_enabled": False}
    assert metadata["pre_poc"] == {"scanner_enabled": True}
    assert metadata["dedup"] == {"enabled": True}
    assert metadata["index"] == {"chunk_vector_enabled": False}

    governance = metadata["governance"]
    assert list(governance) == [
        "remove_images",
        "rule_packs",
        "regex_rules",
        "pii_mask",
        "python_plugin",
        "python_params",
    ]
    assert governance == {
        "remove_images": "all",
        "rule_packs": ["pack-a"],
        "regex_rules": [{"pattern": "alpha", "repl": "1", "flags": re.IGNORECASE}],
        "pii_mask": "[MASKED]",
        "python_plugin": "plugin:demo-service@1.0.0:governance",
        "python_params": {"mode": "strict"},
    }
