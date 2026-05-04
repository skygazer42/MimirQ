from __future__ import annotations

import pytest

from app.core.config import settings
from app.parsing.factory import ParserFactory


@pytest.mark.parametrize("ext", [".js", ".ts", ".tsx", ".py", ".rs"])
def test_source_code_extensions_route_to_text_parser(ext: str) -> None:
    factory = ParserFactory()

    assert factory.resolve_backend(ext, "auto") == "text"
    assert ext in factory.PLAIN_TEXT_EXTENSIONS
    assert ext in settings.allowed_extensions_list
