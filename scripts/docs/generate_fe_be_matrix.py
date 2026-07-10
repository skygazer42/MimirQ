#!/usr/bin/env python3
"""
Generate FE/BE/OpenAPI routing matrix (v0) for the handbook.
Run from repo root: python scripts/docs/generate_fe_be_matrix.py

Reads: web/openapi.json, web/lib/api/*.ts, web/app/**/page.tsx
Writes: docs-site/docs/integration/generated/fe-be-matrix.mdx
"""

import json
import re
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OPENAPI = REPO / "web" / "openapi.json"
WEB_LIB_API = REPO / "web" / "lib" / "api"
WEB_APP = REPO / "web" / "app"
OUT = REPO / "docs-site" / "docs" / "integration" / "generated" / "fe-be-matrix.mdx"

# apiClient.get("/api/v1/foo") or `/api/v1/foo` or "/api/v1/foo"
PATH_RE = re.compile(
    r"""['`](?P<p>/api/v1[^'"`$]*?)['`]"""
)
# Optional template: `/api/v1/foo/${id}`
PATH_TEMPLATE_RE = re.compile(
    r"""['"](?P<p>/api/v1(?:/\{[^}]+\}|/[a-zA-Z0-9_\-{}]+)+)['"]"""
)


def load_openapi_by_tag() -> dict[str, list[str]]:
    data = json.loads(OPENAPI.read_text(encoding="utf-8"))
    by_tag: dict[str, list[str]] = defaultdict(list)
    paths = data.get("paths") or {}
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for _m, spec in methods.items():
            if not isinstance(spec, dict):
                continue
            tags = spec.get("tags") or ["(untagged)"]
            for t in tags:
                by_tag[str(t)].append(path)
    for t in by_tag:
        by_tag[t] = sorted(set(by_tag[t]))
    return dict(sorted(by_tag.items()))


def extract_ts_paths() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if not WEB_LIB_API.exists():
        return out
    for fp in sorted(WEB_LIB_API.glob("*.ts")):
        text = fp.read_text(encoding="utf-8", errors="replace")
        found = set()
        for rx in (PATH_RE, PATH_TEMPLATE_RE):
            for m in rx.finditer(text):
                p = m.group("p")
                if "${" in p or "`" in p:
                    continue
                found.add(re.sub(r"\$\{[^}]+\}", "{id}", p))
        if found:
            out[fp.name] = sorted(found)
    return out


def app_path_to_route(file_path: Path) -> str | None:
    rel = file_path.relative_to(WEB_APP)
    parts: list[str] = []
    for seg in rel.parts[:-1]:  # drop page.tsx or layout
        if seg in ("(", ")"):
            continue
        if seg.startswith("(") and seg.endswith(")"):
            continue
        if seg == "page.tsx" or seg == "layout.tsx":
            continue
        if seg.startswith("["):
            parts.append(f"[{seg.strip('[]')}]")
        else:
            parts.append(seg)
    if not parts:
        return "/"
    return "/" + "/".join(parts)


def list_next_routes() -> list[str]:
    routes: list[str] = []
    if not WEB_APP.exists():
        return routes
    for p in WEB_APP.rglob("page.tsx"):
        r = app_path_to_route(p)
        if r:
            routes.append(r)
    return sorted(set(routes))


def main() -> None:
    by_tag = load_openapi_by_tag()
    ts_paths = extract_ts_paths()
    routes = list_next_routes()

    lines: list[str] = [
        "---",
        "sidebar_label: FE/BE 对照矩阵 (自动生成)",
        "sidebar_position: 10",
        "---",
        "",
        "# FE / BE / 路由对照矩阵（自动生成 v0）",
        "",
        "> 由 `scripts/docs/generate_fe_be_matrix.py` 根据 `web/openapi.json`、`web/lib/api/*.ts`、`web/app/**/page.tsx` 生成。",
        "> 模板字符串与复杂拼接可能未被识别；以 OpenAPI 与源码为准。",
        "",
        "## OpenAPI 路径（按 tag）",
        "",
    ]
    for tag, paths in by_tag.items():
        lines.append(f"### {tag}")
        lines.append("")
        lines.append("| Path |")
        lines.append("| --- |")
        for p in paths[:200]:
            lines.append(f"| `{p}` |")
        if len(paths) > 200:
            lines.append(f"| … 共 {len(paths)} 条，其余见 Redoc |")
        lines.append("")

    lines.append("## `web/lib/api` 中出现的 `/api/v1` 路径片段")
    lines.append("")
    lines.append("| 模块 | Path 片段 |")
    lines.append("| --- | --- |")
    for mod, ps in sorted(ts_paths.items()):
        lines.append(f"| `{mod}` | {', '.join(f'`{p}`' for p in ps[:12])}{' …' if len(ps) > 12 else ''} |")
    lines.append("")

    lines.append("## Next.js `page.tsx` 路由（去重）")
    lines.append("")
    lines.append("| Route |")
    lines.append("| --- |")
    for r in routes[:300]:
        lines.append(f"| `{r}` |")
    if len(routes) > 300:
        lines.append(f"| … 共 {len(routes)} 条 |")
    lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Wrote", OUT)


if __name__ == "__main__":
    main()
