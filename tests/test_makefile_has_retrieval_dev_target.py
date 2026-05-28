from __future__ import annotations

import re
from pathlib import Path


def test_makefile_has_retrieval_dev_targets() -> None:
    contents = Path("Makefile").read_text(encoding="utf-8")
    assert re.search(
        r"^COMPOSE_RETRIEVAL_DEV := docker compose (?:--env-file \.env -f|-f) docker/docker-compose\.retrieval-dev\.yml(?: --env-file \.env)?$",
        contents,
        flags=re.MULTILINE,
    )
    assert re.search(r"^up-retrieval-dev:$", contents, flags=re.MULTILINE)
    assert re.search(r"^ps-retrieval-dev:$", contents, flags=re.MULTILINE)
    assert re.search(r"^down-retrieval-dev:$", contents, flags=re.MULTILINE)
