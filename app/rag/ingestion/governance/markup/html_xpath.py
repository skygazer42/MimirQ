"""Extract HTML text and explicit XPath selections without widening an empty selection."""

from dataclasses import dataclass
from html import escape

from app.infrastructure.runtime.dependencies import optional_import


@dataclass(frozen=True)
class HtmlXPathExtractResult:
    text: str
    matched_nodes: int
    xpath_error: str | None = None


def extract_text_from_html(html: str, *, xpath: str | None = None) -> HtmlXPathExtractResult:
    if not html.strip():
        return HtmlXPathExtractResult(text="", matched_nodes=0)

    etree = optional_import("lxml.etree", feature="html_xpath_extraction", pip_name="lxml")
    lxml_html = optional_import("lxml.html", feature="html_xpath_extraction", pip_name="lxml")
    if etree is None or lxml_html is None:
        return HtmlXPathExtractResult(text="", matched_nodes=0, xpath_error="dependency_missing:lxml")

    parser = lxml_html.HTMLParser(recover=True, remove_comments=False)
    try:
        root = lxml_html.fromstring(html, parser=parser)
    except (etree.ParserError, etree.XMLSyntaxError, ValueError) as exc:
        return HtmlXPathExtractResult(text="", matched_nodes=0, xpath_error=f"parse_failed:{str(exc)[:80]}")

    nodes = [root]
    matched = 0
    if xpath is not None and xpath.strip():
        try:
            selected = root.xpath(xpath)
        except etree.XPathError as exc:
            return HtmlXPathExtractResult(text="", matched_nodes=0, xpath_error=f"xpath_failed:{str(exc)[:120]}")
        nodes = selected if isinstance(selected, list) else [selected]
        matched = len(nodes)
        if not nodes:
            return HtmlXPathExtractResult(text="", matched_nodes=0)

    html_text = optional_import("html_text", feature="html_xpath_text_extraction", pip_name="html-text")
    if html_text is None:
        return HtmlXPathExtractResult(text="", matched_nodes=matched, xpath_error="dependency_missing:html-text")

    fragments = [
        etree.tostring(node, encoding="unicode", method="html", with_tail=False)
        if isinstance(node, etree._Element)
        else escape(str(node), quote=False)
        for node in nodes
    ]
    text = html_text.extract_text("\n".join(fragments), guess_layout=True)
    return HtmlXPathExtractResult(text=text, matched_nodes=matched)


__all__ = ["HtmlXPathExtractResult", "extract_text_from_html"]
