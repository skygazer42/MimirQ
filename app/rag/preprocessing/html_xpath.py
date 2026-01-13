"""
HTML XPath extraction helpers.

Use cases:
- /pipeline/clean-preview for input_format=html
- HTML parser optional fine-grained extraction before text conversion

This module never performs any network access.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class HtmlXPathExtractResult:
    text: str
    matched_nodes: int
    xpath_error: Optional[str] = None


def extract_text_from_html(html: str, *, xpath: str | None = None) -> HtmlXPathExtractResult:
    raw = html or ""
    if not raw.strip():
        return HtmlXPathExtractResult(text="", matched_nodes=0)

    try:
        from lxml import etree, html as lxml_html  # type: ignore
    except Exception:
        # No lxml available: best-effort strip using html_text if present.
        try:
            from html_text import extract_text  # type: ignore

            return HtmlXPathExtractResult(text=extract_text(raw, guess_layout=True) or "", matched_nodes=0)
        except Exception:
            return HtmlXPathExtractResult(text=raw, matched_nodes=0, xpath_error="lxml_unavailable")

    parser = lxml_html.HTMLParser(recover=True, remove_comments=False)
    try:
        root = lxml_html.fromstring(raw, parser=parser)
    except Exception as exc:
        # Best-effort: return raw HTML as text-ish content.
        return HtmlXPathExtractResult(text=raw, matched_nodes=0, xpath_error=f"parse_failed:{str(exc)[:80]}")

    nodes: list[object] | None = None
    xpath_error: str | None = None
    if xpath and str(xpath).strip():
        try:
            result = root.xpath(str(xpath))
            nodes = list(result) if isinstance(result, (list, tuple)) else [result]
        except Exception as exc:
            xpath_error = f"xpath_failed:{str(exc)[:120]}"
            nodes = None

    # If XPath did not match or failed, fall back to the whole document.
    if not nodes:
        fragments_html = raw
        matched = 0
    else:
        matched = len(nodes)
        fragments: list[str] = []
        for node in nodes:
            if isinstance(node, etree._Element):  # type: ignore[attr-defined]
                try:
                    fragments.append(etree.tostring(node, encoding="unicode", method="html") or "")
                except Exception:
                    fragments.append(node.text_content() or "")
            else:
                fragments.append(str(node))
        fragments_html = "\n".join([f for f in fragments if (f or "").strip()])

    # Convert to plain text.
    try:
        from html_text import extract_text  # type: ignore

        text = extract_text(fragments_html or "", guess_layout=True) or ""
    except Exception:
        try:
            # lxml fallback.
            if nodes:
                extracted: list[str] = []
                for node in nodes:
                    if isinstance(node, etree._Element):  # type: ignore[attr-defined]
                        extracted.append(node.text_content() or "")
                    else:
                        extracted.append(str(node))
                text = "\n\n".join([t.strip() for t in extracted if (t or "").strip()])
            else:
                text = root.text_content() or ""
        except Exception:
            text = fragments_html or ""

    return HtmlXPathExtractResult(text=text, matched_nodes=matched, xpath_error=xpath_error)

