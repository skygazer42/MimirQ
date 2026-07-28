#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

WHEEL_DOWNLOAD_USER_AGENT = "MimirQ-CI/1.0 (+https://github.com/skygazer42/MimirQ)"


@dataclasses.dataclass(frozen=True)
class WheelSpec:
    filename: str
    url: str
    sha256: str


WHEELS: tuple[WheelSpec, ...] = (
    WheelSpec(
        filename="torch-2.13.0+cpu-cp311-cp311-manylinux_2_28_x86_64.whl",
        url="https://download-r2.pytorch.org/whl/cpu/torch-2.13.0+cpu-cp311-cp311-manylinux_2_28_x86_64.whl",
        sha256="6746dbcbeb526eb61330b76b41ff1b4eb848951103a892eeb080dfa2b264667b",
    ),
    WheelSpec(
        filename="torchvision-0.28.0+cpu-cp311-cp311-manylinux_2_28_x86_64.whl",
        url="https://download-r2.pytorch.org/whl/cpu/torchvision-0.28.0+cpu-cp311-cp311-manylinux_2_28_x86_64.whl",
        sha256="1dad604dfc0177ecebe0891bd9701fe2c62ec3f7819a247be541b3fb6effee99",
    ),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_existing(path: Path, expected_sha256: str) -> bool:
    if not path.is_file():
        return False
    try:
        return _sha256(path) == expected_sha256
    except OSError:
        return False


def _download(spec: WheelSpec, target: Path, retries: int, timeout_sec: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if _verified_existing(target, spec.sha256):
        print(f"[wheels] using cached {spec.filename}")
        return

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{spec.filename}.", suffix=".tmp", dir=target.parent, delete=False
            ) as tmp:
                tmp_path = Path(tmp.name)
                request = urllib.request.Request(
                    spec.url,
                    headers={"User-Agent": WHEEL_DOWNLOAD_USER_AGENT},
                )
                with urllib.request.urlopen(request, timeout=timeout_sec) as response:
                    shutil.copyfileobj(response, tmp)

            actual_sha256 = _sha256(tmp_path)
            if actual_sha256 != spec.sha256:
                raise RuntimeError(
                    f"sha256 mismatch for {spec.filename}: expected {spec.sha256}, got {actual_sha256}"
                )

            tmp_path.replace(target)
            print(f"[wheels] downloaded {spec.filename}")
            return
        except (OSError, urllib.error.URLError, RuntimeError) as exc:
            last_error = exc
            if tmp_path is not None:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            if attempt < retries:
                time.sleep(min(5 * attempt, 15))

    raise SystemExit(f"[wheels] failed to fetch {spec.filename}: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download and verify pinned CPU wheels.")
    parser.add_argument("--cache-dir", required=True, help="Directory used to cache verified wheels.")
    parser.add_argument("--retries", type=int, default=5, help="Download attempts per wheel.")
    parser.add_argument("--timeout-sec", type=int, default=120, help="Per-attempt network timeout.")
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir)
    for spec in WHEELS:
        _download(spec, cache_dir / spec.filename, retries=args.retries, timeout_sec=args.timeout_sec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
