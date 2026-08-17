import argparse
import re
import secrets
import shutil
from pathlib import Path


def _plan(*, src: Path, dst: Path, force: bool) -> tuple[str, str]:
    if not src.exists():
        return "skip_missing", f"SKIP (missing template): {src.as_posix()}"
    if dst.exists() and not force:
        return "skip_exists", f"SKIP (exists): {dst.as_posix()}"
    return "write", f"WRITE: {dst.as_posix()} <= {src.as_posix()}"


def _ensure_secret(path: Path, *, key: str, value: str) -> bool:
    """Best-effort: fill an empty secret or append it to an existing env file."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return False

    pattern = re.compile(rf"^(?P<key>{re.escape(key)})=(?P<val>.*)$", re.MULTILINE)
    m = pattern.search(raw)
    if not m:
        separator = "" if not raw or raw.endswith("\n") else "\n"
        updated = f"{raw}{separator}{key}={value}\n"
    else:
        current = (m.group("val") or "").strip()
        if current:
            return False
        updated = pattern.sub(lambda match: f"{match.group('key')}={value}", raw, count=1)

    if updated == raw:
        return False

    try:
        path.write_text(updated, encoding="utf-8")
    except OSError:
        return False
    return True


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create local env files from example templates (cross-platform, non-destructive by default).\n"
            "Templates:\n"
            "  .env.example -> .env (complete local runtime settings)\n"
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
    parser.add_argument(
        "--gen-secret-key",
        action="store_true",
        help="Deprecated compatibility flag; SECRET_KEY is now generated automatically when empty.",
    )
    return parser


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _env_pairs(repo_root: Path) -> list[tuple[Path, Path]]:
    return [
        (repo_root / ".env.example", repo_root / ".env"),
        (repo_root / "web" / ".env.local.example", repo_root / "web" / ".env.local"),
    ]


def _planned_actions(*, repo_root: Path, force: bool) -> list[tuple[str, str, Path, Path]]:
    actions: list[tuple[str, str, Path, Path]] = []
    for src, dst in _env_pairs(repo_root):
        kind, msg = _plan(src=src, dst=dst, force=force)
        actions.append((kind, msg, src, dst))
    return actions


def _run_dry_run(actions: list[tuple[str, str, Path, Path]]) -> int:
    if not actions or all(kind != "write" for kind, *_rest in actions):
        print("[init-env] no changes")
        return 0
    for _kind, msg, _src, _dst in actions:
        print(f"[init-env] {msg}")
    return 0


def _apply_actions(actions: list[tuple[str, str, Path, Path]]) -> bool:
    wrote_any = False
    for kind, msg, src, dst in actions:
        print(f"[init-env] {msg}")
        if kind != "write":
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        wrote_any = True
    return wrote_any


def _fill_secret_key(repo_root: Path) -> bool:
    env_path = repo_root / ".env"
    if not env_path.exists():
        return False
    if _ensure_secret(env_path, key="SECRET_KEY", value=secrets.token_urlsafe(32)):
        print("[init-env] filled SECRET_KEY in .env")
        return True
    return False


def _fill_proxy_secret(repo_root: Path) -> bool:
    wrote_any = False
    proxy_secret = secrets.token_urlsafe(32)
    env_path = repo_root / ".env"
    for path in (env_path, repo_root / "web" / ".env.local"):
        if path.exists() and _ensure_secret(path, key="MARKDOWN_IMAGE_PROXY_SECRET", value=proxy_secret):
            print(f"[init-env] filled MARKDOWN_IMAGE_PROXY_SECRET in {path.relative_to(repo_root)}")
            wrote_any = True
    return wrote_any


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    repo_root = _repo_root()
    actions = _planned_actions(repo_root=repo_root, force=bool(args.force))

    if bool(args.dry_run):
        return _run_dry_run(actions)

    wrote_any = _apply_actions(actions)
    wrote_any = _fill_secret_key(repo_root) or wrote_any
    wrote_any = _fill_proxy_secret(repo_root) or wrote_any

    if not wrote_any:
        print("[init-env] no changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
