"""
Small helpers for resolving optional CLI tools.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


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
        return str(direct)

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
                return str(candidate)

    return None
