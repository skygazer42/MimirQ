"""
Small helpers for resolving optional CLI tools.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def resolve_cli_command(command: str) -> str | None:
    """
    Best-effort resolve an executable path for `command`.

    Why: some deployments run the backend with an explicit Python path
    (e.g. `C:\\...\\envs\\kb\\python.exe main.py`) without activating the env,
    so PATH does not include the env Scripts/bin folder.
    """
    cmd = (command or "").strip()
    if not cmd:
        return None

    # Direct/relative path.
    direct = Path(cmd)
    if direct.is_file():
        return str(direct.resolve())

    # Path-like values should not fall back to PATH search.
    is_pathlike = any(sep and sep in cmd for sep in (os.sep, os.altsep)) or (os.name == "nt" and ":" in cmd[:3])
    if is_pathlike:
        return None

    resolved = shutil.which(cmd)
    if resolved:
        return resolved

    exe = Path(sys.executable).resolve()
    base_name = Path(cmd).name
    has_suffix = bool(Path(base_name).suffix)

    names: list[str] = [base_name]
    if not has_suffix and os.name == "nt":
        names.extend([f"{base_name}.exe", f"{base_name}.cmd", f"{base_name}.bat"])

    candidate_dirs = [
        exe.parent,
        exe.parent / "Scripts",
        exe.parent / "bin",
        exe.parent.parent / "Scripts",
        exe.parent.parent / "bin",
    ]

    seen: set[str] = set()
    for d in candidate_dirs:
        try:
            d = d.resolve()
        except Exception:
            pass
        key = str(d)
        if key in seen:
            continue
        seen.add(key)

        for name in names:
            candidate = d / name
            if candidate.is_file():
                return str(candidate.resolve())

    return None


def run_resolved_cli(
    args: Sequence[str],
    *,
    cwd: str | Path | None = None,
    input: bytes | str | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    stdout: Any = subprocess.PIPE,
    stderr: Any = subprocess.PIPE,
    check: bool = True,
    text: bool = False,
) -> subprocess.CompletedProcess[Any]:
    """Run a previously resolved executable without invoking a shell."""
    normalized_args = [str(arg) for arg in args]
    if not normalized_args:
        raise ValueError("CLI command requires at least one argument")

    executable = Path(normalized_args[0])
    if not executable.is_file():
        raise RuntimeError(f"Resolved CLI executable is not a file: {normalized_args[0]}")
    if os.name != "nt" and not os.access(executable, os.X_OK):
        raise RuntimeError(f"Resolved CLI executable is not executable: {normalized_args[0]}")

    # The executable is resolved to a file, arguments stay list-based, and shell remains disabled.
    return subprocess.run(  # noqa: S603  # NOSONAR
        normalized_args,
        cwd=str(cwd) if cwd is not None else None,
        input=input,
        env=dict(env) if env is not None else None,
        timeout=timeout,
        stdout=stdout,
        stderr=stderr,
        check=check,
        text=text,
        shell=False,
    )
