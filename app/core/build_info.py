"""Build identity shared by API metadata, ops snapshots and pipeline provenance."""

import os


def get_build_sha() -> str | None:
    value = (
        os.getenv("MIMIRQ_BUILD_SHA")
        or os.getenv("GIT_SHA")
        or os.getenv("SOURCE_VERSION")
        or os.getenv("GITHUB_SHA")
        or ""
    ).strip()
    return value or None


def get_build_time() -> str | None:
    value = (os.getenv("MIMIRQ_BUILD_TIME") or os.getenv("BUILD_TIME") or "").strip()
    return value or None
