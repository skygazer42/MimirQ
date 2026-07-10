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


def extract_text_from_html(html: str, *, xpath: str | None = None) -> HtmlXPathExtractResult:
    raw = html or ""
    if not raw.strip():
        return HtmlXPathExtractResult(text="", matched_nodes=0)

    lxml_etree = optional_import("lxml.etree", feature="html_xpath_extraction", pip_name="lxml")
    lxml_html = optional_import("lxml.html", feature="html_xpath_extraction", pip_name="lxml")
    if lxml_etree is None or lxml_html is None:
        # No lxml available: best-effort strip using html_text if present.
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
            if isinstance(node, lxml_etree._Element):  # type: ignore[attr-defined]
                try:
                    fragments.append(lxml_etree.tostring(node, encoding="unicode", method="html") or "")
                except Exception:
                    fragments.append(node.text_content() or "")
            else:
                fragments.append(str(node))
        fragments_html = "\n".join([f for f in fragments if (f or "").strip()])

    # Convert to plain text.
    html_text = optional_import("html_text", feature="html_xpath_text_extraction", pip_name="html-text")
    extract_text = getattr(html_text, "extract_text", None) if html_text is not None else None

    text = ""
    if callable(extract_text):
        try:
            text = extract_text(fragments_html or "", guess_layout=True) or ""
        except Exception:
            # Best-effort: fall back to lxml extraction.
            extract_text = None

    if not callable(extract_text):
        try:
            # lxml fallback.
            if nodes:
                extracted: list[str] = []
                for node in nodes:
                    if isinstance(node, lxml_etree._Element):  # type: ignore[attr-defined]
                        extracted.append(node.text_content() or "")
                    else:
                        extracted.append(str(node))
                text = "\n\n".join([t.strip() for t in extracted if (t or "").strip()])
            else:
                text = root.text_content() or ""
        except Exception:
            text = fragments_html or ""

    return HtmlXPathExtractResult(text=text, matched_nodes=matched, xpath_error=xpath_error)
