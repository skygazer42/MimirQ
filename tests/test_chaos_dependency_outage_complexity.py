import json
from typing import Any

import pytest

from scripts import chaos_dependency_outage as outage


def _output(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    return json.loads(capsys.readouterr().out)


def test_main_rejects_invalid_resource_without_kubectl(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        outage,
        "_get_replicas",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("kubectl must not run")),
    )

    assert outage.main(["--namespace", "infra", "--resource", "pod/Redis"]) == 2
    assert _output(capsys) == {
        "ok": False,
        "error": "invalid_resource",
        "resources": ["pod/Redis"],
    }


def test_main_dry_run_reports_original_replicas(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = outage.CmdResult(
        cmd=["kubectl", "get"],
        exit_code=0,
        stdout=" 3 \n",
        stderr="",
    )
    monkeypatch.setattr(outage, "_utc_now_iso", lambda: "2026-08-17T00:00:00+00:00")
    monkeypatch.setattr(outage, "_get_replicas", lambda **_kwargs: (3, command))
    monkeypatch.setattr(
        outage,
        "_scale",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("dry-run must not scale")),
    )

    assert outage.main(["--namespace", "infra", "--resource", "deployment/redis"]) == 0

    assert _output(capsys) == {
        "schema": "mimirq.chaos_dependency_outage.v1",
        "ran_at": "2026-08-17T00:00:00+00:00",
        "namespace": "infra",
        "execute": False,
        "down_seconds": 120,
        "targets": [
            {
                "resource": "deployment/redis",
                "original_replicas": 3,
                "get_replicas": {
                    "cmd": ["kubectl", "get"],
                    "exit_code": 0,
                    "stdout": "3",
                    "stderr": "",
                },
            }
        ],
        "ok": True,
    }


def test_main_execute_scales_down_sleeps_and_restores(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    timestamps = iter(["ran", "started", "ended"])
    scale_calls: list[int] = []
    sleeps: list[float] = []
    get_result = outage.CmdResult(cmd=["get"], exit_code=0, stdout="2", stderr="")

    def scale(*, replicas: int, **_kwargs: Any) -> outage.CmdResult:
        scale_calls.append(replicas)
        return outage.CmdResult(cmd=["scale", str(replicas)], exit_code=0, stdout="scaled", stderr="")

    monkeypatch.setattr(outage, "_utc_now_iso", lambda: next(timestamps))
    monkeypatch.setattr(outage, "_get_replicas", lambda **_kwargs: (2, get_result))
    monkeypatch.setattr(outage, "_scale", scale)
    monkeypatch.setattr(outage.time, "sleep", sleeps.append)

    assert (
        outage.main(
            [
                "--namespace",
                "infra",
                "--resource",
                "statefulset/milvus",
                "--down-seconds",
                "7",
                "--execute",
            ]
        )
        == 0
    )

    payload = _output(capsys)
    assert scale_calls == [0, 2]
    assert sleeps == [7.0]
    assert payload["outage_started_at"] == "started"
    assert payload["outage_ended_at"] == "ended"
    assert payload["scale_down"][0]["resource"] == "statefulset/milvus"
    assert payload["scale_up"][0]["resource"] == "statefulset/milvus"
