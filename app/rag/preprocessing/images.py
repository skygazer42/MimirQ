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


def strip_images(text: str, *, mode: ImageRemoveMode) -> ImageStripResult:
    original = text or ""
    if not original or mode == "none":
        return ImageStripResult(text=original, removed=0, changed=False)

    removed = 0
    out_lines: list[str] = []
    in_code = False

    def md_inline_repl(match: re.Match[str]) -> str:
        nonlocal removed
        if mode == "all":
            removed += 1
            return ""
        alt = (match.group("alt") or "").strip()
        url = (match.group("url") or "").strip()
        if _is_decorative_image(alt=alt, url=url):
            removed += 1
            return ""
        return match.group(0)

    def md_ref_repl(match: re.Match[str]) -> str:
        nonlocal removed
        if mode == "all":
            removed += 1
            return ""
        alt = (match.group("alt") or "").strip()
        ref = (match.group("ref") or "").strip()
        if _is_decorative_image(alt=alt, url=ref):
            removed += 1
            return ""
        return match.group(0)

    def html_img_repl(match: re.Match[str]) -> str:
        nonlocal removed
        if mode == "all":
            removed += 1
            return ""
        tag = match.group(0) or ""
        attrs: dict[str, str] = {}
        for m in _HTML_ATTR_RE.finditer(tag):
            attrs[(m.group("key") or "").strip().lower()] = (m.group("val") or "").strip()
        alt = attrs.get("alt", "")
        src = attrs.get("src", "")
        if _is_decorative_image(alt=alt, url=src):
            removed += 1
            return ""
        return tag

    for line in original.splitlines():
        if _CODE_FENCE_RE.match(line):
            in_code = not in_code
            out_lines.append(line)
            continue
        if in_code:
            out_lines.append(line)
            continue

        current = _HTML_IMG_RE.sub(html_img_repl, line)
        current = _MD_IMAGE_INLINE_RE.sub(md_inline_repl, current)
        current = _MD_IMAGE_REF_RE.sub(md_ref_repl, current)
        out_lines.append(current)

    cleaned = "\n".join(out_lines)
    return ImageStripResult(text=cleaned, removed=removed, changed=(cleaned != original))

