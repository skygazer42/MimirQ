"""
HTML XPath extraction helpers.

Use cases:
- /pipeline/clean-preview for input_format=html
- HTML parser optional fine-grained extraction before text conversion

This module never performs any network access.
"""

from dataclasses import dataclass
from types import ModuleType
from typing import TYPE_CHECKING, Any

from app.core.optional_deps import optional_import
from app.rag.core.logging import get_logger

if TYPE_CHECKING:
    from lxml.html import HtmlElement

logger = get_logger(__name__)


@dataclass(frozen=True)
class HtmlXPathExtractResult:
    text: str
    matched_nodes: int
    xpath_error: str | None = None


def _missing_lxml_result(raw: str) -> HtmlXPathExtractResult:
    html_text = optional_import("html_text", feature="html_xpath_text_extraction", pip_name="html-text")
    extract_text = getattr(html_text, "extract_text", None) if html_text is not None else None
    if callable(extract_text):
        try:
            return HtmlXPathExtractResult(
                text=extract_text(raw, guess_layout=True),
                matched_nodes=0,
                xpath_error="dependency_missing:lxml",
            )
        except Exception:
            return HtmlXPathExtractResult(text=raw, matched_nodes=0, xpath_error="dependency_missing:lxml")
    return HtmlXPathExtractResult(
        text=raw,
        matched_nodes=0,
        xpath_error="dependency_missing:lxml (hint: pip install lxml)",
    )


def _serialize_nodes(raw: str, nodes: list[Any] | None, lxml_etree: ModuleType) -> tuple[str, int]:
    if not nodes:
        return raw, 0

    fragments: list[str] = []
    for node in nodes:
        if isinstance(node, lxml_etree._Element):  # type: ignore[attr-defined]
            try:
                fragments.append(lxml_etree.tostring(node, encoding="unicode", method="html"))
            except Exception:
                fragments.append(node.text_content())
        else:
            fragments.append(str(node))
    return "\n".join([fragment for fragment in fragments if (fragment).strip()]), len(nodes)


def _extract_with_lxml_fallback(
    root: "HtmlElement",
    nodes: list[Any] | None,
    fragments_html: str,
    lxml_etree: ModuleType,
) -> str:
    try:
        if not nodes:
            return root.text_content()
        extracted: list[str] = []
        for node in nodes:
            if isinstance(node, lxml_etree._Element):  # type: ignore[attr-defined]
                extracted.append(node.text_content())
            else:
                extracted.append(str(node))
        return "\n\n".join([text.strip() for text in extracted if (text).strip()])
    except Exception:
        return fragments_html


def extract_text_from_html(html: str, *, xpath: str | None = None) -> HtmlXPathExtractResult:
    raw = html
    if not raw.strip():
        return HtmlXPathExtractResult(text="", matched_nodes=0)

    lxml_etree = optional_import("lxml.etree", feature="html_xpath_extraction", pip_name="lxml")
    lxml_html = optional_import("lxml.html", feature="html_xpath_extraction", pip_name="lxml")
    if lxml_etree is None or lxml_html is None:
        return _missing_lxml_result(raw)

    parser = lxml_html.HTMLParser(recover=True, remove_comments=False)
    try:
        root = lxml_html.fromstring(raw, parser=parser)
    except Exception as exc:
        return HtmlXPathExtractResult(text=raw, matched_nodes=0, xpath_error=f"parse_failed:{str(exc)[:80]}")

    nodes: list[Any] | None = None
    xpath_error: str | None = None
    if xpath and str(xpath).strip():
        try:
            result = root.xpath(str(xpath))
            nodes = list(result) if isinstance(result, (list, tuple)) else [result]
        except Exception as exc:
            xpath_error = f"xpath_failed:{str(exc)[:120]}"

    fragments_html, matched = _serialize_nodes(raw, nodes, lxml_etree)
    html_text = optional_import("html_text", feature="html_xpath_text_extraction", pip_name="html-text")
    extract_text = getattr(html_text, "extract_text", None) if html_text is not None else None
    if callable(extract_text):
        try:
            text = extract_text(fragments_html, guess_layout=True)
        except Exception as exc:
            logger.debug("Optional html-text extraction failed (%s)", type(exc).__name__)
        else:
            return HtmlXPathExtractResult(text=text, matched_nodes=matched, xpath_error=xpath_error)

    text = _extract_with_lxml_fallback(root, nodes, fragments_html, lxml_etree)
    return HtmlXPathExtractResult(text=text, matched_nodes=matched, xpath_error=xpath_error)
