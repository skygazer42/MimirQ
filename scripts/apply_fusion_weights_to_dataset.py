#!/usr/bin/env python3
"""
Apply (persist) per-dataset fusion weights into dataset metadata (rag_defaults).

This is an admin CLI intended for controlled rollouts:
- validates and normalizes weights
- writes to datasets.metadata.rag_defaults.fusion_weights
- (by default) also sets datasets.metadata.rag_defaults.fusion_strategy="weighted"

Safe by default: dry-run unless --execute.

Examples:
  # Dry-run
  python scripts/apply_fusion_weights_to_dataset.py --dataset-id <uuid> --weights runs/fusion_weights/best.json

  # Execute + enable weighted fusion by default
  python scripts/apply_fusion_weights_to_dataset.py --dataset-id <uuid> --weights runs/fusion_weights/best.json --execute

  # Roll back to defaults (remove dataset override)
  python scripts/apply_fusion_weights_to_dataset.py --dataset-id <uuid> --clear --execute
"""

import argparse
import json
import sys
from uuid import UUID

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.dataset import Dataset


def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except Exception as exc:  # noqa: BLE001
        raise argparse.ArgumentTypeError("must be a valid UUID") from exc


def _load_json(path: str) -> object:
    p = str(path or "").strip()
    if not p:
        raise ValueError("weights path is required")
    return json.loads(open(p, "r", encoding="utf-8-sig").read())


def _extract_weights(obj: object) -> dict[str, float]:
    if isinstance(obj, dict):
        if isinstance(obj.get("fusion_weights"), dict):
            obj = obj.get("fusion_weights")  # type: ignore[assignment]
        elif isinstance(obj.get("weights"), dict):
            obj = obj.get("weights")  # type: ignore[assignment]
    if not isinstance(obj, dict):
        raise ValueError("weights JSON must be an object (or {weights: {...}})")

    allowed = {"vector", "bm25", "lexical", "sparse"}
    out: dict[str, float] = {}
    for k, v in obj.items():
        key = str(k or "").strip().lower()
        if not key or key not in allowed:
            continue
        try:
            w = float(v)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("weights values must be numbers") from exc
        if not (0.0 <= w <= 1.0):
            raise ValueError("weights values must be in [0,1]")
        if w <= 0.0:
            continue
        out[key] = float(w)

    if not out:
        raise ValueError("weights must have at least one positive entry")

    s = sum(out.values())
    if s <= 0.0:
        raise ValueError("weights sum must be > 0")

    norm = {k: round(float(v) / s, 6) for k, v in sorted(out.items())}
    return norm


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Apply per-dataset fusion weights to dataset metadata (rag_defaults).")
    p.add_argument("--dataset-id", type=_parse_uuid, required=True, help="Dataset UUID")
    p.add_argument("--tenant-id", type=_parse_uuid, default=None, help="Tenant UUID (defaults to DEFAULT_TENANT_ID)")
    p.add_argument("--weights", default="", help="Path to weights JSON (ignored when --clear)")
    p.add_argument(
        "--clear", action="store_true", help="Remove dataset fusion_weights override (and weighted strategy if present)"
    )
    p.add_argument(
        "--keep-strategy",
        action="store_true",
        help="Do not change fusion_strategy (default: set to weighted when applying weights).",
    )

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Plan only (no DB writes). Default.")
    mode.add_argument("--execute", action="store_true", help="Execute DB update.")
    args = p.parse_args(argv)

    execute = bool(args.execute)
    dry_run = not execute

    tenant_id = args.tenant_id or UUID(str(settings.DEFAULT_TENANT_ID))
    dataset_id = args.dataset_id

    weights: dict[str, float] | None = None
    if not bool(args.clear):
        try:
            weights = _extract_weights(_load_json(str(args.weights)))
        except Exception as exc:  # noqa: BLE001
            print(f"[apply-fusion-weights] ERROR: {str(exc)[:200]}", file=sys.stderr)
            return 2

    db = SessionLocal()
    try:
        ds = db.query(Dataset).filter(Dataset.tenant_id == tenant_id, Dataset.id == dataset_id).first()
        if not ds:
            print("[apply-fusion-weights] ERROR: dataset not found in tenant scope", file=sys.stderr)
            return 2

        meta = dict(getattr(ds, "dataset_metadata", None) or {})
        rag_defaults = meta.get("rag_defaults") if isinstance(meta.get("rag_defaults"), dict) else {}
        rag_defaults = dict(rag_defaults or {})

        before = json.dumps(rag_defaults, ensure_ascii=False, sort_keys=True)

        if bool(args.clear):
            rag_defaults.pop("fusion_weights", None)
            if str(rag_defaults.get("fusion_strategy") or "").strip().lower() == "weighted":
                rag_defaults.pop("fusion_strategy", None)
        else:
            assert weights is not None
            rag_defaults["fusion_weights"] = dict(weights)
            if not bool(args.keep_strategy):
                rag_defaults["fusion_strategy"] = "weighted"

        # Hide empty objects.
        if rag_defaults:
            meta["rag_defaults"] = rag_defaults
        else:
            meta.pop("rag_defaults", None)

        after = json.dumps(meta.get("rag_defaults") or {}, ensure_ascii=False, sort_keys=True)

        print(
            json.dumps(
                {
                    "ok": True,
                    "dry_run": bool(dry_run),
                    "tenant_id": str(tenant_id),
                    "dataset_id": str(dataset_id),
                    "rag_defaults_before": json.loads(before or "{}"),
                    "rag_defaults_after": json.loads(after or "{}"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        if dry_run:
            return 0

        ds.dataset_metadata = meta
        db.commit()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
