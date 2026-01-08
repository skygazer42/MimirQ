import os
import warnings
from pathlib import Path


def main() -> None:
    # Ensure relative paths (like `.env` and `./uploads`) resolve from repo root.
    project_root = Path(__file__).resolve().parent
    os.chdir(project_root)

    import uvicorn

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

    from app.core.config import settings

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
    )


if __name__ == "__main__":
    main()
