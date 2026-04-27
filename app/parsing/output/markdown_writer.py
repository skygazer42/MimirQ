from __future__ import annotations

from pathlib import Path
from typing import Any


def markdown_to_blocks(markdown: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for raw in str(markdown or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# "):
            blocks.append({"type": "heading", "level": 1, "text": line[2:].strip()})
            continue
        blocks.append({"type": "paragraph", "text": line})
    return blocks


def write_clean_markdown(path: str | Path, *, title: str | None, blocks: list[dict[str, Any]]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    title_text = str(title or "").strip()
    if title_text:
        lines.extend([f"# {title_text}", ""])

    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "").strip().lower()
        if block_type == "image":
            alt = str(block.get("alt") or "").strip()
            img_path = str(block.get("path") or "").strip()
            if img_path:
                lines.extend([f"![{alt}]({img_path})", ""])
            continue
        text = str(block.get("text") or "").strip()
        if text:
            lines.extend([text, ""])

    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return target
