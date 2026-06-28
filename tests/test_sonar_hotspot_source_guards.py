from __future__ import annotations

import re
from pathlib import Path

FULL_SHA_RE = re.compile(r"@[0-9a-f]{40}(?:\s|$)")


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_parser_service_dockerfiles_drop_root_after_install() -> None:
    expected_users = {
        "docker/magicpdf/Dockerfile": "USER appuser",
        "docker/marker/Dockerfile": "USER appuser",
        "docker/olmocr/Dockerfile": "USER appuser",
        "docker/paddlevl/Dockerfile": "USER paddleocr",
        "docker/qianfanocr/Dockerfile": "USER appuser",
    }

    for dockerfile_path, user_line in expected_users.items():
        dockerfile = _read(dockerfile_path)

        assert user_line in dockerfile
        assert dockerfile.rfind(user_line) > dockerfile.rfind("COPY")


def test_sonar_flagged_workflow_actions_are_pinned_to_full_sha() -> None:
    workflow_paths = [
        ".github/workflows/ci.yml",
        ".github/workflows/lint-fast.yml",
        ".github/workflows/security.yml",
    ]
    flagged_actions = ("pnpm/action-setup", "trufflesecurity/trufflehog")

    for workflow_path in workflow_paths:
        for line in _read(workflow_path).splitlines():
            if not line.lstrip().startswith("uses:"):
                continue
            if not any(action in line for action in flagged_actions):
                continue
            assert FULL_SHA_RE.search(line), line
