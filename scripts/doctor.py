import locale
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def _decode_output(data: bytes) -> str:
    if not data:
        return ""

    # Some Windows environments default to GBK/CP936, while many CLIs output UTF-8.
    # Decode defensively to avoid crashing `doctor` on mixed/unknown encodings.
    preferred = (locale.getpreferredencoding(False) or "").strip()
    candidates = ["utf-8"]
    if preferred and preferred.lower() not in {"utf-8", "utf8"}:
        candidates.append(preferred)
    # Windows-specific fallback (safe no-op on non-Windows where it's unsupported).
    candidates.append("mbcs")

    for enc in candidates:
        try:
            return data.decode(enc)
        except Exception:  # noqa: BLE001
            continue

    return data.decode("utf-8", errors="replace")


def _run(cmd: list[str]) -> tuple[int, str]:
    exe = shutil.which(cmd[0])
    if exe is None:
        return 127, ""

    # Capture bytes and decode ourselves; `text=True` can raise UnicodeDecodeError on Windows.
    result = subprocess.run([exe, *cmd[1:]], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out_bytes = (result.stdout or b"").strip() or (result.stderr or b"").strip()
    out = _decode_output(out_bytes).strip()
    return result.returncode, out


def _check_cmd(name: str, cmd: list[str], *, required: bool = True) -> bool:
    code, out = _run(cmd)
    if code == 127:
        level = "MISSING" if required else "WARN"
        print(f"[doctor] {level}: {name} ({cmd[0]} not found)")
        return not required
    status = "OK" if code == 0 else f"ERR({code})"
    extra = f": {out}" if out else ""
    print(f"[doctor] {status}: {name}{extra}")
    return code == 0


def _check_file(path: Path, *, required: bool) -> bool:
    if path.exists():
        print(f"[doctor] OK: file {path.as_posix()}")
        return True
    level = "MISSING" if required else "WARN"
    print(f"[doctor] {level}: file {path.as_posix()}")
    return not required


def _print_environment_header(repo_root: Path) -> str:
    os_name = platform.system()
    print(f"[doctor] OS: {os_name} ({platform.release()})")
    print(f"[doctor] Repo: {repo_root.as_posix()}")

    version = sys.version_info
    print(
        f"[doctor] OK: Python runtime ({Path(sys.executable).as_posix()}): "
        f"Python {version.major}.{version.minor}.{version.micro}"
    )
    if (version.major, version.minor) < (3, 11):
        print(
            f"[doctor] WARN: active Python is {version.major}.{version.minor}.{version.micro} "
            "(MimirQ requires Python 3.11+ for local backend)"
        )
    return os_name


def _check_tool_commands() -> None:
    _check_cmd("Node", ["node", "--version"])
    _check_cmd("pnpm", ["pnpm", "--version"])
    _check_cmd("Git (optional)", ["git", "--version"], required=False)
    _check_cmd("Make (optional)", ["make", "--version"], required=False)
    _check_cmd("Docker", ["docker", "--version"])
    _check_cmd("Docker Compose", ["docker", "compose", "version"])
    _check_cmd("Ruff (optional)", ["ruff", "--version"], required=False)
    _check_cmd("pip-audit (optional)", ["pip-audit", "--version"], required=False)


def _warn_if_docker_daemon_unavailable() -> None:
    if shutil.which("docker") is not None:
        code, _out = _run(["docker", "ps"])
        if code != 0:
            print(
                "[doctor] WARN: Docker CLI is installed but the daemon may not be "
                "running (try starting Docker Desktop)."
            )


def _warn_if_git_converts_line_endings() -> None:
    if shutil.which("git") is not None:
        code, out = _run(["git", "config", "--get", "core.autocrlf"])
        if code == 0 and (out or "").strip().lower() in {"true", "input"}:
            print(
                "[doctor] WARN: git core.autocrlf is enabled; consider disabling to "
                "reduce CRLF/LF churn (repo enforces LF via .gitattributes)."
            )


def _required_files_ok(repo_root: Path) -> bool:
    ok = True
    for relative_path in (
        "docker/docker-compose.yml",
        "docker/docker-compose.web.yml",
        "web/package.json",
        "app/main.py",
    ):
        ok &= _check_file(repo_root / relative_path, required=True)
    return ok


def _missing_environment_files(repo_root: Path) -> list[Path]:
    env_files = (
        repo_root / ".env",
        repo_root / "web/.env.local",
    )
    missing_env: list[Path] = []
    for path in env_files:
        exists = path.exists()
        _check_file(path, required=False)
        if not exists:
            missing_env.append(path)
    return missing_env


def _print_environment_hints(os_name: str, missing_env: list[Path]) -> None:
    if missing_env:
        print("[doctor] HINT: Create env files with `python scripts/init_env.py` (or `make init`).")

    if shutil.which("pnpm") is None:
        print("[doctor] WARN: pnpm not on PATH (Corepack may be disabled).")

    if os_name == "Windows":
        print("[doctor] HINT: On Windows without make, use `powershell -File scripts/verify.ps1` for repo checks.")


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    os_name = _print_environment_header(repo_root)
    _check_tool_commands()
    _warn_if_docker_daemon_unavailable()
    _warn_if_git_converts_line_endings()
    ok = _required_files_ok(repo_root)
    missing_env = _missing_environment_files(repo_root)
    _print_environment_hints(os_name, missing_env)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
