import csv
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import dify_console_login
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

    assert "secret-token" in json.dumps(json.loads(state_path.read_text(encoding="utf-8")))
    if os.name == "nt":
        system_tools = Path(os.environ["SystemRoot"]) / "System32"
        identity = subprocess.check_output(
            [system_tools / "whoami.exe", "/user", "/fo", "csv", "/nh"],
            encoding="oem",
        )
        account, _ = next(csv.reader(identity.splitlines()))
        acl = subprocess.check_output([system_tools / "icacls.exe", state_path], encoding="oem")
        assert "(I)" not in acl
        assert acl.count(":(F)") == 1
        assert f"{account.casefold()}:(f)" in acl.casefold()
    else:
        assert stat.S_IMODE(state_path.stat().st_mode) == 0o600


def test_storage_state_publish_failure_keeps_previous_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("previous state", encoding="utf-8")

    def deny_replace(_source: Path, _destination: Path) -> None:
        raise PermissionError("publication denied")

    monkeypatch.setattr(dify_console_login.os, "replace", deny_replace)
    with pytest.raises(PermissionError, match="publication denied"):
        dify_console_login._write_private_text(state_path, "new state")
    assert state_path.read_text(encoding="utf-8") == "previous state"
    assert list(tmp_path.iterdir()) == [state_path]
