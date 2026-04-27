from __future__ import annotations

import re


def rewrite_markdown_image_urls(text: str, image_mapping: dict[str, str] | None) -> str:
    mapping = {
        str(key or "").strip(): str(value or "").strip()
        for key, value in (image_mapping or {}).items()
        if str(key or "").strip() and str(value or "").strip()
    }
    if not mapping:
        return str(text or "")

    content = str(text or "")

    def replace_md(match: re.Match[str]) -> str:
        alt_text = match.group(1)
        raw = str(match.group(2) or "").strip()
        return f"![{alt_text}]({mapping[raw]})" if raw in mapping else match.group(0)

    content = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace_md, content)

    def replace_html(match: re.Match[str]) -> str:
        raw = str(match.group(1) or "").strip()
        return f'<img src="{mapping[raw]}"' if raw in mapping else match.group(0)

    content = re.sub(r'<img\s+src="([^"]+)"', replace_html, content)
    return content
