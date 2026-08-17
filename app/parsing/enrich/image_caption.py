
import re
from urllib.parse import unquote

from app.rag.core.logging import get_logger

logger = get_logger(__name__)

_IMAGE_CAPTION_PREFIX = "Image caption:"

# Match Markdown inline image: ![alt](src "optional title")
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

# Match reference-style image: ![alt][ref]
_MD_IMAGE_REF_RE = re.compile(r"!\[([^\]]*)\]\[([^\]]+)\]")

# Match a single HTML <img ...> tag.
_HTML_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_HTML_IMG_ATTR_RE = re.compile(r"(src|alt)\s*=\s*([\"'])(.*?)\2", re.IGNORECASE)

_FENCE_RE = re.compile(r"^\s*(```+|~~~+)")

_CAPTION_PREFIXES = (
    "image caption:",
    "caption:",
)


def _normalize_caption_check(line: str) -> str:
    """
    Normalize a line for "already has caption" checks.

    - Strip whitespace.
    - Strip blockquote markers (">") repeatedly.
    """
    s = (line or "").strip()
    while s.startswith(">"):
        s = s[1:].lstrip()
    return s.lower()


def _looks_like_table_row(line: str) -> bool:
    s = (line or "").strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 2


def _clean_caption_text(s: str, *, max_chars: int) -> str:
    cleaned = re.sub(r"\s+", " ", str(s or "")).strip()
    if not cleaned:
        return ""
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 3].rstrip() + "..."
    return cleaned


def _filename_from_src(src: str) -> str:
    raw = str(src or "").strip()
    if not raw:
        return ""
    if raw.startswith("data:"):
        return ""
    raw = raw.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    name = raw.rsplit("/", 1)[-1].strip()
    if not name or name in {".", ".."}:
        return ""
    try:
        name = unquote(name)
    except Exception as exc:
        logger.debug("Ignoring image caption filename decode failure: %s", exc)
    return name


def _extract_md_images(line: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for alt, src in _MD_IMAGE_RE.findall(line or ""):
        out.append((alt or "", src or ""))
    # Reference-style image doesn't include src; keep alt only.
    for alt, _ref in _MD_IMAGE_REF_RE.findall(line or ""):
        if alt:
            out.append((alt or "", ""))
    return out


def _extract_html_imgs(line: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for tag in _HTML_IMG_TAG_RE.findall(line or ""):
        alt = ""
        src = ""
        for key, _q, val in _HTML_IMG_ATTR_RE.findall(tag):
            k = (key or "").strip().lower()
            if k == "alt":
                alt = val
            elif k == "src":
                src = val
        out.append((alt or "", src or ""))
    return out


def _extract_line_images(line: str) -> tuple[int, list[tuple[str, str]]]:
    token_start = (line or "").find("![")
    if token_start >= 0:
        tail = (line or "")[token_start:]
        tail_wo_images = _MD_IMAGE_RE.sub("", tail)
        tail_wo_images = _MD_IMAGE_REF_RE.sub("", tail_wo_images)
        if (_MD_IMAGE_RE.search(tail) or _MD_IMAGE_REF_RE.search(tail)) and not tail_wo_images.strip():
            return token_start, _extract_md_images(tail)
        return token_start, []

    token_start = (line or "").lower().find("<img")
    if token_start >= 0:
        tail = (line or "")[token_start:]
        if _HTML_IMG_TAG_RE.search(tail) and not _HTML_IMG_TAG_RE.sub("", tail).strip():
            return token_start, _extract_html_imgs(tail)
    return -1, []


def _build_caption_text(images: list[tuple[str, str]], *, max_caption_chars: int) -> str:
    captions: list[str] = []
    for alt, src in images:
        cap = _clean_caption_text(alt, max_chars=max_caption_chars)
        if not cap:
            cap = _clean_caption_text(_filename_from_src(src), max_chars=max_caption_chars)
        if cap:
            captions.append(cap)
    if not captions:
        return ""
    return _clean_caption_text("; ".join(captions), max_chars=max_caption_chars)


def _next_line_has_caption(lines: list[str], idx: int) -> bool:
    next_line = lines[idx + 1] if idx + 1 < len(lines) else ""
    return _normalize_caption_check(next_line).startswith(_CAPTION_PREFIXES)


def _build_caption_line(
    line: str,
    *,
    lines: list[str],
    idx: int,
    prefix: str,
    max_caption_chars: int,
) -> str:
    if _looks_like_table_row(line) or not (line or "").strip() or _next_line_has_caption(lines, idx):
        return ""

    token_start, images = _extract_line_images(line)
    if not images:
        return ""

    caption_text = _build_caption_text(images, max_caption_chars=max_caption_chars)
    if not caption_text:
        return ""

    prefix0 = str(prefix or _IMAGE_CAPTION_PREFIX).strip() or _IMAGE_CAPTION_PREFIX
    lead = line[:token_start] if token_start >= 0 else ""
    return f"{lead}{prefix0} {caption_text}"


def add_image_captions(
    markdown: str,
    *,
    prefix: str = _IMAGE_CAPTION_PREFIX,
    max_captions: int = 50,
    max_caption_chars: int = 200,
) -> tuple[str, int]:
    """
    Best-effort enrichment: insert a short caption line after Markdown/HTML image lines.

    This does NOT perform OCR. It only uses:
    - Markdown alt text
    - HTML img alt attribute
    - filename fallback derived from the src URL/path
    """
    if not markdown:
        return "", 0

    lines = markdown.splitlines()
    ends_with_newline = markdown.endswith("\n")

    out: list[str] = []
    added = 0
    in_fence = False

    for idx, line in enumerate(lines):
        out.append(line)

        # Toggle fenced code blocks.
        if _FENCE_RE.match(line or ""):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if added >= int(max_captions or 0):
            continue
        caption_line = _build_caption_line(
            line,
            lines=lines,
            idx=idx,
            prefix=prefix,
            max_caption_chars=int(max_caption_chars or 0),
        )
        if not caption_line:
            continue
        out.append(caption_line)
        added += 1

    result = "\n".join(out)
    if ends_with_newline and not result.endswith("\n"):
        result += "\n"
    return result, added
