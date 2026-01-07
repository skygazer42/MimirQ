from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export FastAPI OpenAPI spec to a JSON file.")
    parser.add_argument("--out", default="openapi.json", help="Output path (default: openapi.json)")
    args = parser.parse_args()

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
