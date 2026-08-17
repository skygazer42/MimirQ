"""
Image stripping helpers for governance cleaning.

We treat the input as Markdown-like text; some parsers may still emit raw HTML
image tags. Removal is code-fence aware and supports:
- mode="none": keep all
- mode="decorative": remove likely decorative images (logos/qrcodes/banners)
- mode="all": remove all images
"""


import re
from dataclasses import dataclass
from typing import Literal

ImageRemoveMode = Literal["none", "decorative", "all"]


@dataclass(frozen=True)
class ImageStripResult:
    text: str
    removed: int
    changed: bool


_CODE_FENCE_RE = re.compile(r"^\s*```")

_MD_IMAGE_INLINE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)]+)\)")
_MD_IMAGE_REF_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\[(?P<ref>[^\]]+)\]")
_HTML_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)

_HTML_ATTR_RE = re.compile(r"""\b(?P<key>src|alt)\s*=\s*(?P<q>['"])(?P<val>.*?)(?P=q)""", re.IGNORECASE)

_DECORATIVE_TOKENS = (
    "logo",
    "qrcode",
    "qr",
    "banner",
    "icon",
    "avatar",
    "watermark",
    "sponsor",
    "sponsored",
    "ad",
    "ads",
    "wechat",
    "wx",
    "\u4e8c\u7ef4\u7801",
    "\u516c\u4f17\u53f7",
    "\u56fe\u6807",
    "\u5934\u50cf",
    "\u6c34\u5370",
    "\u5e7f\u544a",
    "\u63a8\u5e7f",
)


def _is_decorative_image(*, alt: str, url: str) -> bool:
    joined = f"{alt} {url}".strip().casefold()
    if not joined:
        return True
    return any(tok in joined for tok in _DECORATIVE_TOKENS)


def _replace_markdown_image(
    match: re.Match[str],
    *,
    mode: ImageRemoveMode,
    url_group: str,
    removed: list[int],
) -> str:
    if mode == "all":
        removed[0] += 1
        return ""

    alt = (match.group("alt") or "").strip()
    url = (match.group(url_group) or "").strip()
    if _is_decorative_image(alt=alt, url=url):
        removed[0] += 1
        return ""
    return match.group(0)


def _replace_html_image(match: re.Match[str], *, mode: ImageRemoveMode, removed: list[int]) -> str:
    if mode == "all":
        removed[0] += 1
        return ""

    tag = match.group(0) or ""
    attrs = {
        (m.group("key") or "").strip().lower(): (m.group("val") or "").strip()
        for m in _HTML_ATTR_RE.finditer(tag)
    }
    if _is_decorative_image(alt=attrs.get("alt", ""), url=attrs.get("src", "")):
        removed[0] += 1
        return ""
    return tag


def _strip_image_line(line: str, *, mode: ImageRemoveMode, removed: list[int]) -> str:
    current = _HTML_IMG_RE.sub(lambda match: _replace_html_image(match, mode=mode, removed=removed), line)
    current = _MD_IMAGE_INLINE_RE.sub(
        lambda match: _replace_markdown_image(match, mode=mode, url_group="url", removed=removed),
        current,
    )
    return _MD_IMAGE_REF_RE.sub(
        lambda match: _replace_markdown_image(match, mode=mode, url_group="ref", removed=removed),
        current,
    )


def strip_images(text: str, *, mode: ImageRemoveMode) -> ImageStripResult:
    original = text or ""
    if not original or mode == "none":
        return ImageStripResult(text=original, removed=0, changed=False)

    removed = [0]
    out_lines: list[str] = []
    in_code = False

    for line in original.splitlines():
        if _CODE_FENCE_RE.match(line):
            in_code = not in_code
            out_lines.append(line)
            continue
        if in_code:
            out_lines.append(line)
            continue

        out_lines.append(_strip_image_line(line, mode=mode, removed=removed))

    cleaned = "\n".join(out_lines)
    return ImageStripResult(text=cleaned, removed=removed[0], changed=(cleaned != original))
