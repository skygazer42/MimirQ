#!/usr/bin/env python3

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.rag.chunking.strategy_matrix import run_chunk_strategy_matrix  # noqa: E402


def _now_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _to_markdown(results: list[dict[str, object]]) -> str:
    lines = [
        "# Chunking Strategy Matrix",
        "",
        "| strategy | status | chunks | elapsed ms | fixture |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for row in results:
        lines.append(
            f"| {row.get('strategy')} | {row.get('status')} | {row.get('chunk_count')} | {row.get('elapsed_ms')} | {row.get('fixture')} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    out_dir = Path("artifacts") / "chunking-strategy-matrix" / _now_id()
    out_dir.mkdir(parents=True, exist_ok=True)
    results = run_chunk_strategy_matrix()
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
        "failures": [row for row in results if row.get("status") not in {"passed", "unavailable"}],
    }
    (out_dir / "report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(_to_markdown(results), encoding="utf-8")
    print(json.dumps({"output_dir": str(out_dir.resolve()), "failures": payload["failures"]}, ensure_ascii=False, indent=2))
    return 0 if not payload["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
