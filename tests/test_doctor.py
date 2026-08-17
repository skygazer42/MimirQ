
from pathlib import Path

from scripts import doctor


def test_doctor_main_preserves_probe_order_warnings_and_file_based_exit(monkeypatch, capsys) -> None:
    command_calls: list[tuple[str, tuple[str, ...], bool]] = []
    file_calls: list[tuple[str, bool]] = []

    def fake_check_cmd(name: str, command: list[str], *, required: bool = True) -> bool:
        command_calls.append((name, tuple(command), required))
        return False

    def fake_check_file(path: Path, *, required: bool) -> bool:
        file_calls.append((path.as_posix(), required))
        return not path.as_posix().endswith("web/package.json")

    def fake_run(command: list[str]) -> tuple[int, str]:
        if command == ["docker", "ps"]:
            return 1, "daemon unavailable"
        return 0, "input"

    monkeypatch.setattr(doctor, "_check_cmd", fake_check_cmd)
    monkeypatch.setattr(doctor, "_check_file", fake_check_file)
    monkeypatch.setattr(doctor, "_run", fake_run)
    monkeypatch.setattr(doctor.platform, "system", lambda: "Windows")
    monkeypatch.setattr(doctor.platform, "release", lambda: "test-release")
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/bin/tool")
    monkeypatch.setattr(Path, "exists", lambda _path: True)

    assert doctor.main() == 1

    assert [name for name, _command, _required in command_calls] == [
        "Node",
        "pnpm",
        "Git (optional)",
        "Make (optional)",
        "Docker",
        "Docker Compose",
        "Ruff (optional)",
        "pip-audit (optional)",
    ]
    assert [required for _path, required in file_calls] == [True, True, True, True, False, False]
    output = capsys.readouterr().out
    assert "Docker CLI is installed but the daemon may not be running" in output
    assert "git core.autocrlf is enabled" in output
    assert "Create env files" not in output
    assert "On Windows without make" in output


def test_doctor_main_keeps_command_failures_advisory_and_prints_missing_env_hints(monkeypatch, capsys) -> None:
    monkeypatch.setattr(doctor, "_check_cmd", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(doctor, "_check_file", lambda _path, *, required: required)
    monkeypatch.setattr(doctor.platform, "system", lambda: "Linux")
    monkeypatch.setattr(doctor.platform, "release", lambda: "test-release")
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)
    monkeypatch.setattr(Path, "exists", lambda _path: False)

    assert doctor.main() == 0

    output = capsys.readouterr().out
    assert "Create env files" in output
    assert "pnpm not on PATH" in output
    assert "On Windows without make" not in output
