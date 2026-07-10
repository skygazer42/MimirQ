#!/usr/bin/env python3

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.ltr_model_registry import evaluate_online_rollback_trigger, rollback_active_model


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _load_windows(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    obj = json.loads(raw)
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        rows = obj.get("windows")
        if isinstance(rows, list):
            return [x for x in rows if isinstance(x, dict)]
    raise ValueError("windows_file_invalid: expected JSON list or {windows:[...]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LTR online rollback daemon (windowed degradation trigger).")
    parser.add_argument("--windows-file", required=True, help="JSON file containing degradation windows.")
    parser.add_argument("--metric-key", default="delta.mrr")
    parser.add_argument("--max-allowed-delta", type=float, default=-0.02)
    parser.add_argument("--min-consecutive-windows", type=int, default=3)
    parser.add_argument("--apply-rollback", action="store_true", help="Apply rollback when trigger fires.")
    parser.add_argument("--actor-id", default="ltr-online-daemon")
    parser.add_argument("--out", default="artifacts/ltr_online_rollback.report.json")
    args = parser.parse_args(argv)

    windows_path = Path(str(args.windows_file)).expanduser().resolve()
    if not windows_path.exists():
        raise SystemExit(f"windows_file_not_found:{windows_path}")

    windows = _load_windows(windows_path)
    trigger = evaluate_online_rollback_trigger(
        windows=windows,
        metric_key=str(args.metric_key or "delta.mrr"),
        max_allowed_delta=float(args.max_allowed_delta),
        min_consecutive_windows=max(1, int(args.min_consecutive_windows or 1)),
    )

    rollback_payload: dict[str, Any] = {
        "applied": False,
        "reason": "not_triggered",
    }
    exit_code = 0
    if bool(trigger.get("triggered")) and bool(args.apply_rollback):
        try:
            active = rollback_active_model(actor_id=str(args.actor_id or "").strip() or None)
            rollback_payload = {
                "applied": True,
                "reason": "rollback_executed",
                "active": dict(active or {}),
            }
        except Exception as exc:  # noqa: BLE001
            rollback_payload = {
                "applied": False,
                "reason": f"rollback_error:{exc.__class__.__name__}",
                "error": str(exc)[:200],
            }
            exit_code = 3

    report = {
        "schema": "mimirq.ltr_online_rollback_daemon_report.v1",
        "generated_at": _now_utc_iso(),
        "inputs": {
            "windows_file": str(windows_path),
            "metric_key": str(args.metric_key or "delta.mrr"),
            "max_allowed_delta": float(args.max_allowed_delta),
            "min_consecutive_windows": int(max(1, int(args.min_consecutive_windows or 1))),
            "apply_rollback": bool(args.apply_rollback),
        },
        "trigger": trigger,
        "rollback": rollback_payload,
    }

    out_path = Path(str(args.out)).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[ltr-online-rollback] wrote {out_path}")
    print(f"[ltr-online-rollback] triggered={bool(trigger.get('triggered'))} applied={bool(rollback_payload.get('applied'))}")
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
