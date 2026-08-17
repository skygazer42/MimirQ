import json
import subprocess
from pathlib import Path


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


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    required = [
        Path("web/openapi.json"),
        Path("web/types/openapi.ts"),
    ]

    ok = True

    for rel in required:
        full = repo_root / rel
        if not _is_non_empty_file(full):
            print(f"[openapi-check] FAIL: missing or empty: {rel.as_posix()}")
            ok = False

    if not ok:
        return 1

    dirty: list[str] = []
    for rel in required:
        if not _is_tracked(rel):
            continue
        if not _git_diff_clean(rel):
            dirty.append(rel.as_posix())

    if dirty:
        joined = ", ".join(dirty)
        print(f"[openapi-check] FAIL: OpenAPI artifacts differ: {joined}")
        print("[openapi-check] Run `make openapi-types` and commit changes.")
        for rel_path in dirty:
            diff = _git_diff(Path(rel_path))
            if diff:
                print(f"[openapi-check] Diff for {rel_path}:")
                print(diff[:20_000])
                if len(diff) > 20_000:
                    print("[openapi-check] ...diff truncated...")
        return 1

    # Schema sanity: empty `type: object` schemas generate `Record<string, never>` in openapi-typescript,
    # which is almost always unintended (dict-like payloads should use additionalProperties).
    try:
        spec = json.loads((repo_root / "web/openapi.json").read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"[openapi-check] FAIL: could not parse web/openapi.json: {exc}")
        return 1

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

    if empty_object_paths:
        empty_object_paths.sort()
        print(
            f"[openapi-check] FAIL: found {len(empty_object_paths)} empty object schemas (missing additionalProperties)"
        )
        for p in empty_object_paths[:200]:
            print(f"  - {p}")
        if len(empty_object_paths) > 200:
            print(f"  ...and {len(empty_object_paths) - 200} more")
        print("[openapi-check] Hint: for dict-like schemas, set additionalProperties (or patch OpenAPI export).")
        return 1

    print("[openapi-check] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
