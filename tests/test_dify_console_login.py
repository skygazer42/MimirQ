import stat
from pathlib import Path
from typing import Any

from scripts.dify_console_login import refresh_storage_state


def test_refresh_storage_state_restricts_token_file_permissions(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("stale", encoding="utf-8")
    state_path.chmod(0o644)

    def request_json(**kwargs: Any) -> dict[str, Any]:
        if kwargs["path"] == "/login":
            return {"access_token": "secret-token"}
        return {"email": "user@example.com", "id": "user-1"}

    refresh_storage_state(
        console_base_url="https://dify.example.com/console/api",
        console_origin="https://dify.example.com",
        email="user@example.com",
        password="password",
        storage_state=state_path,
        request_json=request_json,
    )

    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
