from __future__ import annotations


def test_diff_ingestion_policies_detects_added_removed_and_changed_rules() -> None:
    from app.api.schemas.ingestion_policy import IngestionPolicy
    from app.services.ingestion_policy_diff import diff_ingestion_policies

    before = IngestionPolicy(
        rules=[
            {
                "id": "r1",
                "name": "one",
                "enabled": True,
                "match": {"extensions": [".pdf"], "filename_regex": None},
                "preprocess": {"enabled": False, "steps": []},
                "parser_backend": None,
                "chunk_strategy": None,
                "governance_profile_ref": None,
                "pipeline_patch": {},
            },
            {
                "id": "r2",
                "name": "two",
                "enabled": True,
                "match": {"extensions": [".md"], "filename_regex": None},
                "preprocess": {"enabled": False, "steps": []},
                "parser_backend": None,
                "chunk_strategy": None,
                "governance_profile_ref": None,
                "pipeline_patch": {},
            },
        ]
    )
    after = IngestionPolicy(
        rules=[
            {
                "id": "r2",
                "name": "two",
                "enabled": True,
                "match": {"extensions": [".md"], "filename_regex": None},
                "preprocess": {"enabled": True, "steps": [{"id": "text.normalize_newlines", "params": {}}]},
                "parser_backend": None,
                "chunk_strategy": None,
                "governance_profile_ref": None,
                "pipeline_patch": {},
            },
            {
                "id": "r3",
                "name": "three",
                "enabled": True,
                "match": {"extensions": [".html"], "filename_regex": None},
                "preprocess": {"enabled": False, "steps": []},
                "parser_backend": None,
                "chunk_strategy": None,
                "governance_profile_ref": None,
                "pipeline_patch": {},
            },
        ]
    )

    diff = diff_ingestion_policies(before, after)
    assert diff["before_rule_count"] == 2
    assert diff["after_rule_count"] == 2
    assert diff["added_rule_ids"] == ["r3"]
    assert diff["removed_rule_ids"] == ["r1"]
    assert diff["changed_rule_ids"] == ["r2"]


def test_diff_ingestion_policies_handles_none_before_policy() -> None:
    from app.api.schemas.ingestion_policy import IngestionPolicy
    from app.services.ingestion_policy_diff import diff_ingestion_policies

    after = IngestionPolicy(rules=[])
    diff = diff_ingestion_policies(None, after)
    assert diff["before_rule_count"] == 0
    assert diff["after_rule_count"] == 0
    assert diff["added_rule_ids"] == []
    assert diff["removed_rule_ids"] == []
    assert diff["changed_rule_ids"] == []

