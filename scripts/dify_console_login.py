#!/usr/bin/env python3
"""Refresh a Dify console storage_state file without printing secrets."""


import argparse
import base64
import binascii
import json
import os
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_CONSOLE_BASE_URL = "https://dify.example.com:5001/console/api"
DEFAULT_CONSOLE_ORIGIN = "https://dify.example.com:3000"
DEFAULT_STORAGE_STATE = "/tmp/dify_console_storage_state.json"

RequestJsonFn = Callable[..., dict[str, Any]]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def extract_console_token(payload: dict[str, Any]) -> str:
    """Extract a Dify console token from common nested login response shapes."""
    for key in ("access_token", "token", "console_token"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    for value in payload.values():
        if isinstance(value, dict):
            found = extract_console_token(value)
            if found:
                return found
    return ""


def build_storage_state(*, console_origin: str, console_token: str) -> dict[str, Any]:
    return {
        "cookies": [],
        "origins": [
            {
                "origin": _text(console_origin),
                "localStorage": [{"name": "console_token", "value": console_token}],
            }
        ],
    }


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = _text(token).split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        value = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _load_console_token_from_storage_state(storage_state: str | os.PathLike[str]) -> str:
    state_path = Path(storage_state)
    if not state_path.is_file():
        return ""
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    for origin in payload.get("origins") or []:
        if not isinstance(origin, dict):
            continue
        for item in origin.get("localStorage") or []:
            if isinstance(item, dict) and item.get("name") == "console_token":
                return _text(item.get("value"))
    return ""


def check_storage_state(
    *,
    storage_state: str | os.PathLike[str],
    min_ttl_seconds: int,
    now: int | None = None,
) -> dict[str, Any]:
    token = _load_console_token_from_storage_state(storage_state)
    if not token:
        return {"valid": False, "reason": "missing_token", "storage_state": str(storage_state)}
    payload = _decode_jwt_payload(token)
    exp = payload.get("exp")
    if not isinstance(exp, int):
        return {"valid": False, "reason": "missing_exp", "storage_state": str(storage_state)}
    current = int(time.time() if now is None else now)
    ttl_seconds = exp - current
    if ttl_seconds <= 0:
        return {
            "valid": False,
            "reason": "token_expired",
            "storage_state": str(storage_state),
            "ttl_seconds": ttl_seconds,
            "min_ttl_seconds": int(min_ttl_seconds),
        }
    if ttl_seconds < int(min_ttl_seconds):
        return {
            "valid": False,
            "reason": "token_expires_soon",
            "storage_state": str(storage_state),
            "ttl_seconds": ttl_seconds,
            "min_ttl_seconds": int(min_ttl_seconds),
        }
    return {
        "valid": True,
        "reason": "ok",
        "storage_state": str(storage_state),
        "ttl_seconds": ttl_seconds,
        "min_ttl_seconds": int(min_ttl_seconds),
    }


def _request_json(
    *,
    console_base_url: str,
    path: str,
    method: str,
    payload: dict[str, Any] | None,
    console_token: str,
    timeout: float,
) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if console_token:
        headers["Authorization"] = f"Bearer {console_token}"
    request = Request(
        f"{console_base_url.rstrip('/')}/{path.lstrip('/')}",
        data=data,
        method=method,
        headers=headers,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:800]}") from exc
    except URLError as exc:
        raise RuntimeError(f"request failed: {exc}") from exc


def _load_password(*, password: str, password_file: str) -> str:
    explicit = _text(password)
    if explicit:
        return explicit
    file_path = Path(_text(password_file))
    if file_path.is_file():
        return file_path.read_text(encoding="utf-8").strip()
    return ""


def refresh_storage_state(
    *,
    console_base_url: str,
    console_origin: str,
    email: str,
    password: str,
    storage_state: str | os.PathLike[str],
    request_json: RequestJsonFn = _request_json,
    timeout: float = 30.0,
) -> dict[str, str]:
    login_payload = {"email": _text(email), "password": password, "remember_me": True}
    login_response = request_json(
        console_base_url=console_base_url,
        path="/login",
        method="POST",
        payload=login_payload,
        console_token="",
        timeout=timeout,
    )
    console_token = extract_console_token(login_response)
    if not console_token:
        raise RuntimeError("Dify login response did not contain a console token")

    profile = request_json(
        console_base_url=console_base_url,
        path="/account/profile",
        method="GET",
        payload=None,
        console_token=console_token,
        timeout=timeout,
    )

    state_path = Path(storage_state)
    state_path.write_text(
        json.dumps(
            build_storage_state(console_origin=console_origin, console_token=console_token),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "storage_state": str(state_path),
        "profile_email": _text(profile.get("email")),
        "profile_id": _text(profile.get("id")),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh a Dify console Playwright storage_state file.")
    parser.add_argument("--console-base-url", default=os.getenv("DIFY_CONSOLE_API_BASE_URL") or DEFAULT_CONSOLE_BASE_URL)
    parser.add_argument("--console-origin", default=os.getenv("DIFY_CONSOLE_ORIGIN") or DEFAULT_CONSOLE_ORIGIN)
    parser.add_argument("--email", default=os.getenv("DIFY_CONSOLE_EMAIL") or "")
    parser.add_argument("--password", default=os.getenv("DIFY_CONSOLE_PASSWORD") or "")
    parser.add_argument("--password-file", default=os.getenv("DIFY_CONSOLE_PASSWORD_FILE") or "")
    parser.add_argument("--storage-state", default=DEFAULT_STORAGE_STATE)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--check", action="store_true", help="Validate the existing storage_state token without logging in.")
    parser.add_argument("--min-ttl-seconds", type=int, default=900)
    parser.add_argument("--out", default="", help="Optional JSON report path.")
    return parser


def _emit_report(report: dict[str, Any], out: str) -> None:
    safe_report = dict(report)
    safe_report.setdefault("generated_at", _utc_now_text())
    text = json.dumps(safe_report, ensure_ascii=False, indent=2)
    if _text(out):
        Path(_text(out)).write_text(text + "\n", encoding="utf-8")
    print(text)


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if bool(args.check):
        report = check_storage_state(
            storage_state=str(args.storage_state),
            min_ttl_seconds=int(args.min_ttl_seconds),
        )
        if report.get("valid") is not True:
            report["hint"] = (
                "Refresh Dify console login with "
                "DIFY_CONSOLE_EMAIL=<email> DIFY_CONSOLE_PASSWORD_FILE=/tmp/dify_console_password.txt "
                "make dify-console-login."
            )
        _emit_report(report, str(args.out))
        return 0 if report.get("valid") is True else 1
    email = _text(args.email)
    password = _load_password(password=str(args.password), password_file=str(args.password_file))
    if not email:
        print("DIFY_CONSOLE_EMAIL or --email is required", file=sys.stderr)
        return 2
    if not password:
        print("DIFY_CONSOLE_PASSWORD, --password, or --password-file is required", file=sys.stderr)
        return 2
    try:
        report = refresh_storage_state(
            console_base_url=str(args.console_base_url),
            console_origin=str(args.console_origin),
            email=email,
            password=password,
            storage_state=str(args.storage_state),
            request_json=_request_json,
            timeout=float(args.timeout),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[dify-console-login] ERR: {exc}", file=sys.stderr)
        return 1
    check_report = check_storage_state(
        storage_state=str(args.storage_state),
        min_ttl_seconds=int(args.min_ttl_seconds),
    )
    report = {**report, **check_report}
    _emit_report(report, str(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
