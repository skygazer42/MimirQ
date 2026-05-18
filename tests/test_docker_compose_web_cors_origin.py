from __future__ import annotations

from pathlib import Path

import yaml


def test_default_docker_cors_allows_containerized_web_origin() -> None:
    """
    Docker-only browser tests open the frontend through the Compose service name
    (http://web:3000), so the backend default CORS allowlist must include that
    origin as well as host-browser localhost origins.
    """

    compose = yaml.safe_load(Path("docker/docker-compose.yml").read_text(encoding="utf-8"))
    cors_default = compose["x-backend-env"]["CORS_ORIGINS"]

    assert "CORS_ORIGINS_DOCKER:-" in cors_default
    assert "http://localhost:3000" in cors_default
    assert "http://localhost:3001" in cors_default
    assert "http://web:3000" in cors_default
