from app.rag.preprocessing.secrets import redact_secrets


def test_redact_secrets_mask_mode_replaces_common_patterns():
    text = (
        "OpenAI: sk-aaaaaaaaaaaaaaaaaaaa\n"
        "Bearer abcdefghijklmnop\n"
        "GitHub: ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        "AWS: AKIAAAAAAAAAAAAAAAAA\n"
        "Slack: xoxb-1234567890-abcdefg\n"
        "-----BEGIN PRIVATE KEY-----\n"
        "abc\n"
        "-----END PRIVATE KEY-----\n"
    )
    res = redact_secrets(text, enabled=True, mode="mask", mask="[S]")

    assert "sk-aaaaaaaaaaaaaaaaaaaa" not in res.text
    assert "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in res.text
    assert "AKIAAAAAAAAAAAAAAAAA" not in res.text
    assert "xoxb-1234567890-abcdefg" not in res.text
    assert "BEGIN PRIVATE KEY" not in res.text
    assert "Bearer [S]" in res.text

    assert res.hits.get("openai_key", 0) >= 1
    assert res.hits.get("bearer_token", 0) >= 1
    assert res.hits.get("github_token", 0) >= 1
    assert res.hits.get("aws_access_key", 0) >= 1
    assert res.hits.get("slack_token", 0) >= 1
    assert res.hits.get("private_key", 0) >= 1
    assert res.changed is True


def test_redact_secrets_token_mode_is_stable_per_value():
    text = "Token: sk-aaaaaaaaaaaaaaaaaaaa and again sk-aaaaaaaaaaaaaaaaaaaa"
    res = redact_secrets(text, enabled=True, mode="token", mask="[S]")

    assert res.text.count("[SECRET_OPENAI_KEY_1]") == 2
    assert res.hits.get("openai_key") == 2


def test_redact_secrets_disabled_is_noop():
    text = "OpenAI: sk-aaaaaaaaaaaaaaaaaaaa"
    res = redact_secrets(text, enabled=False, mode="mask", mask="[S]")
    assert res.text == text
    assert res.hits == {}
    assert res.changed is False

