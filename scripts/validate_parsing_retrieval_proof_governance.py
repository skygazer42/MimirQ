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


def _strip_text(value: Any) -> str:
    return str(value or "").strip()


def _require_schema(payload: dict[str, Any]) -> None:
    if _strip_text(payload.get("schema")) != _SCHEMA:
        raise ValueError(f"invalid_schema: expected {_SCHEMA}")


def _require_mode(payload: dict[str, Any]) -> str:
    mode = _strip_text(payload.get("mode")).lower()
    if mode not in {"informational", "warn", "fail"}:
        raise ValueError("invalid_mode")
    return mode


def _require_existing_path(payload: dict[str, Any], key: str) -> str:
    raw_value = payload.get(key)
    path_text = _strip_text(raw_value)
    if not path_text:
        raise ValueError(f"{key}_required")
    if not Path(path_text).exists():
        raise ValueError(f"{key}_not_found:{path_text}")
    return str(raw_value)


def _normalize_required_list(payload: dict[str, Any], key: str, *, error: str) -> list[str]:
    raw = payload.get(key)
    if not isinstance(raw, list):
        raise ValueError(error)
    values = [_strip_text(item) for item in raw]
    out = [item for item in values if item]
    if not out:
        raise ValueError(error)
    return out


def _validate_workflows(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("workflows")
    if not isinstance(raw, list) or not raw:
        raise ValueError("workflows_required")
    out: list[str] = []
    for item in raw:
        path_text = _strip_text(item)
        if not path_text:
            raise ValueError("workflow_path_empty")
        if not Path(path_text).exists():
            raise ValueError(f"workflow_not_found:{path_text}")
        out.append(path_text)
    return out


def validate_governance(payload: dict[str, Any]) -> dict[str, Any]:
    _require_schema(payload)
    mode = _require_mode(payload)
    owner_roles = _normalize_required_list(payload, "owner_roles", error="owner_roles_required")
    sample_runner = _strip_text(payload.get("sample_runner"))
    if not sample_runner:
        raise ValueError("sample_runner_required")

    baseline_summary_path = _require_existing_path(payload, "baseline_summary_path")
    thresholds_path = _require_existing_path(payload, "thresholds_path")
    policy_doc_path = _require_existing_path(payload, "policy_doc_path")
    workflow_doc_path = _require_existing_path(payload, "workflow_doc_path")
    workflows = _validate_workflows(payload)
    promotion_requirements = _normalize_required_list(
        payload,
        "promotion_requirements",
        error="promotion_requirements_required",
    )

    return {
        "schema": _SCHEMA,
        "mode": mode,
        "owner_roles": owner_roles,
        "sample_runner": sample_runner,
        "baseline_summary_path": baseline_summary_path,
        "thresholds_path": thresholds_path,
        "policy_doc_path": policy_doc_path,
        "workflow_doc_path": workflow_doc_path,
        "workflows": workflows,
        "promotion_requirements": promotion_requirements,
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
