from __future__ import annotations

import re
from pathlib import Path


def _extract_compose_default_max_jobs(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    m = re.search(
        r"^\s*TASK_WORKER_MAX_JOBS:\s*\$\{TASK_WORKER_MAX_JOBS_DOCKER:-(\d+)\}\s*$",
        text,
        flags=re.MULTILINE,
    )
    assert m is not None, f"Expected TASK_WORKER_MAX_JOBS default in {path}"
    return int(m.group(1))


def test_default_worker_jobs_is_conservative() -> None:
    """
    Docker Compose defaults should be conservative to avoid OOM / thrash on laptops.
    """

    defaults = {
        "docker-compose.yml": _extract_compose_default_max_jobs(Path("docker/docker-compose.yml")),
        "docker-compose.lite.yml": _extract_compose_default_max_jobs(Path("docker/docker-compose.lite.yml")),
    }
    assert defaults["docker-compose.yml"] <= 4, f"docker-compose.yml default too high: {defaults['docker-compose.yml']}"
    assert (
        defaults["docker-compose.lite.yml"] <= 4
    ), f"docker-compose.lite.yml default too high: {defaults['docker-compose.lite.yml']}"

