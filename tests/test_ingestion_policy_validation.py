import pytest


def test_ingestion_policy_rejects_unknown_pipeline_patch_keys():
    from app.api.schemas.ingestion_policy import IngestionPolicy
    from app.services.ingestion_policy import validate_and_normalize_ingestion_policy

    policy = IngestionPolicy(
        version="1",
        rules=[
            {
                "id": "rule1",
                "name": "Bad Patch",
                "enabled": True,
                "match": {"extensions": [".pdf"]},
                "preprocess": {"enabled": False, "steps": []},
                "pipeline_patch": {"totally_unknown_key": True},
            }
        ],
    )

    with pytest.raises(ValueError):
        validate_and_normalize_ingestion_policy(policy)


def test_ingestion_policy_rejects_unsupported_preprocess_step():
    from app.api.schemas.ingestion_policy import IngestionPolicy
    from app.services.ingestion_policy import validate_and_normalize_ingestion_policy

    policy = IngestionPolicy(
        version="1",
        rules=[
            {
                "id": "rule1",
                "name": "Bad Step",
                "enabled": True,
                "match": {"extensions": ["txt"]},
                "preprocess": {"enabled": True, "steps": [{"id": "exec.shell", "params": {}}]},
            }
        ],
    )

    with pytest.raises(ValueError):
        validate_and_normalize_ingestion_policy(policy)


def test_ingestion_policy_rejects_suspicious_filename_regex():
    from app.api.schemas.ingestion_policy import IngestionPolicy
    from app.services.ingestion_policy import validate_and_normalize_ingestion_policy

    policy = IngestionPolicy(
        version="1",
        rules=[
            {
                "id": "rule1",
                "name": "Bad Regex",
                "enabled": True,
                "match": {"extensions": [".pdf"], "filename_regex": "(.*)+"},
            }
        ],
    )

    with pytest.raises(ValueError):
        validate_and_normalize_ingestion_policy(policy)


def test_ingestion_policy_normalizes_extensions():
    from app.api.schemas.ingestion_policy import IngestionPolicy
    from app.services.ingestion_policy import validate_and_normalize_ingestion_policy

    policy = IngestionPolicy(
        version="1",
        rules=[
            {
                "id": "rule1",
                "name": "Exts",
                "enabled": True,
                "match": {"extensions": ["PDF", ".pdf", "  html  ", ".htm"]},
            }
        ],
    )

    normalized = validate_and_normalize_ingestion_policy(policy)
    assert normalized.rules[0].match.extensions == [".pdf", ".html", ".htm"]

