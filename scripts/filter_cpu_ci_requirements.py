#!/usr/bin/env python3
"""Write a CPU-CI requirements file without GPU-only transitive deps.

`xgboost==3.2.0` declares `nvidia-nccl-cu12` on Linux. The project only needs
CPU xgboost in CI and in the default backend image, so those environments
install xgboost separately with `--no-deps` after installing this filtered file.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def _is_xgboost_pin(line: str) -> bool:
    requirement = line.split("#", 1)[0].strip()
    return requirement.lower().startswith("xgboost==")


def _filter_file(source: Path, output: Path, seen: set[Path]) -> None:
    source = source.resolve()
    if source in seen:
        raise SystemExit(f"Recursive requirements include detected: {source}")
    seen.add(source)

    output.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for raw_line in source.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("-r ") or stripped.startswith("--requirement "):
            include_name = stripped.split(maxsplit=1)[1]
            include_source = (source.parent / include_name).resolve()
            include_output = output.parent / f"{include_source.name}.cpu-ci"
            _filter_file(include_source, include_output, seen)
            lines.append(f"-r {include_output}")
            continue
        if _is_xgboost_pin(raw_line):
            lines.append("# xgboost is installed separately with --no-deps for CPU CI.")
            continue
        lines.append(raw_line)

    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    seen.remove(source)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    _filter_file(args.source, args.output, set())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
