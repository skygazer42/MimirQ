
import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _load_json(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError(f"policy root must be an object: {path}")
    return obj


def run(*, policy_path: Path, out: Path | None = None) -> dict[str, Any]:
    from app.services.queryset_health_service import validate_and_normalize_queryset_health_policy

    raw = _load_json(policy_path)
    normalized = validate_and_normalize_queryset_health_policy(raw)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[queryset-health-policy] valid policy={policy_path}")
    return dict(normalized)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Validate query-set health threshold policy JSON")
    p.add_argument("--policy", required=True, help="Path to policy JSON")
    p.add_argument("--out", default="", help="Optional output path for normalized policy JSON")
    args = p.parse_args(argv)

    try:
        out = Path(args.out) if str(args.out or "").strip() else None
        run(policy_path=Path(args.policy), out=out)
    except Exception as exc:
        print(f"[queryset-health-policy] invalid policy: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
