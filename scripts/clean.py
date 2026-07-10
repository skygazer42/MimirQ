
import argparse
import shutil
from pathlib import Path


def _iter_pycache_dirs(root: Path) -> list[Path]:
    return [p for p in root.rglob("__pycache__") if p.is_dir()]


def _remove_dir(path: Path, *, dry_run: bool) -> bool:
    if not path.exists():
        return False
    if dry_run:
        return True
    shutil.rmtree(path, ignore_errors=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove common local caches/artifacts.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be removed.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    removed: list[Path] = []

    for rel in [
        Path(".pytest_cache"),
        Path(".ruff_cache"),
        Path("web/.next"),
        Path("web/.next_build"),
    ]:
        target = repo_root / rel
        if _remove_dir(target, dry_run=args.dry_run):
            removed.append(rel)

    for pycache in _iter_pycache_dirs(repo_root):
        rel = pycache.relative_to(repo_root)
        if _remove_dir(pycache, dry_run=args.dry_run):
            removed.append(rel)

    if args.dry_run:
        for rel in removed:
            print(f"[dry-run] remove {rel.as_posix()}")
    else:
        for rel in removed:
            print(f"removed {rel.as_posix()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

