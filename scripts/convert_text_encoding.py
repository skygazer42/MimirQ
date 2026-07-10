"""
Batch-convert text files to UTF-8.

Typical use (from repo root):
  python -m scripts.convert_text_encoding --source . --target output

Defaults:
- converts *.txt (you can add more extensions via --ext)
- keeps relative folder structure under the target directory
- uses app.parsing.utils.text.read_text_file() for best-effort decoding
"""


import argparse
import os
import shutil
from pathlib import Path

from app.parsing.utils.text import read_text_file


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Convert text files to UTF-8 (best-effort).")
    p.add_argument("--source", default=".", help="Source directory (default: current directory)")
    p.add_argument("--target", default="output", help="Target directory (default: ./output)")
    p.add_argument(
        "--ext",
        action="append",
        default=[".txt"],
        help="File extension to include, repeatable (default: .txt)",
    )
    p.add_argument("--clean-target", action="store_true", help="Delete target dir before converting")
    p.add_argument("--dry-run", action="store_true", help="Print actions without writing files")
    return p.parse_args()


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def convert_encoding(*, source_dir: Path, target_dir: Path, extensions: set[str], clean_target: bool, dry_run: bool) -> int:
    source_dir = source_dir.resolve()
    target_dir = target_dir.resolve()

    if clean_target and target_dir.exists() and target_dir.is_dir():
        if dry_run:
            print(f"[dry-run] rm -rf {target_dir}")
        else:
            shutil.rmtree(target_dir)

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    converted = 0
    skipped = 0

    for root, dirs, files in os.walk(source_dir):
        root_path = Path(root)

        # Avoid recursively converting output into itself when target is within source.
        if _is_under(root_path, target_dir):
            dirs[:] = []
            continue
        if _is_under(target_dir, root_path):
            dirs[:] = [d for d in dirs if not _is_under(root_path / d, target_dir)]

        for name in files:
            src_path = root_path / name
            if src_path.suffix.lower() not in extensions:
                continue

            rel = src_path.relative_to(source_dir)
            dest_path = target_dir / rel
            if dry_run:
                decoded = read_text_file(src_path)
                print(f"[dry-run] {src_path} ({decoded.encoding}) -> {dest_path}")
                converted += 1
                continue

            dest_path.parent.mkdir(parents=True, exist_ok=True)
            decoded = read_text_file(src_path)
            try:
                dest_path.write_text(decoded.text, encoding="utf-8")
            except Exception:
                skipped += 1
                continue
            print(f"Converted: {src_path} ({decoded.encoding}) -> {dest_path}")
            converted += 1

    print(f"\nDone. converted={converted} skipped={skipped} target={target_dir}")
    return 0 if skipped == 0 else 1


def main() -> int:
    args = _parse_args()
    exts = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in (args.ext or [])}
    return convert_encoding(
        source_dir=Path(args.source),
        target_dir=Path(args.target),
        extensions=exts,
        clean_target=bool(args.clean_target),
        dry_run=bool(args.dry_run),
    )


if __name__ == "__main__":
    raise SystemExit(main())

