import base64
import json
import time
from pathlib import Path
from typing import Any

from scripts import dify_console_login as mod


def _jwt_with_exp(exp: int) -> str:
    def encode(payload: dict[str, Any]) -> str:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

    return f"{encode({'alg': 'none'})}.{encode({'exp': exp})}."


def test_extract_console_token_accepts_nested_dify_login_response() -> None:
    payload = {"result": "success", "data": {"access_token": "console-token"}}

    assert mod.extract_console_token(payload) == "console-token"


def test_build_storage_state_uses_playwright_local_storage_shape() -> None:
    state = mod.build_storage_state(console_origin="https://dify.example.com:3000", console_token="console-token")

    assert state == {
        "cookies": [],
        "origins": [
            {
                "origin": "https://dify.example.com:3000",
                "localStorage": [{"name": "console_token", "value": "console-token"}],
            }
        ],
    }


def test_check_storage_state_reports_valid_expiring_and_expired_tokens(tmp_path: Path) -> None:
    now = int(time.time())
    valid_state = tmp_path / "valid.json"
    expiring_state = tmp_path / "expiring.json"
    expired_state = tmp_path / "expired.json"
    valid_state.write_text(
        json.dumps(
            mod.build_storage_state(
                console_origin="https://dify.example.com:3000",
                console_token=_jwt_with_exp(now + 1800),
            )
        ),
        encoding="utf-8",
    )
    expiring_state.write_text(
        json.dumps(
            mod.build_storage_state(
                console_origin="https://dify.example.com:3000",
                console_token=_jwt_with_exp(now + 60),
            )
        ),
        encoding="utf-8",
    )
    expired_state.write_text(
        json.dumps(
            mod.build_storage_state(
                console_origin="https://dify.example.com:3000",
                console_token=_jwt_with_exp(now - 60),
            )
        ),
        encoding="utf-8",
    )

    assert mod.check_storage_state(storage_state=valid_state, min_ttl_seconds=600)["valid"] is True
    assert mod.check_storage_state(storage_state=expiring_state, min_ttl_seconds=600)["valid"] is False
    assert mod.check_storage_state(storage_state=expiring_state, min_ttl_seconds=600)["reason"] == "token_expires_soon"
    assert mod.check_storage_state(storage_state=expired_state, min_ttl_seconds=600)["reason"] == "token_expired"


def test_check_storage_state_handles_missing_malformed_and_non_jwt_state(tmp_path: Path) -> None:
    missing_state = tmp_path / "missing.json"
    malformed_state = tmp_path / "malformed.json"
    non_jwt_state = tmp_path / "non-jwt.json"
    malformed_state.write_text("{", encoding="utf-8")
    non_jwt_state.write_text(
        json.dumps(
            mod.build_storage_state(
                console_origin="https://dify.example.com:3000",
                console_token="not-a-jwt",
            )
        ),
        encoding="utf-8",
    )

    assert mod.check_storage_state(storage_state=missing_state, min_ttl_seconds=600)["reason"] == "missing_token"
    assert mod.check_storage_state(storage_state=malformed_state, min_ttl_seconds=600)["reason"] == "missing_token"
    assert mod.check_storage_state(storage_state=non_jwt_state, min_ttl_seconds=600)["reason"] == "missing_exp"


def test_refresh_storage_state_logs_in_validates_profile_and_writes_state(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def fake_request_json(
        *,
        console_base_url: str,
        path: str,
        method: str,
        payload: dict[str, Any] | None,
        console_token: str,
        timeout: float,
    ) -> dict[str, Any]:
        calls.append(
            {
                "console_base_url": console_base_url,
                "path": path,
                "method": method,
                "payload": payload,
                "console_token": console_token,
                "timeout": timeout,
            }
        )
        if path == "/login":
            assert payload == {"email": "operator@example.com", "password": "secret", "remember_me": True}
            assert console_token == ""
            return {"data": {"access_token": "console-token"}}
        if path == "/account/profile":
            assert console_token == "console-token"
            return {"email": "operator@example.com", "id": "account-id"}
        raise AssertionError(path)

    storage_state = tmp_path / "state.json"

    report = mod.refresh_storage_state(
        console_base_url="https://dify.example.com:5001/console/api",
        console_origin="https://dify.example.com:3000",
        email="operator@example.com",
        password="secret",
        storage_state=storage_state,
        request_json=fake_request_json,
        timeout=12.0,
    )

    assert report == {
        "storage_state": str(storage_state),
        "profile_email": "operator@example.com",
        "profile_id": "account-id",
    }
    assert [call["path"] for call in calls] == ["/login", "/account/profile"]
    assert json.loads(storage_state.read_text(encoding="utf-8")) == mod.build_storage_state(
        console_origin="https://dify.example.com:3000",
        console_token="console-token",
    )
