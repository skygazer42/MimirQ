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


def _load_hard_negative_nightly_module():
    path = Path(__file__).resolve().with_name("mine_hard_negatives_nightly.py")
    spec = importlib.util.spec_from_file_location("mine_hard_negatives_nightly", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed_to_load_module:{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _read_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"invalid_json_object:{path}")
    return obj


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run nightly LTR cycle (hard negatives + lineage manifest).")
    parser.add_argument("--cases", required=True, help="Regression cases bundle JSON.")
    parser.add_argument("--traces", required=True, help="rag_trace metrics JSONL.")
    parser.add_argument("--feedback-events", default="", help="Optional feedback rows JSONL.")
    parser.add_argument("--out-dir", required=True, help="Output directory.")
    parser.add_argument("--tenant-id", default="", help="Optional tenant filter for mining.")
    parser.add_argument("--retrieval-config-hash", default="", help="Optional retrieval_config_hash filter.")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--max-traces", type=int, default=0)
    parser.add_argument("--max-hard-negatives", type=int, default=10)
    parser.add_argument("--max-negatives-per-document", type=int, default=2)
    parser.add_argument("--candidate-model", default="", help="Optional candidate model artifact path.")
    parser.add_argument("--candidate-manifest", default="", help="Optional candidate manifest path.")
    args = parser.parse_args(argv)

    out_dir = Path(str(args.out_dir)).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    cycle_manifest_path = out_dir / "ltr_nightly_cycle.manifest.json"

    hard_neg_mod = _load_hard_negative_nightly_module()
    hard_neg_cmd = [
        "--cases",
        str(args.cases),
        "--traces",
        str(args.traces),
        "--out-dir",
        str(out_dir),
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
        hard_neg_cmd.extend(["--feedback-events", str(args.feedback_events)])
    if str(args.tenant_id or "").strip():
        hard_neg_cmd.extend(["--tenant-id", str(args.tenant_id)])
    if str(args.retrieval_config_hash or "").strip():
        hard_neg_cmd.extend(["--retrieval-config-hash", str(args.retrieval_config_hash)])

    hard_neg_rc = int(hard_neg_mod.main(hard_neg_cmd))  # type: ignore[attr-defined]
    if hard_neg_rc != 0:
        manifest = {
            "schema": "mimirq.ltr_nightly_cycle_manifest.v1",
            "generated_at": _now_utc_iso(),
            "status": "failed",
            "steps": {
                "hard_negative_mining": {
                    "status": "error",
                    "exit_code": int(hard_neg_rc),
                }
            },
        }
        cycle_manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return int(hard_neg_rc)

    hard_neg_jsonl = out_dir / "hard_negatives.nightly.jsonl"
    hard_neg_manifest = out_dir / "hard_negatives.nightly.manifest.json"
    hard_neg_rows = 0
    if hard_neg_manifest.exists():
        try:
            hard_neg_meta = _read_json(hard_neg_manifest)
            hard_neg_rows = int(hard_neg_meta.get("records_written") or 0)
        except Exception:
            hard_neg_rows = 0

    lineage: dict[str, Any] = {
        "schema": "mimirq.ltr_run_lineage.v1",
        "kind": "nightly",
        "tenant_id": (str(args.tenant_id) if str(args.tenant_id or "").strip() else None),
        "retrieval_config_hash": (
            str(args.retrieval_config_hash) if str(args.retrieval_config_hash or "").strip() else None
        ),
        "cases_sha256": _sha256_file(Path(str(args.cases)).expanduser().resolve()),
        "traces_sha256": _sha256_file(Path(str(args.traces)).expanduser().resolve()),
        "hard_negatives_sha256": (_sha256_file(hard_neg_jsonl) if hard_neg_jsonl.exists() else None),
    }

    candidate_model_path = (
        Path(str(args.candidate_model)).expanduser().resolve() if str(args.candidate_model or "").strip() else None
    )
    candidate_manifest_path = (
        Path(str(args.candidate_manifest)).expanduser().resolve()
        if str(args.candidate_manifest or "").strip()
        else None
    )
    if candidate_model_path is not None and candidate_model_path.exists():
        lineage["candidate_model_sha256"] = _sha256_file(candidate_model_path)
        lineage["candidate_model_path"] = str(candidate_model_path)
    if candidate_manifest_path is not None and candidate_manifest_path.exists():
        lineage["candidate_manifest_sha256"] = _sha256_file(candidate_manifest_path)
        lineage["candidate_manifest_path"] = str(candidate_manifest_path)

    cycle_id = stable_hash(
        json.dumps(
            {
                "generated_at": _now_utc_iso(),
                "cases": str(args.cases),
                "traces": str(args.traces),
                "feedback_events": str(args.feedback_events or ""),
                "tenant_id": str(args.tenant_id or ""),
                "retrieval_config_hash": str(args.retrieval_config_hash or ""),
                "hard_neg_rows": int(hard_neg_rows),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        length=16,
    )

    manifest = {
        "schema": "mimirq.ltr_nightly_cycle_manifest.v1",
        "generated_at": _now_utc_iso(),
        "cycle_id": cycle_id,
        "status": "ok",
        "steps": {
            "hard_negative_mining": {
                "status": "ok",
                "output_path": str(hard_neg_jsonl),
                "manifest_path": str(hard_neg_manifest),
                "records_written": int(hard_neg_rows),
            }
        },
        "lineage": lineage,
        "outputs": {
            "hard_negatives_jsonl": str(hard_neg_jsonl),
            "hard_negatives_manifest": str(hard_neg_manifest),
        },
    }
    cycle_manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[ltr-nightly-cycle] wrote {cycle_manifest_path}")
    print(f"[ltr-nightly-cycle] hard_negatives={hard_neg_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
