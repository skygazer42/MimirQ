import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from typing import Any

_HEADING_RE = re.compile(r"(?m)^(#{1,6})\s+\S+")

POSITION_TAG_RE = re.compile(r"@@([0-9-]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)##")
MARKDOWN_IMAGE_RE = re.compile(
    r"!\[[^\]]*\]\(\s*(?:<)?[^)\s>]+(?:>)?(?:\s+['\"][^'\"]*['\"])?\s*\)",
    re.IGNORECASE,
)
HTML_IMAGE_RE = re.compile(r"<img\b[^>]*\bsrc\s*=\s*['\"][^'\"]+['\"][^>]*>", re.IGNORECASE)


def _coerce_int(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        if isinstance(value, str):
            value = float(value.strip())
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def count_position_tag_blocks(markdown: str) -> int:
    """
    Count "position blocks" in markdown.

    A position block is a chunk of text associated with 1+ position tags (e.g. @@page...##),
    matching the workspace UI's block extraction semantics (only blocks that have positions).
    """
    if not markdown:
        return 0

    block_count = 0
    last_index = 0
    has_last_block = False

    for match in POSITION_TAG_RE.finditer(markdown):
        text_chunk = markdown[last_index : match.start()]
        text = text_chunk.strip()
        if text or not has_last_block:
            block_count += 1
            has_last_block = True

        last_index = match.end()

    return block_count


def count_markdown_images(markdown: str | None) -> int:
    if not markdown:
        return 0
    return len(MARKDOWN_IMAGE_RE.findall(markdown)) + len(HTML_IMAGE_RE.findall(markdown))


def _iter_metadata(documents: Iterable[Any] | None) -> Iterable[Mapping[str, Any]]:
    if documents is None:
        return
    for item in documents:
        if isinstance(item, Mapping):
            meta = item.get("metadata")
        else:
            meta = getattr(item, "metadata", None)
        if isinstance(meta, Mapping):
            yield meta


def compute_parsing_artifact_stats(
    *,
    documents: Iterable[Any] | None,
    original_markdown: str,
    markdown: str | None = None,
    pdf_quality: Mapping[str, Any] | None,
) -> dict[str, int]:
    table_count = 0
    image_count = 0

    for meta in _iter_metadata(documents):
        content_type = meta.get("content_type")
        doc_type = meta.get("doc_type_kwd")
        if isinstance(content_type, str):
            content_type = content_type.strip().lower()
        if isinstance(doc_type, str):
            doc_type = doc_type.strip().lower()
        if content_type == "table" or doc_type == "table":
            table_count += 1
        if content_type == "image" or doc_type == "image":
            image_count += 1

    page_count = 0
    if isinstance(pdf_quality, Mapping):
        page_count = max(0, _coerce_int(pdf_quality.get("page_count")))

    markdown_image_count = max(
        count_markdown_images(original_markdown),
        count_markdown_images(markdown),
    )
    image_count = max(image_count, markdown_image_count)
    block_count = count_position_tag_blocks(original_markdown)

    return {
        "page_count": page_count,
        "table_count": table_count,
        "image_count": image_count,
        "block_count": block_count,
    }


@dataclass(frozen=True)
class DocumentAnalytics:
    """Text, artifact and optional language statistics for the document UI."""

    char_count: int = 0
    line_count: int = 0
    heading_count: int = 0
    page_count: int = 0
    table_count: int = 0
    image_count: int = 0
    block_count: int = 0
    language: str | None = None
    language_confidence: float | None = None
    cjk_chars: int | None = None
    latin_chars: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


def compute_document_analytics(
    *,
    markdown: str,
    documents: Iterable[Any] | None = None,
    pdf_quality: Mapping[str, Any] | None = None,
    detect_language: bool = False,
    language_min_chars: int = 40,
) -> DocumentAnalytics:
    artifact = compute_parsing_artifact_stats(
        documents=documents,
        original_markdown=markdown,
        markdown=markdown,
        pdf_quality=pdf_quality,
    )
    analytics = DocumentAnalytics(
        char_count=len(markdown),
        line_count=len(markdown.splitlines()),
        heading_count=len(_HEADING_RE.findall(markdown)),
        page_count=artifact["page_count"],
        table_count=artifact["table_count"],
        image_count=artifact["image_count"],
        block_count=artifact["block_count"],
    )
    if detect_language:
        from app.rag.ingestion.governance.tagging.language import detect_language as detect_language_fn

        language = detect_language_fn(markdown, min_chars=language_min_chars)
        analytics = replace(
            analytics,
            language=language.language,
            language_confidence=language.confidence,
            cjk_chars=language.cjk_chars,
            latin_chars=language.latin_chars,
        )
    return analytics
