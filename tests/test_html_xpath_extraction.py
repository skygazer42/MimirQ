from types import SimpleNamespace

import pytest

from app.rag.ingestion.governance.markup import html_xpath


class _XPathError(ValueError):
    pass


class _Element:
    def __init__(self, text):
        self.text = text

    def text_content(self):
        return self.text


class _Root:
    def __init__(self, result=None, *, error=None):
        self.result = result
        self.error = error

    def xpath(self, _expression):
        if self.error is not None:
            raise self.error
        return self.result


def _lxml_modules(root):
    etree = SimpleNamespace(
        _Element=_Element,
        ParserError=ValueError,
        XMLSyntaxError=ValueError,
        XPathError=_XPathError,
        tostring=lambda node, **_kwargs: f"<p>{node.text_content()}</p>",
    )
    html = SimpleNamespace(HTMLParser=lambda **_kwargs: object(), fromstring=lambda _raw, parser: root)
    return etree, html


def test_empty_html_returns_without_loading_optional_dependencies(monkeypatch):
    monkeypatch.setattr(html_xpath, "optional_import", lambda *_args, **_kwargs: pytest.fail("unexpected import"))
    assert html_xpath.extract_text_from_html(" \n ") == html_xpath.HtmlXPathExtractResult(text="", matched_nodes=0)


def test_missing_lxml_returns_dependency_error_without_raw_html(monkeypatch):
    monkeypatch.setattr(html_xpath, "optional_import", lambda *_args, **_kwargs: None)
    assert html_xpath.extract_text_from_html("<p>raw</p>", xpath="//p") == html_xpath.HtmlXPathExtractResult(
        text="", matched_nodes=0, xpath_error="dependency_missing:lxml"
    )


def test_missing_lxml_does_not_bypass_xpath_with_html_text(monkeypatch):
    seen = []
    extractor = SimpleNamespace(extract_text=lambda *args, **kwargs: seen.append(args))
    monkeypatch.setattr(
        html_xpath, "optional_import", lambda name, **_kwargs: extractor if name == "html_text" else None
    )
    result = html_xpath.extract_text_from_html("<p>raw</p>", xpath="//private")
    assert result.text == ""
    assert result.xpath_error == "dependency_missing:lxml"
    assert seen == []


def test_xpath_nodes_are_serialized_before_html_text_conversion(monkeypatch):
    etree, html = _lxml_modules(_Root([_Element("alpha"), "<scalar>"]))
    seen = []
    modules = {
        "lxml.etree": etree,
        "lxml.html": html,
        "html_text": SimpleNamespace(extract_text=lambda raw, guess_layout: seen.append(raw) or "converted"),
    }
    monkeypatch.setattr(html_xpath, "optional_import", lambda name, **_kwargs: modules[name])
    result = html_xpath.extract_text_from_html("<main>raw</main>", xpath="//main/*")
    assert result == html_xpath.HtmlXPathExtractResult(text="converted", matched_nodes=2)
    assert seen == ["<p>alpha</p>\n&lt;scalar&gt;"]


def test_html_text_failure_propagates_after_xpath_selection(monkeypatch):
    etree, html = _lxml_modules(_Root([_Element("alpha")]))

    def fail(*_args, **_kwargs):
        raise RuntimeError("html text failed")

    modules = {"lxml.etree": etree, "lxml.html": html, "html_text": SimpleNamespace(extract_text=fail)}
    monkeypatch.setattr(html_xpath, "optional_import", lambda name, **_kwargs: modules[name])
    with pytest.raises(RuntimeError, match="html text failed"):
        html_xpath.extract_text_from_html("<main>raw</main>", xpath="//main/*")


def test_xpath_and_parse_failures_return_errors_without_unselected_text(monkeypatch):
    etree, html = _lxml_modules(_Root(error=_XPathError("bad xpath")))
    modules = {"lxml.etree": etree, "lxml.html": html}
    monkeypatch.setattr(html_xpath, "optional_import", lambda name, **_kwargs: modules[name])
    assert html_xpath.extract_text_from_html("<p>raw</p>", xpath="//[") == html_xpath.HtmlXPathExtractResult(
        text="", matched_nodes=0, xpath_error="xpath_failed:bad xpath"
    )
    html.fromstring = lambda _raw, parser: (_ for _ in ()).throw(ValueError("bad html"))
    assert html_xpath.extract_text_from_html("<p>raw</p>") == html_xpath.HtmlXPathExtractResult(
        text="", matched_nodes=0, xpath_error="parse_failed:bad html"
    )
