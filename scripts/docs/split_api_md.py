#!/usr/bin/env python3
"""
Split docs/API.md on level-1 Markdown headings (# Foo) into docs/api/reference/*.md.
Headings inside fenced code blocks (```) are ignored.
Writes docs/api/reference/_index.md manifest. Run from repo root.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# Long-form narrative lives here after API.md became an index; fallback to docs/API.md for one-off runs.
SRC = REPO / "docs" / "api" / "source" / "legacy-api-narrative.md"
FALLBACK = REPO / "docs" / "API.md"
OUT_DIR = REPO / "docs" / "api" / "reference"

H1_RE = re.compile(r"^# [^#]")


def slugify_title(title: str) -> str:
    t = title.strip()
    t = re.sub(r"[^\w\u4e00-\u9fff]+", "-", t, flags=re.UNICODE)
    t = t.strip("-").lower()
    if not t or len(t) > 80:
        return "section"
    return t


def find_h1_lines(lines: list[str]) -> list[int]:
    in_fence = False
    indices: list[int] = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if H1_RE.match(ln):
            indices.append(i)
    return indices


def main() -> None:
    src = SRC if SRC.exists() else FALLBACK
    text = src.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    h1_indices = find_h1_lines(lines)
    if not h1_indices:
        raise SystemExit("No H1 sections found (outside code fences)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest: list[tuple[str, str]] = []

    for j, start in enumerate(h1_indices):
        end = h1_indices[j + 1] if j + 1 < len(h1_indices) else len(lines)
        chunk = "".join(lines[start:end]).strip()
        if not chunk:
            continue
        first_line = lines[start].strip()
        title = first_line.lstrip("# ").strip()
        slug = slugify_title(title)
        fname = f"{j:03d}-{slug}.md"
        if j == 0 and "接口文档" in title:
            fname = "000-title.md"
        path = OUT_DIR / fname
        path.write_text(chunk + "\n", encoding="utf-8")
        manifest.append((fname, title))

    index_lines = [
        "# API 文档拆分索引",
        "",
        "> 由 `scripts/docs/split_api_md.py` 从 `docs/api/source/legacy-api-narrative.md`（或 `docs/API.md`）自动切分（忽略代码围栏内的 `#` 行）。",
        "> 更新长文：编辑 legacy 文件后重新运行本脚本，或直接改 `reference/` 下分片。",
        "",
        "## 分片列表",
        "",
        "| 文件 | 标题 |",
        "| --- | --- |",
    ]
    for fname, title in manifest:
        index_lines.append(f"| [`{fname}`](./{fname}) | {title} |")
    index_lines.append("")
    index_lines.append("## 全栈手册")
    index_lines.append("")
    index_lines.append("- [Docusaurus 手册（GitHub Pages）](https://skygazer42.github.io/MimirQ/handbook/)")
    index_lines.append("- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)")
    index_lines.append("")

    (OUT_DIR / "_index.md").write_text("\n".join(index_lines), encoding="utf-8")
    print("Wrote", len(manifest), "chunks to", OUT_DIR)


if __name__ == "__main__":
    main()
