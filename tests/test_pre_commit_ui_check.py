from pathlib import Path


def test_pre_commit_runs_frontend_ui_audit():
    src = Path(".pre-commit-config.yaml").read_text(encoding="utf-8")

    assert "id: web-ui-check" in src
    assert "pnpm -C web run ui-check" in src
    assert "pass_filenames: false" in src
