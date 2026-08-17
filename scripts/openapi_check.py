import json
import subprocess
from pathlib import Path

REQUIRED_ARTIFACTS = (
    Path("web/openapi.json"),
    Path("web/types/openapi.ts"),
)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True)


def _is_tracked(path: Path) -> bool:
    result = _run(["git", "ls-files", "--error-unmatch", "--", str(path)])
    return result.returncode == 0


def _is_non_empty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _git_diff_clean(path: Path) -> bool:
    result = subprocess.run(["git", "diff", "--quiet", "--exit-code", "--", str(path)])
    return result.returncode == 0


def _git_diff(path: Path) -> str:
    result = _run(["git", "diff", "--", str(path)])
    return result.stdout.strip()


def _required_artifacts_exist(repo_root: Path) -> bool:
    ok = True
    for rel in REQUIRED_ARTIFACTS:
        full = repo_root / rel
        if not _is_non_empty_file(full):
            print(f"[openapi-check] FAIL: missing or empty: {rel.as_posix()}")
            ok = False
    return ok


def _dirty_artifacts() -> list[str]:
    return [rel.as_posix() for rel in REQUIRED_ARTIFACTS if _is_tracked(rel) and not _git_diff_clean(rel)]


def _report_dirty_artifacts(dirty: list[str]) -> None:
    joined = ", ".join(dirty)
    print(f"[openapi-check] FAIL: OpenAPI artifacts differ: {joined}")
    print("[openapi-check] Run `make openapi-types` and commit changes.")
    for rel_path in dirty:
        diff = _git_diff(Path(rel_path))
        if not diff:
            continue
        print(f"[openapi-check] Diff for {rel_path}:")
        print(diff[:20_000])
        if len(diff) > 20_000:
            print("[openapi-check] ...diff truncated...")


def _load_spec(repo_root: Path) -> tuple[dict[str, object] | None, bool]:
    try:
        spec = json.loads((repo_root / "web/openapi.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"[openapi-check] FAIL: could not parse web/openapi.json: {exc}")
        return None, False
    return spec, True


def _find_empty_object_paths(spec: dict[str, object]) -> list[str]:
    empty_object_paths: list[str] = []

    def walk(node: object, path: list[str]) -> None:
        if isinstance(node, dict):
            if "$ref" not in node and node.get("type") == "object":
                props = node.get("properties")
                if (not props) and ("additionalProperties" not in node):
                    empty_object_paths.append("/".join(path))
            for k, v in node.items():
                walk(v, path + [str(k)])
            return
        if isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, path + [str(i)])

    walk(spec.get("components", {}).get("schemas", {}), ["components", "schemas"])
    empty_object_paths.sort()
    return empty_object_paths


def _report_empty_object_paths(paths: list[str]) -> None:
    print(f"[openapi-check] FAIL: found {len(paths)} empty object schemas (missing additionalProperties)")
    for path in paths[:200]:
        print(f"  - {path}")
    if len(paths) > 200:
        print(f"  ...and {len(paths) - 200} more")
    print("[openapi-check] Hint: for dict-like schemas, set additionalProperties (or patch OpenAPI export).")


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    if not _required_artifacts_exist(repo_root):
        return 1

    dirty = _dirty_artifacts()
    if dirty:
        _report_dirty_artifacts(dirty)
        return 1

    spec, loaded = _load_spec(repo_root)
    if not loaded or spec is None:
        return 1

    # Empty object schemas become `Record<string, never>` in openapi-typescript.
    empty_object_paths = _find_empty_object_paths(spec)
    if empty_object_paths:
        _report_empty_object_paths(empty_object_paths)
        return 1

    print("[openapi-check] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
