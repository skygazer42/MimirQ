"""
Small helpers for resolving optional CLI tools.
"""


import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.rag.core.logging import get_logger

logger = get_logger(__name__)


def _is_pathlike_command(cmd: str) -> bool:
    return any(sep and sep in cmd for sep in (os.sep, os.altsep)) or (os.name == "nt" and ":" in cmd[:3])


def _candidate_command_names(base_name: str) -> list[str]:
    names: list[str] = [base_name]
    if not Path(base_name).suffix and os.name == "nt":
        names.extend([f"{base_name}.exe", f"{base_name}.cmd", f"{base_name}.bat"])
    return names


def _candidate_directories(executable: Path) -> list[Path]:
    return [
        executable.parent,
        executable.parent / "Scripts",
        executable.parent / "bin",
        executable.parent.parent / "Scripts",
        executable.parent.parent / "bin",
    ]


def _resolve_from_python_environment(cmd: str) -> str | None:
    executable = Path(sys.executable).resolve()
    names = _candidate_command_names(Path(cmd).name)

    seen: set[str] = set()
    for directory in _candidate_directories(executable):
        try:
            directory = directory.resolve()
        except Exception as exc:
            logger.debug("Ignoring CLI candidate directory resolve failure: %s", exc)
        key = str(directory)
        if key in seen:
            continue
        seen.add(key)

        for name in names:
            candidate = directory / name
            if candidate.is_file():
                return str(candidate.resolve())

    return None


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
    if _is_pathlike_command(cmd):
        return None

    resolved = shutil.which(cmd)
    if resolved:
        return resolved

    return _resolve_from_python_environment(cmd)


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
