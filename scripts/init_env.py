
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


def main() -> int:
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
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    pairs: list[tuple[Path, Path]] = [
        (repo_root / ".env.example", repo_root / ".env"),
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

    env_path = repo_root / ".env"
    if env_path.exists() and _ensure_secret(env_path, key="SECRET_KEY", value=secrets.token_urlsafe(32)):
        print("[init-env] filled SECRET_KEY in .env")
        wrote_any = True

    proxy_secret = secrets.token_urlsafe(32)
    for path in (env_path, repo_root / "web" / ".env.local"):
        if path.exists() and _ensure_secret(path, key="MARKDOWN_IMAGE_PROXY_SECRET", value=proxy_secret):
            print(f"[init-env] filled MARKDOWN_IMAGE_PROXY_SECRET in {path.relative_to(repo_root)}")
            wrote_any = True

    if not wrote_any:
        print("[init-env] no changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
