from __future__ import annotations

import subprocess
from pathlib import Path


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True)


def _is_tracked(path: Path) -> bool:
    result = _run(["git", "ls-files", "--error-unmatch", "--", str(path)])
    return result.returncode == 0


def _is_non_empty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _git_diff_clean(path: Path) -> bool:
    result = subprocess.run(["git", "diff", "--quiet", "--exit-code", "--", str(path)])
    return result.returncode == 0


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    required = [
        Path("web/openapi.json"),
        Path("web/types/openapi.ts"),
    ]

    ok = True

    for rel in required:
        full = repo_root / rel
        if not _is_non_empty_file(full):
            print(f"[openapi-check] FAIL: missing or empty: {rel.as_posix()}")
            ok = False

    if not ok:
        return 1

    dirty: list[str] = []
    for rel in required:
        if not _is_tracked(rel):
            continue
        if not _git_diff_clean(rel):
            dirty.append(rel.as_posix())

    if dirty:
        joined = ", ".join(dirty)
        print(f"[openapi-check] FAIL: OpenAPI artifacts differ: {joined}")
        print("[openapi-check] Run `make openapi-types` and commit changes.")
        return 1

    print("[openapi-check] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

