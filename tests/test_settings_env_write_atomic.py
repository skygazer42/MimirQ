from __future__ import annotations

from app.api.v1 import settings as settings_api


def test_write_env_file_preserves_comments_and_updates(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# comment\n"
        "A=1\n"
        "B=2\n"
        "\n"
        "# another\n"
        "UNTOUCHED=yes\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(settings_api, "ENV_FILE", env_path)

    settings_api.write_env_file(
        {
            "A": "one",
            "B": "2",
            "C": "3",
            "UNTOUCHED": "yes",
        }
    )

    out = env_path.read_text(encoding="utf-8")
    assert "# comment" in out
    assert "# another" in out
    assert "A=one" in out
    assert "B=2" in out
    assert "C=3" in out
    assert "UNTOUCHED=yes" in out

