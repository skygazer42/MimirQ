import os
import warnings
from functools import partial
from pathlib import Path

import uvicorn


def _is_truthy(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    return normalized in {"1", "true", "yes", "y", "on"}


def _is_watch_limit_error(exc: BaseException) -> bool:
    message = str(exc)
    return "MaxFilesWatch" in message or "file watch limit reached" in message.lower()


def main() -> None:
    # Ensure relative paths (like `.env` and `./uploads`) resolve from repo root.
    project_root = Path(__file__).resolve().parent
    os.chdir(project_root)

    # Avoid noisy dev-only warning when running with AUTH_MODE=header.
    warnings.filterwarnings(
        "ignore",
        message=r"pkg_resources is deprecated as an API\..*",
        category=UserWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r"The pynvml package is deprecated\..*",
        category=FutureWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r"Using default SECRET_KEY\. Change this in production!",
        category=UserWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r"Using default MinIO credentials\. Change in production!",
        category=UserWarning,
    )

    from app.infrastructure.config import settings

    reload_dirs = [
        str(project_root / "app"),
        str(project_root / "scripts"),
    ]
    reload_excludes = [
        "web/node_modules",
        "web/.next",
        "web/.next_build",
        "uploads",
    ]

    reload_enabled = _is_truthy(os.getenv("UVICORN_RELOAD"), default=True)
    run_server = partial(
        uvicorn.run,
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=reload_enabled,
        reload_dirs=reload_dirs,
        reload_excludes=reload_excludes,
    )

    try:
        run_server()
    except OSError as exc:
        if not reload_enabled or _is_truthy(os.getenv("WATCHFILES_FORCE_POLLING")) or not _is_watch_limit_error(exc):
            raise
        warnings.warn(
            "OS file watch limit reached; falling back to polling reloader. "
            "To avoid reload, set UVICORN_RELOAD=false. To force polling, set WATCHFILES_FORCE_POLLING=1.",
            UserWarning,
            stacklevel=2,
        )
        os.environ["WATCHFILES_FORCE_POLLING"] = "1"
        run_server()


if __name__ == "__main__":
    main()
