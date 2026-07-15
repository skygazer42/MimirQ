import argparse
import json
import os
import secrets
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export FastAPI OpenAPI spec to a JSON file.")
    parser.add_argument("--out", default="openapi.json", help="Output path (default: openapi.json)")
    args = parser.parse_args()

    # Ensure repo root is importable when executed as a script (sys.path[0] == scripts/).
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))

    # Hint the app to avoid heavyweight side effects during OpenAPI export.
    os.environ.setdefault("MIMIRQ_OPENAPI_EXPORT", "1")
    os.environ.setdefault("SECRET_KEY", secrets.token_urlsafe(32))

    # Import here to avoid side effects during argument parsing.
    from app.main import app

    spec = app.openapi()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[openapi] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
