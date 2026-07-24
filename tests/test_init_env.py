from scripts.init_env import _ensure_secret


def test_ensure_secret_fills_missing_value_without_overwriting_existing_one(tmp_path) -> None:  # noqa: ANN001
    env_path = tmp_path / ".env"
    env_path.write_text("SECRET_KEY=\nEXISTING=keep\n", encoding="utf-8")

    assert _ensure_secret(env_path, key="SECRET_KEY", value="generated") is True
    assert _ensure_secret(env_path, key="MARKDOWN_IMAGE_PROXY_SECRET", value="proxy") is True
    assert _ensure_secret(env_path, key="EXISTING", value="replaced") is False
    assert env_path.read_text(encoding="utf-8") == (
        "SECRET_KEY=generated\nEXISTING=keep\nMARKDOWN_IMAGE_PROXY_SECRET=proxy\n"
    )
