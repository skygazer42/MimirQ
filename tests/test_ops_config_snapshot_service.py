import pytest

from app.core.config import Settings
from app.services import ops_config_snapshot_service as snapshots


@pytest.mark.parametrize(
    ("helper", "parser", "url"),
    [
        (snapshots._redact_sqlalchemy_url, "make_url", "postgresql://user:secret@db/knowledge"),
        (snapshots._redact_generic_url, "urlparse", "redis://user:secret@cache:6379/0"),
    ],
)
def test_redaction_does_not_hide_unexpected_parser_failures(monkeypatch, helper, parser, url):  # noqa: ANN001
    def fail(_url):  # noqa: ANN001, ANN202
        raise RuntimeError("parser invariant failed")

    monkeypatch.setattr(snapshots, parser, fail)

    with pytest.raises(RuntimeError, match="parser invariant failed"):
        helper(url)


def test_config_snapshot_preserves_redaction_and_fingerprint(monkeypatch):  # noqa: ANN001
    config = Settings.model_construct(
        DATABASE_URL="postgresql://user:database-secret@db/knowledge",
        REDIS_URL="redis://user:redis-secret@cache:6379/0",
        LLM_API_KEY="test-llm-secret-key",
        MILVUS_PASSWORD="vector-password",
        LLM_TIMEOUT=60,
    )
    monkeypatch.setattr(snapshots, "settings", config)

    result = snapshots.build_ops_config_snapshot()

    assert result.config["datastores"] == {
        "database_url_redacted": "postgresql://user:***@db/knowledge",
        "redis_url_redacted": "redis://user:***@cache:6379/0",
    }
    assert result.config["llm"]["api_key_masked"] == "test***-key"
    assert result.config["llm"]["api_key_set"] is True
    assert result.config["llm"]["timeout_sec"] == 60.0
    assert isinstance(result.config["llm"]["timeout_sec"], float)
    assert result.config["vector_store"]["milvus"]["port"] == "19530"
    assert result.fingerprint == snapshots.build_ops_config_snapshot().fingerprint

    config.RETRIEVAL_TOP_K += 1
    assert snapshots.build_ops_config_snapshot().fingerprint != result.fingerprint


@pytest.mark.parametrize(
    ("helper", "invalid_url"),
    [
        (snapshots._redact_sqlalchemy_url, "not-a-database-url"),
        (snapshots._redact_sqlalchemy_url, "postgresql://user:secret@db:invalid-port/knowledge"),
        (snapshots._redact_generic_url, "redis://cache:invalid-port/0"),
    ],
)
def test_invalid_urls_keep_the_documented_redacted_marker(helper, invalid_url):  # noqa: ANN001
    assert helper(invalid_url) == "<invalid-url>"
