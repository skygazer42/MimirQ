
import argparse
import ipaddress
import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_iso_timestamp() -> str:
    # `datetime.UTC` is only available on Python 3.11+.
    return datetime.now(timezone.utc).isoformat()


def _read_env_file(path: Path) -> dict[str, str]:
    """
    Minimal .env parser (best-effort).

    - Ignores comments/blank lines
    - Does not implement full dotenv quoting/expansion rules
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    parsed: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def _coerce_int(value: str | None, *, default: int) -> int:
    if value is None:
        return default
    try:
        return int(str(value).strip())
    except ValueError:
        return default


def _run_command(cmd: list[str], *, cwd: Path) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return 127, "", f"{type(exc).__name__}: {exc}"

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    return int(proc.returncode), stdout, stderr


def _parse_ps_output(output: str) -> list[dict[str, Any]]:
    """
    docker compose ps --format json returns JSONL (one object per line) in recent versions.

    Return a list of parsed objects (best-effort).
    """
    output = (output or "").strip()
    if not output:
        return []

    if output.startswith("["):
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        return []

    items: list[dict[str, Any]] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            items.append(parsed)
    return items


def _collect_services_from_compose(
    *,
    repo_root: Path,
    compose_file: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    cmd = ["docker", "compose", "-f", compose_file, "ps", "--format", "json"]
    exit_code, stdout, stderr = _run_command(cmd, cwd=repo_root)
    if exit_code != 0:
        return {}, {"command": cmd, "exit_code": exit_code, "stderr": (stderr or "").strip()[:800]}

    services: dict[str, Any] = {}
    for item in _parse_ps_output(stdout):
        service = str(item.get("Service") or "").strip()
        if not service:
            continue

        services[service] = {
            "state": item.get("State") or "",
            "status": item.get("Status") or "",
            "health": item.get("Health") or "",
            "container": item.get("Name") or "",
            "image": item.get("Image") or "",
        }
    return services, None


def _collect_ports_from_compose(
    *,
    repo_root: Path,
    compose_file: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    cmd = ["docker", "compose", "-f", compose_file, "ps", "--format", "json"]
    exit_code, stdout, stderr = _run_command(cmd, cwd=repo_root)
    if exit_code != 0:
        return {}, {"command": cmd, "exit_code": exit_code, "stderr": (stderr or "").strip()[:800]}

    ports: dict[str, Any] = {}
    for item in _parse_ps_output(stdout):
        service = str(item.get("Service") or "").strip()
        if not service:
            continue

        publishers = item.get("Publishers")
        if not isinstance(publishers, list):
            continue

        published: list[dict[str, Any]] = []
        for pub in publishers:
            if not isinstance(pub, dict):
                continue
            published_port = pub.get("PublishedPort")
            try:
                published_port_int = int(published_port)
            except (TypeError, ValueError):
                published_port_int = 0
            if published_port_int <= 0:
                continue
            published.append(
                {
                    "url": pub.get("URL") or "",
                    "target_port": pub.get("TargetPort") or 0,
                    "published_port": published_port_int,
                    "protocol": pub.get("Protocol") or "",
                }
            )

        if published:
            ports[service] = published
    return ports, None


def _check_backend_ready(*, url: str, timeout_sec: float) -> dict[str, Any]:
    result: dict[str, Any] = {"url": url, "ok": False}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mimirq-compose-diagnostics/1.0"})
        host = (urllib.parse.urlsplit(url).hostname or "").rstrip(".").lower()
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = host == "localhost"
        open_url = (
            urllib.request.build_opener(urllib.request.ProxyHandler({})).open
            if is_loopback
            else urllib.request.urlopen
        )
        with open_url(req, timeout=timeout_sec) as res:  # noqa: S310
            body = res.read()
            status = int(getattr(res, "status", 200))
            result["status_code"] = status
            if body:
                try:
                    result["body"] = json.loads(body.decode("utf-8"))
                except Exception:  # noqa: BLE001
                    result["body"] = body[:500].decode("utf-8", errors="replace")
            result["ok"] = status == 200
    except urllib.error.HTTPError as exc:
        result["status_code"] = int(getattr(exc, "code", 0) or 0)
        result["error"] = f"HTTPError: {exc}"
    except urllib.error.URLError as exc:
        result["error"] = f"URLError: {exc}"
    except TimeoutError as exc:
        result["error"] = f"TimeoutError: {exc}"
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print a condensed Docker Compose diagnostics report as JSON.")
    parser.add_argument(
        "--compose-file",
        default="docker/docker-compose.yml",
        help="Compose file to inspect (default: docker/docker-compose.yml).",
    )
    parser.add_argument(
        "--skip-docker",
        action="store_true",
        help="Skip docker compose inspection (useful in CI).",
    )
    parser.add_argument(
        "--skip-health",
        action="store_true",
        help="Skip backend readiness HTTP check.",
    )
    parser.add_argument(
        "--base-url",
        default="",
        help="Override backend base URL (default: inferred from root .env BACKEND_PORT).",
    )
    parser.add_argument(
        "--timeout-sec",
        default="2.0",
        help="Timeout for health checks (seconds).",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    compose_file = str(args.compose_file)

    report: dict[str, Any] = {
        "ts": _utc_iso_timestamp(),
        "compose_file": compose_file,
        "services": {},
        "ports": {},
        "health": {},
        "errors": [],
    }

    if not bool(args.skip_docker):
        services, service_error = _collect_services_from_compose(repo_root=repo_root, compose_file=compose_file)
        ports, ports_error = _collect_ports_from_compose(repo_root=repo_root, compose_file=compose_file)
        report["services"] = services
        report["ports"] = ports
        if service_error:
            report["errors"].append({"kind": "docker_ps_services", **service_error})
        if ports_error:
            report["errors"].append({"kind": "docker_ps_ports", **ports_error})

    if not bool(args.skip_health):
        env = _read_env_file(repo_root / ".env")
        backend_port = _coerce_int(env.get("BACKEND_PORT"), default=8000)
        base_url = str(args.base_url).strip() or f"http://localhost:{backend_port}"
        report["health"] = _check_backend_ready(url=f"{base_url}/api/v1/health/ready", timeout_sec=float(args.timeout_sec))

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
