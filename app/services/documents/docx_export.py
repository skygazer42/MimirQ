"""Render stored clean Markdown for the document download endpoint."""

from io import BytesIO

from docx import Document


def render_clean_docx(markdown: str, *, title: str) -> bytes:
    """Export headings and paragraphs, suppressing a duplicate filename title."""
    document = Document()
    display_title = title.strip()
    if display_title:
        document.add_heading(display_title, level=1)

    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    if lines and lines[0].startswith("# ") and lines[0][2:].strip() == title:
        lines = lines[1:]

    for line in lines:
        if line.startswith("# "):
            document.add_heading(line[2:].strip(), level=1)
        else:
            document.add_paragraph(line)

    with BytesIO() as buffer:
        document.save(buffer)
        return buffer.getvalue()
