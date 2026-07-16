
import argparse
import ipaddress
import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener, urlopen


def _strip_trailing_slashes(value: str) -> str:
    return (value or "").strip().rstrip("/")


def _join_url(base: str, path: str) -> str:
    b = _strip_trailing_slashes(base)
    p = (path or "").strip()
    if not p:
        return b
    if not p.startswith("/"):
        p = f"/{p}"
    return f"{b}{p}"


@dataclass(frozen=True)
class PingResult:
    url: str
    status_code: int | None
    elapsed_ms: int
    data: Any | None
    error: str | None


def _read_json(url: str, *, timeout_sec: float) -> PingResult:
    start = time.perf_counter()
    try:
        req = Request(url, headers={"Accept": "application/json"})
        host = (urlsplit(url).hostname or "").rstrip(".").lower()
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = host == "localhost"
        open_url = build_opener(ProxyHandler({})).open if is_loopback else urlopen
        with open_url(req, timeout=timeout_sec) as resp:
            body = resp.read() or b""
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            content_type = (resp.headers.get("Content-Type") or "").lower()
            if "application/json" in content_type:
                try:
                    parsed = json.loads(body.decode("utf-8"))
                except Exception:  # noqa: BLE001
                    parsed = body.decode("utf-8", errors="replace")
                return PingResult(url=url, status_code=resp.status, elapsed_ms=elapsed_ms, data=parsed, error=None)

            text = body.decode("utf-8", errors="replace")
            return PingResult(url=url, status_code=resp.status, elapsed_ms=elapsed_ms, data=text, error=None)
    except HTTPError as exc:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        body = exc.read() if hasattr(exc, "read") else b""
        parsed: Any | None = None
        if body:
            try:
                parsed = json.loads(body.decode("utf-8"))
            except Exception:  # noqa: BLE001
                parsed = body.decode("utf-8", errors="replace")
        return PingResult(
            url=url,
            status_code=getattr(exc, "code", None),
            elapsed_ms=elapsed_ms,
            data=parsed,
            error=f"HTTPError: {getattr(exc, 'code', 'unknown')}",
        )
    except URLError as exc:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return PingResult(url=url, status_code=None, elapsed_ms=elapsed_ms, data=None, error=f"URLError: {exc}")


def _summarize_data(value: Any | None) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False)[:300]
        except Exception:  # noqa: BLE001
            return str(value)[:300]
    return str(value)[:300]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ping MimirQ backend health endpoints for quick FE/BE connectivity checks."
    )
    parser.add_argument(
        "--base-url",
        default=_strip_trailing_slashes(os.getenv("BACKEND_BASE_URL") or "http://localhost:8000"),
        help="Backend base URL (default: env BACKEND_BASE_URL or http://localhost:8000)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("API_PING_TIMEOUT_SEC") or "1.5"),
        help="Timeout per request in seconds (default: 1.5)",
    )
    args = parser.parse_args()

    base_url = _strip_trailing_slashes(str(args.base_url))
    timeout_sec = float(args.timeout)

    targets = [
        ("/api/v1/health", "health"),
        ("/api/v1/health/ready", "ready"),
        ("/api/v1/meta", "meta"),
    ]

    ok = True
    for path, label in targets:
        url = _join_url(base_url, path)
        result = _read_json(url, timeout_sec=timeout_sec)
        code = result.status_code
        status = "OK" if code and 200 <= code < 300 else "ERR"
        if status != "OK":
            ok = False

        extra = _summarize_data(result.data)
        extra_part = f"  {extra}" if extra else ""
        err_part = f"  ({result.error})" if result.error else ""
        print(f"[api-ping] {status}: {label}  {code if code is not None else '-'}  {result.elapsed_ms}ms  {url}{err_part}{extra_part}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
