"""Build identity shared by API metadata, ops snapshots and pipeline provenance."""

import os


def get_build_sha() -> str | None:
    value = (
        os.getenv("MIMIRQ_BUILD_SHA") or os.getenv("GIT_SHA") or os.getenv("SOURCE_VERSION") or os.getenv("GITHUB_SHA")
    )
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def get_build_time() -> str | None:
    value = os.getenv("MIMIRQ_BUILD_TIME") or os.getenv("BUILD_TIME")
    if value is None:
        return None
    value = value.strip()
    return value if value else None
