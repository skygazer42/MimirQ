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

_RESOURCE_RE = re.compile(
    r"^(deployment|statefulset|daemonset|replicaset|job|cronjob)/[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"
)


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


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Chaos helper: scale dependencies down/up (kubectl).")
    p.add_argument("--namespace", required=True, help="Kubernetes namespace where dependencies run.")
    p.add_argument(
        "--resource",
        action="append",
        default=[],
        help="Target resource in kind/name form (repeatable), e.g. deployment/redis or statefulset/milvus.",
    )
    p.add_argument(
        "--down-seconds", type=int, default=120, help="How long to keep resources at 0 replicas (default: 120)."
    )
    p.add_argument("--execute", action="store_true", help="Actually run kubectl scale (default: dry-run).")
    return p


def _command_payload(result: CmdResult) -> dict[str, Any]:
    return {
        "cmd": result.cmd,
        "exit_code": result.exit_code,
        "stdout": (result.stdout or "").strip()[:200],
        "stderr": (result.stderr or "").strip()[:200],
    }


def _read_originals(
    *,
    namespace: str,
    resources: list[str],
    report: dict[str, Any],
) -> list[tuple[str, str, str, int]]:
    originals: list[tuple[str, str, str, int]] = []
    for resource in resources:
        kind, name = resource.split("/", 1)
        replicas, result = _get_replicas(namespace=namespace, kind=kind, name=name)
        report["targets"].append(
            {
                "resource": resource,
                "original_replicas": replicas,
                "get_replicas": _command_payload(result),
            }
        )
        if replicas is None:
            report["ok"] = False
            report["error"] = "failed_to_read_replicas"
        else:
            originals.append((resource, kind, name, replicas))
    return originals


def _scale_phase(
    *,
    namespace: str,
    originals: list[tuple[str, str, str, int]],
    report: dict[str, Any],
    phase: str,
    restore: bool,
) -> bool:
    for resource, kind, name, original_replicas in originals:
        replicas = original_replicas if restore else 0
        result = _scale(namespace=namespace, kind=kind, name=name, replicas=replicas)
        report.setdefault(phase, []).append({"resource": resource, **_command_payload(result)})
        if result.exit_code != 0:
            report["ok"] = False
            report["error"] = f"{phase}_failed"
    return bool(report["ok"])


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    namespace = str(args.namespace or "").strip()
    resources = [str(resource or "").strip() for resource in (args.resource or []) if str(resource or "").strip()]
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

    originals = _read_originals(namespace=namespace, resources=resources, report=report)

    if not bool(report["ok"]):
        print(json.dumps(report, ensure_ascii=False))
        return 1

    if not execute:
        print(json.dumps(report, ensure_ascii=False))
        return 0

    if not _scale_phase(
        namespace=namespace,
        originals=originals,
        report=report,
        phase="scale_down",
        restore=False,
    ):
        print(json.dumps(report, ensure_ascii=False))
        return 1

    report["outage_started_at"] = _utc_now_iso()
    time.sleep(float(down_seconds))
    report["outage_ended_at"] = _utc_now_iso()

    _scale_phase(
        namespace=namespace,
        originals=originals,
        report=report,
        phase="scale_up",
        restore=True,
    )

    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
