from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.parsing.quality.ocr_validator import rapid_ocr_service


def _normalize_lines(text: str) -> tuple[list[str], int | None]:
    lines = [" ".join(line.split()) for line in str(text or "").splitlines()]
    lines = [line for line in lines if line]
    expected_rows: int | None = None
    if lines:
        footer = lines[-1].strip()
        if footer.lower().startswith("rows"):
            raw_count = footer.split(":", 1)[1] if ":" in footer else footer[4:]
            try:
                expected_rows = max(0, int(raw_count.strip()))
            except Exception:
                expected_rows = None
            if expected_rows is not None:
                lines = lines[:-1]
    return lines, expected_rows


def markdown_table_from_ocr_text(text: str) -> str:
    lines, expected_rows = _normalize_lines(text)
    if len(lines) < 3:
        return ""

    for start in range(len(lines) - 2):
        header_tokens = [token.strip() for token in lines[start].split(" ") if token.strip()]
        if len(header_tokens) < 2 or len(header_tokens) > 6:
            continue
        rows: list[list[str]] = []
        cursor = start + 1
        while cursor < len(lines):
            row_tokens = [token.strip() for token in lines[cursor].split(" ") if token.strip()]
            if len(row_tokens) != len(header_tokens):
                break
            rows.append(row_tokens)
            cursor += 1
        if len(rows) < 2:
            continue
        if expected_rows is not None and len(rows) < expected_rows:
            continue

        prefix = lines[:start]
        header = f"| {' | '.join(header_tokens)} |"
        separator = f"| {' | '.join(['---'] * len(header_tokens))} |"
        body = [f"| {' | '.join(row)} |" for row in rows]
        blocks: list[str] = []
        if prefix:
            blocks.append("\n\n".join(prefix))
        blocks.append("\n".join([header, separator, *body]))
        return "\n\n".join(blocks).strip()
    return ""


def markdown_table_from_image_path(path: Path) -> str:
    try:
        with Image.open(path) as image:
            text = rapid_ocr_service.ocr_image(image)
    except Exception:
        return ""
    return markdown_table_from_ocr_text(text)


__all__ = ["markdown_table_from_image_path", "markdown_table_from_ocr_text"]
