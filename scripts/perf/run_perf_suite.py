from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


SUITE_NAME = "perf-v1"


def _utc_compact_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the MimirQ performance harness suite.")
    default_out = str(Path("runs") / "perf" / f"{SUITE_NAME}-{_utc_compact_timestamp()}.json")
    parser.add_argument(
        "--out",
        default=default_out,
        help="Output JSON path (default: timestamped under runs/perf/).",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL for the MimirQ API (default: http://localhost:8000).",
    )
    parser.add_argument(
        "--llm-mock",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable LLM mock mode for this run (sets LLM_MOCK_ENABLED=1).",
    )
    return parser.parse_args(argv)


def _apply_llm_mock_env(enabled: bool) -> None:
    if enabled:
        try:
            os.environ["LLM_MOCK_ENABLED"] = "1"
        except Exception:
            pass
        return

    try:
        os.environ.pop("LLM_MOCK_ENABLED", None)
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _apply_llm_mock_env(bool(getattr(args, "llm_mock", True)))

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
