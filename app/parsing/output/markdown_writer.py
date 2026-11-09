from pathlib import Path
from typing import Any


def markdown_to_blocks(markdown: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for raw in markdown.splitlines():
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
    title_text = str(title).strip() if title is not None else None
    if title_text:
        lines.extend([f"# {title_text}", ""])

    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        raw_type = block.get("type")
        block_type = raw_type.strip().lower() if isinstance(raw_type, str) else None
        if block_type == "image":
            alt_value = block.get("alt")
            alt = str(alt_value).strip() if alt_value is not None else ""
            path_value = block.get("path")
            img_path = str(path_value).strip() if path_value is not None else None
            if img_path:
                lines.extend([f"![{alt}]({img_path})", ""])
            continue
        value = block.get("text")
        if value is None:
            continue
        text = str(value).strip()
        if text:
            lines.extend([text, ""])

    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return target
