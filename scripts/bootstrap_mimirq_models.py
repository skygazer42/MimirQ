#!/usr/bin/env python3

import argparse
import hashlib
import re
from pathlib import Path

from huggingface_hub import snapshot_download

MODEL_REPO_ID = "qwqqwq/mimirq"
MODEL_REVISION = "118452f3ea3ccd09a41b2d39ea82d7de535e2908"
_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_DIR = _REPO_ROOT / "app" / "deepdoc" / "resources" / "models"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model_snapshot(model_dir: str | Path) -> int:
    root = Path(model_dir).resolve()
    manifest = root / "SHA256SUMS"
    if not manifest.is_file():
        raise RuntimeError(f"model checksum manifest is missing: {manifest}")

    verified = 0
    for line_number, raw_line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or not _SHA256_RE.fullmatch(parts[0]):
            raise RuntimeError(f"invalid SHA256SUMS entry at line {line_number}")

        expected, relative_name = parts
        relative_name = relative_name.lstrip("*")
        candidate = (root / relative_name).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f"checksum path escapes model directory: {relative_name}") from exc
        if not candidate.is_file():
            raise RuntimeError(f"model file is missing: {relative_name}")

        actual = _sha256(candidate)
        if actual != expected:
            raise RuntimeError(
                f"model checksum mismatch: {relative_name} expected={expected} actual={actual}"
            )
        verified += 1

    if verified == 0:
        raise RuntimeError(f"model checksum manifest is empty: {manifest}")
    return verified


def download_and_verify_models(model_dir: str | Path = DEFAULT_MODEL_DIR) -> int:
    target = Path(model_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=MODEL_REPO_ID, revision=MODEL_REVISION, local_dir=target)
    return verify_model_snapshot(target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download and verify MimirQ's pinned DeepDoc model bundle.")
    parser.add_argument("--target", type=Path, default=DEFAULT_MODEL_DIR, help="Model output directory.")
    parser.add_argument("--verify-only", action="store_true", help="Verify an existing model directory.")
    args = parser.parse_args()

    verified = verify_model_snapshot(args.target) if args.verify_only else download_and_verify_models(args.target)
    print(f"[models] verified {verified} files from {MODEL_REPO_ID}@{MODEL_REVISION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
