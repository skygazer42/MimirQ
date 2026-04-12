from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCHEMA = "mimirq.parsing_retrieval_proof_governance.v1"


def _load_json(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError(f"governance root must be an object: {path}")
    return obj


def validate_governance(payload: dict[str, Any]) -> dict[str, Any]:
    if str(payload.get("schema") or "").strip() != _SCHEMA:
        raise ValueError(f"invalid_schema: expected {_SCHEMA}")

    mode = str(payload.get("mode") or "").strip().lower()
    if mode not in {"informational", "warn", "fail"}:
        raise ValueError("invalid_mode")

    owner_roles = payload.get("owner_roles")
    if not isinstance(owner_roles, list) or not [str(v).strip() for v in owner_roles if str(v).strip()]:
        raise ValueError("owner_roles_required")

    sample_runner = str(payload.get("sample_runner") or "").strip()
    if not sample_runner:
        raise ValueError("sample_runner_required")

    for key in ("baseline_summary_path", "thresholds_path", "policy_doc_path", "workflow_doc_path"):
        path_text = str(payload.get(key) or "").strip()
        if not path_text:
            raise ValueError(f"{key}_required")
        if not Path(path_text).exists():
            raise ValueError(f"{key}_not_found:{path_text}")

    workflows = payload.get("workflows")
    if not isinstance(workflows, list) or not workflows:
        raise ValueError("workflows_required")
    for item in workflows:
        path_text = str(item or "").strip()
        if not path_text:
            raise ValueError("workflow_path_empty")
        if not Path(path_text).exists():
            raise ValueError(f"workflow_not_found:{path_text}")

    promotion_requirements = payload.get("promotion_requirements")
    if not isinstance(promotion_requirements, list) or not [str(v).strip() for v in promotion_requirements if str(v).strip()]:
        raise ValueError("promotion_requirements_required")

    return {
        "schema": _SCHEMA,
        "mode": mode,
        "owner_roles": [str(v).strip() for v in owner_roles if str(v).strip()],
        "sample_runner": sample_runner,
        "baseline_summary_path": str(payload.get("baseline_summary_path")),
        "thresholds_path": str(payload.get("thresholds_path")),
        "policy_doc_path": str(payload.get("policy_doc_path")),
        "workflow_doc_path": str(payload.get("workflow_doc_path")),
        "workflows": [str(v).strip() for v in workflows if str(v).strip()],
        "promotion_requirements": [str(v).strip() for v in promotion_requirements if str(v).strip()],
    }


def run(*, governance_path: Path, out: Path | None = None) -> dict[str, Any]:
    raw = _load_json(governance_path)
    normalized = validate_governance(raw)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[parsing-proof-governance] valid policy={governance_path}")
    return normalized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate broader parsing-proof governance JSON")
    parser.add_argument("--governance", required=True, help="Path to governance JSON")
    parser.add_argument("--out", default="", help="Optional output path for normalized governance JSON")
    args = parser.parse_args(argv)

    try:
        out = Path(args.out) if str(args.out or "").strip() else None
        run(governance_path=Path(args.governance), out=out)
    except Exception as exc:
        print(f"[parsing-proof-governance] invalid governance: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
