import json
from pathlib import Path
from typing import Any

from scripts import dify_console_login as mod


def test_extract_console_token_accepts_nested_dify_login_response() -> None:
    payload = {"result": "success", "data": {"access_token": "console-token"}}

    assert mod.extract_console_token(payload) == "console-token"


def test_build_storage_state_uses_playwright_local_storage_shape() -> None:
    state = mod.build_storage_state(console_origin="https://ai.kingdonsoft.com:3000", console_token="console-token")

    assert state == {
        "cookies": [],
        "origins": [
            {
                "origin": "https://ai.kingdonsoft.com:3000",
                "localStorage": [{"name": "console_token", "value": "console-token"}],
            }
        ],
    }


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
        console_base_url="https://ai.kingdonsoft.com:5001/console/api",
        console_origin="https://ai.kingdonsoft.com:3000",
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
        console_origin="https://ai.kingdonsoft.com:3000",
        console_token="console-token",
    )
