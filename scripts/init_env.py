from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def _plan(*, src: Path, dst: Path, force: bool) -> tuple[str, str]:
    if not src.exists():
        return "skip_missing", f"SKIP (missing template): {src.as_posix()}"
    if dst.exists() and not force:
        return "skip_exists", f"SKIP (exists): {dst.as_posix()}"
    return "write", f"WRITE: {dst.as_posix()} <= {src.as_posix()}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create local env files from example templates (cross-platform, non-destructive by default).\n"
            "Templates:\n"
            "  .env.example -> .env\n"
            "  docker/.env.example -> docker/.env\n"
            "  web/.env.local.example -> web/.env.local"
        )
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing env files (default: only create missing files).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned changes without writing files.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    pairs: list[tuple[Path, Path]] = [
        (repo_root / ".env.example", repo_root / ".env"),
        (repo_root / "docker" / ".env.example", repo_root / "docker" / ".env"),
        (repo_root / "web" / ".env.local.example", repo_root / "web" / ".env.local"),
    ]

    actions: list[tuple[str, str, Path, Path]] = []
    for src, dst in pairs:
        kind, msg = _plan(src=src, dst=dst, force=bool(args.force))
        actions.append((kind, msg, src, dst))

    if bool(args.dry_run):
        if not actions or all(kind != "write" for kind, *_rest in actions):
            print("[init-env] no changes")
            return 0
        for _kind, msg, _src, _dst in actions:
            print(f"[init-env] {msg}")
        return 0

    wrote_any = False
    for kind, msg, src, dst in actions:
        print(f"[init-env] {msg}")
        if kind != "write":
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        wrote_any = True

    if not wrote_any:
        print("[init-env] no changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
