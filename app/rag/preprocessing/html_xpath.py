"""
HTML XPath extraction helpers.

Use cases:
- /pipeline/clean-preview for input_format=html
- HTML parser optional fine-grained extraction before text conversion

This module never performs any network access.
"""

from dataclasses import dataclass

from app.core.optional_deps import optional_import


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
                text=extract_text(raw, guess_layout=True) or "",
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


def _parse_root(raw: str, lxml_html: object) -> tuple[object | None, HtmlXPathExtractResult | None]:
    parser = lxml_html.HTMLParser(recover=True, remove_comments=False)
    try:
        return lxml_html.fromstring(raw, parser=parser), None
    except Exception as exc:
        return None, HtmlXPathExtractResult(
            text=raw,
            matched_nodes=0,
            xpath_error=f"parse_failed:{str(exc)[:80]}",
        )


def _select_nodes(root: object | None, xpath: str | None) -> tuple[list[object] | None, str | None]:
    nodes: list[object] | None = None
    xpath_error: str | None = None
    if xpath and str(xpath).strip():
        try:
            result = root.xpath(str(xpath))
            nodes = list(result) if isinstance(result, (list, tuple)) else [result]
        except Exception as exc:
            xpath_error = f"xpath_failed:{str(exc)[:120]}"
            nodes = None
    return nodes, xpath_error


def _serialize_nodes(raw: str, nodes: list[object] | None, lxml_etree: object) -> tuple[str, int]:
    if not nodes:
        return raw, 0

    fragments: list[str] = []
    for node in nodes:
        if isinstance(node, lxml_etree._Element):  # type: ignore[attr-defined]
            try:
                fragments.append(lxml_etree.tostring(node, encoding="unicode", method="html") or "")
            except Exception:
                fragments.append(node.text_content() or "")
        else:
            fragments.append(str(node))
    return "\n".join([fragment for fragment in fragments if (fragment or "").strip()]), len(nodes)


def _extract_html_text(fragments_html: str) -> tuple[bool, str]:
    html_text = optional_import("html_text", feature="html_xpath_text_extraction", pip_name="html-text")
    extract_text = getattr(html_text, "extract_text", None) if html_text is not None else None
    if callable(extract_text):
        try:
            return True, extract_text(fragments_html or "", guess_layout=True) or ""
        except Exception:
            pass
    return False, ""


def _extract_with_lxml_fallback(
    root: object | None,
    nodes: list[object] | None,
    fragments_html: str,
    lxml_etree: object,
) -> str:
    try:
        if not nodes:
            return root.text_content() or ""
        extracted: list[str] = []
        for node in nodes:
            if isinstance(node, lxml_etree._Element):  # type: ignore[attr-defined]
                extracted.append(node.text_content() or "")
            else:
                extracted.append(str(node))
        return "\n\n".join([text.strip() for text in extracted if (text or "").strip()])
    except Exception:
        return fragments_html or ""


def extract_text_from_html(html: str, *, xpath: str | None = None) -> HtmlXPathExtractResult:
    raw = html or ""
    if not raw.strip():
        return HtmlXPathExtractResult(text="", matched_nodes=0)

    lxml_etree = optional_import("lxml.etree", feature="html_xpath_extraction", pip_name="lxml")
    lxml_html = optional_import("lxml.html", feature="html_xpath_extraction", pip_name="lxml")
    if lxml_etree is None or lxml_html is None:
        return _missing_lxml_result(raw)

    root, parse_error = _parse_root(raw, lxml_html)
    if parse_error is not None:
        return parse_error

    nodes, xpath_error = _select_nodes(root, xpath)
    fragments_html, matched = _serialize_nodes(raw, nodes, lxml_etree)
    extracted, text = _extract_html_text(fragments_html)
    if not extracted:
        text = _extract_with_lxml_fallback(root, nodes, fragments_html, lxml_etree)

    return HtmlXPathExtractResult(text=text, matched_nodes=matched, xpath_error=xpath_error)
