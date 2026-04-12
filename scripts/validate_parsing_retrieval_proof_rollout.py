from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCHEMA = "mimirq.parsing_retrieval_proof_rollout.v1"
_ALLOWED = {"informational", "warn", "fail"}


def _load_json(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError(f"rollout root must be an object: {path}")
    return obj


def validate_rollout(payload: dict[str, Any]) -> dict[str, Any]:
    if str(payload.get("schema") or "").strip() != _SCHEMA:
        raise ValueError(f"invalid_schema: expected {_SCHEMA}")

    current_stage = str(payload.get("current_stage") or "").strip().lower()
    if current_stage not in _ALLOWED:
        raise ValueError("invalid_current_stage")

    allowed = payload.get("allowed_stages")
    if not isinstance(allowed, list) or [str(v).strip().lower() for v in allowed if str(v).strip().lower() in _ALLOWED] != ["informational", "warn", "fail"]:
        raise ValueError("allowed_stages_invalid")

    owner_roles = payload.get("owner_roles")
    if not isinstance(owner_roles, list) or not [str(v).strip() for v in owner_roles if str(v).strip()]:
        raise ValueError("owner_roles_required")

    requirements = payload.get("promotion_requirements")
    if not isinstance(requirements, dict):
        raise ValueError("promotion_requirements_required")
    for key in ("informational_to_warn", "warn_to_fail"):
        rows = requirements.get(key)
        if not isinstance(rows, list) or not [str(v).strip() for v in rows if str(v).strip()]:
            raise ValueError(f"{key}_required")

    return {
        "schema": _SCHEMA,
        "current_stage": current_stage,
        "allowed_stages": ["informational", "warn", "fail"],
        "promotion_requirements": {
            "informational_to_warn": [str(v).strip() for v in (requirements.get("informational_to_warn") or []) if str(v).strip()],
            "warn_to_fail": [str(v).strip() for v in (requirements.get("warn_to_fail") or []) if str(v).strip()],
        },
        "owner_roles": [str(v).strip() for v in owner_roles if str(v).strip()],
    }


def run(*, rollout_path: Path, out: Path | None = None) -> dict[str, Any]:
    raw = _load_json(rollout_path)
    normalized = validate_rollout(raw)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[parsing-proof-rollout] valid policy={rollout_path}")
    return normalized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate broader parsing-proof staged rollout JSON")
    parser.add_argument("--rollout", required=True, help="Path to rollout JSON")
    parser.add_argument("--out", default="", help="Optional output path for normalized rollout JSON")
    args = parser.parse_args(argv)

    try:
        out = Path(args.out) if str(args.out or "").strip() else None
        run(rollout_path=Path(args.rollout), out=out)
    except Exception as exc:
        print(f"[parsing-proof-rollout] invalid rollout: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
