from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


SUITE_NAME = "perf-v1"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the MimirQ performance harness suite.")
    parser.add_argument(
        "--out",
        default=str(Path("runs") / "perf" / f"{SUITE_NAME}.json"),
        help="Output JSON path (default: runs/perf/perf-v1.json).",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL for the MimirQ API (default: http://localhost:8000).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "suite": SUITE_NAME,
        "base_url": args.base_url,
    }

    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

