
from types import SimpleNamespace

import pytest

from app.rag.preprocessing import html_xpath


class _Element:
    def __init__(self, text: str) -> None:
        self._text = text

    def text_content(self) -> str:
        return self._text


class _Root:
    def __init__(self, result=None, *, error: Exception | None = None) -> None:
        self.result = result
        self.error = error

    def xpath(self, _xpath: str):
        if self.error is not None:
            raise self.error
        return self.result

    def text_content(self) -> str:
        return "whole document"


def _lxml_modules(root: _Root):
    etree = SimpleNamespace(
        _Element=_Element,
        tostring=lambda node, **_kwargs: f"<p>{node.text_content()}</p>",
    )
    lxml_html = SimpleNamespace(
        HTMLParser=lambda **_kwargs: object(),
        fromstring=lambda _raw, parser: root,
    )
    return etree, lxml_html


def test_empty_html_returns_without_loading_optional_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        html_xpath,
        "optional_import",
        lambda *_args, **_kwargs: pytest.fail("optional dependencies should not load"),
    )

    assert html_xpath.extract_text_from_html(" \n ") == html_xpath.HtmlXPathExtractResult(text="", matched_nodes=0)


@pytest.mark.parametrize("html_text", [None, SimpleNamespace(extract_text=None)])
def test_missing_lxml_returns_raw_html_with_install_hint(monkeypatch: pytest.MonkeyPatch, html_text) -> None:
    def fake_optional_import(name: str, **_kwargs):
        return html_text if name == "html_text" else None

    monkeypatch.setattr(html_xpath, "optional_import", fake_optional_import)

    result = html_xpath.extract_text_from_html("<p>raw</p>", xpath="//p")

    assert result == html_xpath.HtmlXPathExtractResult(
        text="<p>raw</p>",
        matched_nodes=0,
        xpath_error="dependency_missing:lxml (hint: pip install lxml)",
    )


def test_missing_lxml_uses_html_text_and_preserves_failure_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool]] = []

    def extract(raw: str, *, guess_layout: bool) -> str:
        calls.append((raw, guess_layout))
        if "broken" in raw:
            raise ValueError("decode")
        return "plain text"

    def fake_optional_import(name: str, **_kwargs):
        return SimpleNamespace(extract_text=extract) if name == "html_text" else None

    monkeypatch.setattr(html_xpath, "optional_import", fake_optional_import)

    assert html_xpath.extract_text_from_html("<p>ok</p>").text == "plain text"
    broken = html_xpath.extract_text_from_html("<p>broken</p>")
    assert broken.text == "<p>broken</p>"
    assert broken.xpath_error == "dependency_missing:lxml"
    assert calls == [("<p>ok</p>", True), ("<p>broken</p>", True)]


def test_xpath_nodes_are_serialized_before_html_text_conversion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _Root([_Element("alpha"), "scalar"])
    etree, lxml_html_module = _lxml_modules(root)
    seen: list[str] = []

    def fake_optional_import(name: str, **_kwargs):
        if name == "lxml.etree":
            return etree
        if name == "lxml.html":
            return lxml_html_module
        return SimpleNamespace(extract_text=lambda raw, guess_layout: seen.append(raw) or "converted")

    monkeypatch.setattr(html_xpath, "optional_import", fake_optional_import)

    result = html_xpath.extract_text_from_html("<main>raw</main>", xpath="//main/*")

    assert result == html_xpath.HtmlXPathExtractResult(text="converted", matched_nodes=2)
    assert seen == ["<p>alpha</p>\nscalar"]


def test_html_text_failure_falls_back_to_selected_node_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _Root([_Element(" alpha "), " scalar "])
    etree, lxml_html_module = _lxml_modules(root)

    def fail_extract(*_args, **_kwargs):
        raise RuntimeError("html text failed")

    def fake_optional_import(name: str, **_kwargs):
        if name == "lxml.etree":
            return etree
        if name == "lxml.html":
            return lxml_html_module
        return SimpleNamespace(extract_text=fail_extract)

    monkeypatch.setattr(html_xpath, "optional_import", fake_optional_import)

    result = html_xpath.extract_text_from_html("<main>raw</main>", xpath="//main/*")

    assert result == html_xpath.HtmlXPathExtractResult(text="alpha\n\nscalar", matched_nodes=2)


def test_xpath_and_parse_failures_preserve_existing_fallback_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _Root(error=ValueError("bad xpath"))
    etree, lxml_html_module = _lxml_modules(root)

    def fake_optional_import(name: str, **_kwargs):
        if name == "lxml.etree":
            return etree
        if name == "lxml.html":
            return lxml_html_module
        return SimpleNamespace(extract_text=lambda raw, guess_layout: f"plain:{raw}")

    monkeypatch.setattr(html_xpath, "optional_import", fake_optional_import)
    xpath_result = html_xpath.extract_text_from_html("<p>raw</p>", xpath="//[")
    assert xpath_result == html_xpath.HtmlXPathExtractResult(
        text="plain:<p>raw</p>",
        matched_nodes=0,
        xpath_error="xpath_failed:bad xpath",
    )

    lxml_html_module.fromstring = lambda _raw, parser: (_ for _ in ()).throw(ValueError("bad html"))
    parse_result = html_xpath.extract_text_from_html("<p>raw</p>")
    assert parse_result == html_xpath.HtmlXPathExtractResult(
        text="<p>raw</p>", matched_nodes=0, xpath_error="parse_failed:bad html"
    )
