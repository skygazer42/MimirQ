#!/usr/bin/env python3
"""
Capture retrieval-only requests (Evidence API) into a PII-safe replay format.

Wave7(B):
- PII-safe by default: capture file MUST NOT include raw query text or document snippets.
- Deterministic: capture includes retrieval_config_hash + citations_fingerprint + seed.

Intended use:
  1) Run this script against a regression cases bundle to produce capture JSONL.
  2) Run scripts/replay_retrieval_replay.py to verify determinism across builds.
"""


import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from app.rag.evaluation.replay_capture import build_retrieval_replay_capture_record


def _load_json(path: Path) -> Any:
    # PowerShell commonly writes UTF-8 JSON with BOM; `utf-8-sig` handles both BOM/no-BOM.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _headers(args: argparse.Namespace) -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if args.tenant_id:
        h["X-Tenant-ID"] = str(args.tenant_id)
    if args.user_id:
        h["X-User-ID"] = str(args.user_id)
    if args.bearer:
        h["Authorization"] = f"Bearer {args.bearer}"
    return h


def coerce_case_bundle(obj: Any) -> tuple[str, list[dict[str, Any]]]:
    """
    Normalize case bundle payloads into: (dataset_id, items[]).

    Supported shapes:
    - Export bundle v1: {"schema":"mimirq.regression_cases.v1","dataset_id":"...","items":[...]}
    - Minimal bundle: {"dataset_id":"...","items":[...]}
    - Legacy: [{"dataset_id":"...","question":"...","reference_sources":[...], ...}, ...]
    """
    if isinstance(obj, dict) and isinstance(obj.get("items"), list):
        ds = str(obj.get("dataset_id") or "").strip()
        if ds:
            items = [x for x in obj.get("items") if isinstance(x, dict)]
            cleaned = [{k: v for k, v in it.items() if k != "dataset_id"} for it in items]
            return ds, cleaned
        return coerce_case_bundle(list(obj.get("items") or []))

    if isinstance(obj, list):
        items = [x for x in obj if isinstance(x, dict)]
        dsids: list[str] = []
        for it in items:
            ds = str(it.get("dataset_id") or "").strip()
            if ds and ds not in dsids:
                dsids.append(ds)
        if not dsids:
            raise ValueError("dataset_id is required in cases bundle")
        if len(dsids) > 1:
            raise ValueError("mixed dataset_id in cases bundle")
        dsid = dsids[0]
        cleaned = [{k: v for k, v in it.items() if k != "dataset_id"} for it in items]
        return dsid, cleaned

    raise ValueError("cases file must be a JSON array, or an object with { dataset_id, items: [...] }")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Capture PII-safe Evidence API replay records.")
    p.add_argument("--cases", required=True, help="Path to regression cases JSON (bundle v1 or legacy array)")
    p.add_argument("--out", required=True, help="Write capture JSONL to this path")

    p.add_argument("--base-url", default="http://localhost:8000/api/v1", help="API base URL (default: %(default)s)")
    p.add_argument("--tenant-id", default="", help="Tenant id (X-Tenant-ID header)")
    p.add_argument("--user-id", default="", help="User id (X-User-ID header, for AUTH_MODE=header)")
    p.add_argument("--bearer", default="", help="Bearer token (Authorization: Bearer ...)")
    p.add_argument("--timeout-sec", type=float, default=30.0, help="HTTP timeout seconds (default: %(default)s)")

    # rag_config overrides
    p.add_argument("--top-k", type=int, default=50, help="Evidence API rag_config.top_k (default: %(default)s)")
    p.add_argument("--score-threshold", type=float, default=0.0, help="Evidence API rag_config.score_threshold (default: %(default)s)")
    p.add_argument("--retrieval-mode", default="hybrid", help="hybrid|vector|keyword|mmr (default: %(default)s)")
    p.add_argument("--retrieval-profile", default="recall50", help="recall20|recall50|coverage80 (default: %(default)s)")
    p.add_argument("--alpha", type=float, default=0.6, help="Fusion alpha (default: %(default)s)")
    p.add_argument("--enable-weight-rerank", action="store_true", help="Enable heuristic weight rerank (default: off)")
    p.add_argument("--enable-reranker", action="store_true", help="Enable reranker (default: off)")
    p.add_argument("--reranker-provider", default="none", help="reranker provider (default: none)")
    p.add_argument("--reranker-top-n", type=int, default=0, help="reranker_top_n (default: %(default)s)")

    p.add_argument("--seed", type=int, default=42, help="Replay seed (default: %(default)s)")
    p.add_argument("--max-cases", type=int, default=0, help="Limit cases processed (default: all)")
    p.add_argument("--max-citations", type=int, default=80, help="Capture at most N citations per case (default: %(default)s)")
    args = p.parse_args(argv)

    cases_path = Path(args.cases)
    out_path = Path(args.out)
    if not cases_path.exists():
        print(f"[replay-capture] ERROR: cases file not found: {cases_path}", file=sys.stderr)
        return 2

    try:
        raw = _load_json(cases_path)
        dataset_id, items = coerce_case_bundle(raw)
    except Exception as exc:  # noqa: BLE001
        print(f"[replay-capture] ERROR: failed to parse cases: {str(exc)[:200]}", file=sys.stderr)
        return 2

    if args.max_cases and int(args.max_cases) > 0:
        items = list(items)[: int(args.max_cases)]

    rag_config = {
        "retrieval_profile": str(args.retrieval_profile),
        "retrieval_mode": str(args.retrieval_mode),
        "top_k": int(args.top_k),
        "score_threshold": float(args.score_threshold),
        "alpha": float(args.alpha),
        "enable_weight_rerank": bool(args.enable_weight_rerank),
        "enable_reranker": bool(args.enable_reranker),
        "reranker_provider": str(args.reranker_provider),
        "reranker_top_n": int(args.reranker_top_n),
    }

    url = str(args.base_url).rstrip("/") + "/rag/retrieve"
    timeout = httpx.Timeout(float(args.timeout_sec or 30.0))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()

    captured = 0
    missed = 0
    with httpx.Client(timeout=timeout) as client, out_path.open("w", encoding="utf-8") as f:
        for it in items:
            if not isinstance(it, dict):
                continue
            question = str(it.get("question") or it.get("query") or "").strip()
            if not question:
                continue

            body = {
                "query": question,
                "history": [],
                "dataset_id": str(dataset_id),
                "document_ids": [],
                "rag_config": rag_config,
                # Optional field; the API ignores it unless supported.
                "seed": int(args.seed),
            }
            try:
                resp = client.post(url, headers=_headers(args), json=body)
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:  # noqa: BLE001
                missed += 1
                print(f"[replay-capture] WARN: retrieve failed: {str(exc)[:200]}", file=sys.stderr)
                continue

            if not isinstance(payload, dict):
                missed += 1
                continue

            rec = build_retrieval_replay_capture_record(
                query=question,
                dataset_id=str(dataset_id),
                document_ids=[],
                rag_config=rag_config,
                evidence_payload=payload,
                seed=int(args.seed),
                max_citations=int(args.max_citations or 0),
            )
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            captured += 1

    print(
        "[replay-capture] OK"
        f" captured={captured}"
        f" missed={missed}"
        f" elapsed_sec={round(float(time.monotonic() - t0), 3)}"
        f" out={out_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

