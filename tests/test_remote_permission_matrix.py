from __future__ import annotations

from types import SimpleNamespace

import scripts.remote_permission_matrix as permissions_mod
from scripts.remote_permission_matrix import build_case_result, force_member_role_via_docker, status_matches_expected


def test_remote_permission_matrix_status_matches_expected() -> None:
    assert status_matches_expected(200, [200]) is True
    assert status_matches_expected(403, [401, 403]) is True
    assert status_matches_expected(404, [401, 403]) is False


def test_remote_permission_matrix_build_case_result_marks_failure_outside_expected() -> None:
    result = build_case_result("outsider_settings", status=404, body={"detail": "nope"}, elapsed=0.123, expected_statuses=[401, 403])

    assert result["name"] == "outsider_settings"
    assert result["ok"] is False
    assert result["status_code"] == 404
    assert "response" in result


def test_remote_permission_matrix_force_member_role_uses_psql_update(monkeypatch) -> None:  # noqa: ANN001
    calls: list[dict[str, object]] = []

    def _fake_run(cmd, **kwargs):  # noqa: ANN001
        calls.append({"cmd": cmd, "kwargs": kwargs})
        return SimpleNamespace(returncode=0, stdout="UPDATE 1\n", stderr="")

    monkeypatch.setattr(permissions_mod.subprocess, "run", _fake_run)

    ok, output = force_member_role_via_docker(
        tenant_id="00000000-0000-0000-0000-000000000000",
        account_id="outsider",
        role="viewer",
    )

    assert ok is True
    assert "UPDATE 1" in output
    assert calls
    cmd = calls[0]["cmd"]
    assert cmd[:6] == ["docker", "exec", "-i", "docker-mimirq-postgres-1", "psql", "-U"]
