#!/usr/bin/env python3
"""Fail if exported OpenAPI has no paths (prevents empty spec on Pages)."""


import json
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    path = repo_root / "web" / "openapi.json"
    if not path.is_file() or path.stat().st_size == 0:
        print(f"[openapi-paths-sanity] FAIL: missing or empty {path}")
        return 1
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[openapi-paths-sanity] FAIL: invalid JSON: {exc}")
        return 1
    paths = spec.get("paths")
    if not isinstance(paths, dict) or not paths:
        print("[openapi-paths-sanity] FAIL: spec has no paths")
        return 1
    n = len(paths)
    min_paths = 50
    if n < min_paths:
        print(f"[openapi-paths-sanity] FAIL: only {n} paths (expected >= {min_paths})")
        return 1
    components = spec.get("components")
    schemas = components.get("schemas") if isinstance(components, dict) else None
    schema_n = len(schemas) if isinstance(schemas, dict) else 0
    print(f"[openapi-paths-sanity] OK: paths={n}, components.schemas={schema_n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
