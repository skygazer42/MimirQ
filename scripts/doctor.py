
import locale
import platform
import re
import shutil
import subprocess
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


def _parse_python_version(output: str) -> tuple[int, int, int] | None:
    # Expected: "Python 3.11.7"
    m = re.search(r"Python\s+(\d+)\.(\d+)\.(\d+)", output or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    os_name = platform.system()
    print(f"[doctor] OS: {os_name} ({platform.release()})")
    print(f"[doctor] Repo: {repo_root.as_posix()}")

    ok = True

    # Prefer python3 on Unix-like systems; prefer python on Windows.
    if os_name == "Windows":
        py_ok = _check_cmd("Python (python)", ["python", "--version"])
        # Optional: python3 alias (some Windows setups have it).
        _check_cmd("Python (python3) (optional)", ["python3", "--version"], required=False)
        if not py_ok:
            py_ok = _check_cmd("Python (python3)", ["python3", "--version"])
    else:
        py_ok = _check_cmd("Python (python3)", ["python3", "--version"])
        if not py_ok:
            py_ok = _check_cmd("Python (python)", ["python", "--version"])
    ok &= py_ok

    # Warn (but don't fail) if local Python is < 3.11 (repo requires 3.11+ for syntax/deps).
    for exe in ("python3", "python"):
        code, out = _run([exe, "--version"])
        if code != 0:
            continue
        ver = _parse_python_version(out)
        if ver and (ver[0], ver[1]) < (3, 11):
            print(f"[doctor] WARN: {exe} is {ver[0]}.{ver[1]}.{ver[2]} (MimirQ requires Python 3.11+ for local backend)")
        break

    _check_cmd("Node", ["node", "--version"])
    _check_cmd("pnpm", ["pnpm", "--version"])
    _check_cmd("Git (optional)", ["git", "--version"], required=False)
    _check_cmd("Make (optional)", ["make", "--version"], required=False)
    _check_cmd("Docker", ["docker", "--version"])
    _check_cmd("Docker Compose", ["docker", "compose", "version"])
    _check_cmd("Ruff (optional)", ["ruff", "--version"], required=False)
    _check_cmd("pip-audit (optional)", ["pip-audit", "--version"], required=False)

    # Best-effort: docker daemon check (avoid noisy `docker info` output).
    if shutil.which("docker") is not None:
        code, _out = _run(["docker", "ps"])
        if code != 0:
            print("[doctor] WARN: Docker CLI is installed but the daemon may not be running (try starting Docker Desktop).")

    # Best-effort: warn about CRLF auto-conversion which may cause noisy diffs.
    if shutil.which("git") is not None:
        code, out = _run(["git", "config", "--get", "core.autocrlf"])
        if code == 0 and (out or "").strip().lower() in {"true", "input"}:
            print("[doctor] WARN: git core.autocrlf is enabled; consider disabling to reduce CRLF/LF churn (repo enforces LF via .gitattributes).")

    ok &= _check_file(repo_root / "docker/docker-compose.yml", required=True)
    ok &= _check_file(repo_root / "docker/docker-compose.web.yml", required=True)
    ok &= _check_file(repo_root / "web/package.json", required=True)
    ok &= _check_file(repo_root / "app/main.py", required=True)

    env_files = [
        repo_root / ".env",
        repo_root / "web/.env.local",
    ]
    missing_env: list[Path] = []
    for path in env_files:
        exists = path.exists()
        _check_file(path, required=False)
        if not exists:
            missing_env.append(path)

    if missing_env:
        print("[doctor] HINT: Create env files with `python scripts/init_env.py` (or `make init`).")

    # Helpful hint: show whether pnpm is discoverable via PATH
    if shutil.which("pnpm") is None:
        print("[doctor] WARN: pnpm not on PATH (Corepack may be disabled).")

    if os_name == "Windows":
        print("[doctor] HINT: On Windows without make, use `powershell -File scripts/verify.ps1` for repo checks.")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
