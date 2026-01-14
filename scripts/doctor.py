from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path


def _run(cmd: list[str]) -> tuple[int, str]:
    exe = shutil.which(cmd[0])
    if exe is None:
        return 127, ""
    result = subprocess.run([exe, *cmd[1:]], text=True, capture_output=True)
    out = (result.stdout or "").strip() or (result.stderr or "").strip()
    return result.returncode, out


def _check_cmd(name: str, cmd: list[str]) -> bool:
    code, out = _run(cmd)
    if code == 127:
        print(f"[doctor] MISSING: {name} ({cmd[0]} not found)")
        return False
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


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    os_name = platform.system()
    print(f"[doctor] OS: {os_name} ({platform.release()})")
    print(f"[doctor] Repo: {repo_root.as_posix()}")

    ok = True

    ok &= _check_cmd("Python", ["python", "--version"])
    _check_cmd("Node", ["node", "--version"])
    _check_cmd("pnpm", ["pnpm", "--version"])
    _check_cmd("Docker", ["docker", "--version"])
    _check_cmd("Docker Compose", ["docker", "compose", "version"])

    ok &= _check_file(repo_root / "docker/docker-compose.yml", required=True)
    ok &= _check_file(repo_root / "docker/docker-compose.web.yml", required=True)
    ok &= _check_file(repo_root / "web/package.json", required=True)
    ok &= _check_file(repo_root / "app/main.py", required=True)

    _check_file(repo_root / ".env", required=False)
    _check_file(repo_root / "docker/.env", required=False)
    _check_file(repo_root / "web/.env.local", required=False)

    # Helpful hint: show whether pnpm is discoverable via PATH
    if shutil.which("pnpm") is None:
        print("[doctor] WARN: pnpm not on PATH (Corepack may be disabled).")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
