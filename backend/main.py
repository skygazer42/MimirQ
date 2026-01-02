from __future__ import annotations

import os
from pathlib import Path


def main() -> None:
    # Ensure relative paths (like `.env` and `./uploads`) resolve from backend/
    backend_root = Path(__file__).resolve().parent
    os.chdir(backend_root)

    import uvicorn

    from app.core.config import settings

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
    )


if __name__ == "__main__":
    main()

