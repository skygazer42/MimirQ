#!/usr/bin/env python3

import argparse
import hashlib
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.rag.core.hashing import stable_hash


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _load_base_miner():
    path = Path(__file__).resolve().with_name("mine_hard_negatives_from_traces.py")
    spec = importlib.util.spec_from_file_location("mine_hard_negatives_from_traces", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed_to_load_base_miner:{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _count_jsonl_rows(path: Path) -> int:
    if not path.exists():
        return 0
    n = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if str(line or "").strip():
                n += 1
    return int(n)


def build_nightly_manifest(
    *,
    args: argparse.Namespace,
    output_path: Path,
) -> dict[str, Any]:
    return {
        "schema": "mimirq.hard_negatives_nightly_manifest.v1",
        "generated_at": _now_utc_iso(),
        "inputs": {
            "cases_path": str(args.cases),
            "traces_path": str(args.traces),
            "feedback_events_path": (str(args.feedback_events) if str(args.feedback_events or "").strip() else None),
            "tenant_id": (str(args.tenant_id) if str(args.tenant_id or "").strip() else None),
            "retrieval_config_hash": (
                str(args.retrieval_config_hash) if str(args.retrieval_config_hash or "").strip() else None
            ),
        },
        "limits": {
            "max_cases": int(args.max_cases or 0),
            "max_traces": int(args.max_traces or 0),
            "max_hard_negatives": int(args.max_hard_negatives or 0),
            "max_negatives_per_document": int(args.max_negatives_per_document or 0),
        },
        "output_path": str(output_path),
        "records_written": int(_count_jsonl_rows(output_path)),
        "output_sha256": (_sha256_file(output_path) if output_path.exists() else None),
        "run_id": stable_hash(
            json.dumps(
                {
                    "cases": str(args.cases),
                    "traces": str(args.traces),
                    "feedback": str(args.feedback_events or ""),
                    "tenant_id": str(args.tenant_id or ""),
                    "retrieval_config_hash": str(args.retrieval_config_hash or ""),
                    "generated_at": _now_utc_iso(),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            length=16,
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Nightly hard-negative miner (PII-safe JSONL + manifest).")
    parser.add_argument("--cases", required=True, help="Regression cases bundle JSON.")
    parser.add_argument("--traces", required=True, help="rag_trace metrics JSONL.")
    parser.add_argument("--feedback-events", default="", help="Optional feedback/training rows JSONL.")
    parser.add_argument("--out-dir", required=True, help="Output directory for nightly artifacts.")
    parser.add_argument("--retrieval-config-hash", default="", help="Optional retrieval_config_hash filter.")
    parser.add_argument("--tenant-id", default="", help="Optional tenant filter.")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--max-traces", type=int, default=0)
    parser.add_argument("--max-hard-negatives", type=int, default=10)
    parser.add_argument("--max-negatives-per-document", type=int, default=2)
    args = parser.parse_args(argv)

    out_dir = Path(str(args.out_dir)).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_jsonl = out_dir / "hard_negatives.nightly.jsonl"
    out_manifest = out_dir / "hard_negatives.nightly.manifest.json"

    base = _load_base_miner()
    cmd = [
        "--cases",
        str(args.cases),
        "--traces",
        str(args.traces),
        "--out",
        str(out_jsonl),
        "--max-cases",
        str(int(args.max_cases or 0)),
        "--max-traces",
        str(int(args.max_traces or 0)),
        "--max-hard-negatives",
        str(int(args.max_hard_negatives or 0)),
        "--max-negatives-per-document",
        str(int(args.max_negatives_per_document or 0)),
    ]
    if str(args.feedback_events or "").strip():
        cmd.extend(["--feedback-events", str(args.feedback_events)])
    if str(args.retrieval_config_hash or "").strip():
        cmd.extend(["--retrieval-config-hash", str(args.retrieval_config_hash)])
    if str(args.tenant_id or "").strip():
        cmd.extend(["--tenant-id", str(args.tenant_id)])

    rc = int(base.main(cmd))  # type: ignore[attr-defined]
    if rc != 0:
        return int(rc)

    manifest = build_nightly_manifest(args=args, output_path=out_jsonl)
    out_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[hard-negatives-nightly] wrote {out_jsonl}")
    print(f"[hard-negatives-nightly] wrote {out_manifest}")
    print(f"[hard-negatives-nightly] records={int(manifest.get('records_written') or 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
