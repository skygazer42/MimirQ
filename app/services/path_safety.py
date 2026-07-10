"""
Filesystem safety helpers.

These helpers are used as defense-in-depth when interacting with paths that may
ultimately be influenced by persisted DB state (e.g. document.file_path) or by
user-configured scan roots.

Design:
- Use `.resolve(strict=False)` to normalize `..` and to *follow symlinks* so we can
  detect and block "symlink escape" (path under base that points outside base).
- Keep helpers small and dependency-free so they can be used across API/services.
"""


from pathlib import Path


def resolve_under_base(path: Path, *, base: Path) -> Path | None:
    """
    Return `path.resolve()` if it stays under `base.resolve()`, else None.

    Notes:
    - This follows symlinks intentionally to prevent "escape via symlink".
    - `strict=False` keeps behavior predictable for missing paths (caller decides).
    """
    try:
        base_resolved = base.resolve(strict=False)
        candidate = path.resolve(strict=False)
        candidate.relative_to(base_resolved)
        return candidate
    except Exception:
        return None


__all__ = ["resolve_under_base"]

