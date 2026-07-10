#!/usr/bin/env python3
"""
Chaos helper: simulate dependency outage by scaling Kubernetes resources to 0 and back.

This script is intentionally generic so it can be used for Redis/MinIO/Milvus (or others),
as long as they run inside the same Kubernetes cluster.

Safe-by-default:
- Dry-run unless --execute is passed.
- Captures original replica counts and restores them on best-effort.

Example (dry-run):
  python scripts/chaos_dependency_outage.py \
    --namespace infra \
    --resource deployment/redis \
    --resource statefulset/milvus \
    --down-seconds 120

Example (execute):
  python scripts/chaos_dependency_outage.py \
    --namespace infra \
    --resource deployment/redis \
    --down-seconds 120 \
    --execute
"""


import argparse
import json
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_RESOURCE_RE = re.compile(r"^(deployment|statefulset|daemonset|replicaset|job|cronjob)/[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class CmdResult:
    cmd: list[str]
    exit_code: int
    stdout: str
    stderr: str


def _run(cmd: list[str], *, timeout_sec: float = 30.0) -> CmdResult:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=timeout_sec)
    except subprocess.TimeoutExpired as exc:
        return CmdResult(cmd=cmd, exit_code=124, stdout=(exc.stdout or ""), stderr=f"TimeoutExpired: {exc}")
    except FileNotFoundError as exc:
        return CmdResult(cmd=cmd, exit_code=127, stdout="", stderr=f"{type(exc).__name__}: {exc}")
    return CmdResult(cmd=cmd, exit_code=int(proc.returncode), stdout=(proc.stdout or ""), stderr=(proc.stderr or ""))


def _get_replicas(*, namespace: str, kind: str, name: str) -> tuple[int | None, CmdResult]:
    # Use JSONPath to avoid requiring jq.
    cmd = ["kubectl", "-n", namespace, "get", kind, name, "-o", "jsonpath={.spec.replicas}"]
    res = _run(cmd, timeout_sec=20.0)
    if res.exit_code != 0:
        return None, res
    raw = (res.stdout or "").strip()
    if raw == "":
        # Some kinds may not have replicas; treat as unsupported.
        return None, res
    try:
        return int(raw), res
    except ValueError:
        return None, res


def _scale(*, namespace: str, kind: str, name: str, replicas: int) -> CmdResult:
    cmd = ["kubectl", "-n", namespace, "scale", kind, name, f"--replicas={int(replicas)}"]
    return _run(cmd, timeout_sec=60.0)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Chaos helper: scale dependencies down/up (kubectl).")
    p.add_argument("--namespace", required=True, help="Kubernetes namespace where dependencies run.")
    p.add_argument(
        "--resource",
        action="append",
        default=[],
        help="Target resource in kind/name form (repeatable), e.g. deployment/redis or statefulset/milvus.",
    )
    p.add_argument("--down-seconds", type=int, default=120, help="How long to keep resources at 0 replicas (default: 120).")
    p.add_argument("--execute", action="store_true", help="Actually run kubectl scale (default: dry-run).")

    args = p.parse_args(argv)

    namespace = str(args.namespace or "").strip()
    resources = [str(r or "").strip() for r in (args.resource or []) if str(r or "").strip()]
    if not namespace:
        print(json.dumps({"ok": False, "error": "namespace_required"}, ensure_ascii=False))
        return 2
    if not resources:
        print(json.dumps({"ok": False, "error": "no_resources_selected"}, ensure_ascii=False))
        return 2

    invalid = [r for r in resources if not _RESOURCE_RE.match(r)]
    if invalid:
        print(json.dumps({"ok": False, "error": "invalid_resource", "resources": invalid}, ensure_ascii=False))
        return 2

    down_seconds = max(0, int(args.down_seconds or 0))
    execute = bool(args.execute)

    report: dict[str, Any] = {
        "schema": "mimirq.chaos_dependency_outage.v1",
        "ran_at": _utc_now_iso(),
        "namespace": namespace,
        "execute": execute,
        "down_seconds": down_seconds,
        "targets": [],
        "ok": True,
    }

    originals: list[tuple[str, str, str, int]] = []

    # 1) Read originals
    for r in resources:
        kind, name = r.split("/", 1)
        replicas, res = _get_replicas(namespace=namespace, kind=kind, name=name)
        report["targets"].append(
            {
                "resource": r,
                "original_replicas": replicas,
                "get_replicas": {
                    "cmd": res.cmd,
                    "exit_code": res.exit_code,
                    "stdout": (res.stdout or "").strip()[:200],
                    "stderr": (res.stderr or "").strip()[:200],
                },
            }
        )
        if replicas is None:
            report["ok"] = False
            report["error"] = "failed_to_read_replicas"
        else:
            originals.append((r, kind, name, replicas))

    if not bool(report["ok"]):
        print(json.dumps(report, ensure_ascii=False))
        return 1

    if not execute:
        print(json.dumps(report, ensure_ascii=False))
        return 0

    # 2) Scale down
    for r, kind, name, _replicas in originals:
        res = _scale(namespace=namespace, kind=kind, name=name, replicas=0)
        report.setdefault("scale_down", []).append(
            {"resource": r, "cmd": res.cmd, "exit_code": res.exit_code, "stdout": (res.stdout or "").strip()[:200], "stderr": (res.stderr or "").strip()[:200]}
        )
        if res.exit_code != 0:
            report["ok"] = False
            report["error"] = "scale_down_failed"

    if not bool(report["ok"]):
        print(json.dumps(report, ensure_ascii=False))
        return 1

    # 3) Hold outage window
    report["outage_started_at"] = _utc_now_iso()
    time.sleep(float(down_seconds))
    report["outage_ended_at"] = _utc_now_iso()

    # 4) Restore replicas (best-effort)
    for r, kind, name, replicas in originals:
        res = _scale(namespace=namespace, kind=kind, name=name, replicas=replicas)
        report.setdefault("scale_up", []).append(
            {"resource": r, "cmd": res.cmd, "exit_code": res.exit_code, "stdout": (res.stdout or "").strip()[:200], "stderr": (res.stderr or "").strip()[:200]}
        )
        if res.exit_code != 0:
            report["ok"] = False
            report["error"] = "scale_up_failed"

    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
