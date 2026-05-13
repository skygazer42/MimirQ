from __future__ import annotations

from pathlib import Path

import pytest


def test_mathpix_parser_noops_without_api_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.parsing.parsers.mathpix_parser import MathpixParser

    monkeypatch.setattr(settings, "MATHPIX_APP_ID", "", raising=False)
    monkeypatch.setattr(settings, "MATHPIX_APP_KEY", "", raising=False)

    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    with pytest.raises(RuntimeError, match="Mathpix is not configured"):
        MathpixParser().parse(pdf)


def test_mathpix_parser_parses_via_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.core.config import settings
    from app.parsing.parsers.mathpix_parser import MathpixParser

    monkeypatch.setattr(settings, "MATHPIX_APP_ID", "id", raising=False)
    monkeypatch.setattr(settings, "MATHPIX_APP_KEY", "key", raising=False)

    async def _fake_backend_async(**_kwargs):  # noqa: ANN001
        return "# Parsed by Mathpix\n\nEquation: $a^2+b^2=c^2$"

    monkeypatch.setattr(
        "app.parsing.parsers.mathpix_parser._call_mathpix_backend_async",
        _fake_backend_async,
    )

    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    docs = MathpixParser().parse(pdf)
    assert len(docs) == 1
    assert "Parsed by Mathpix" in (docs[0].page_content or "")
    meta = docs[0].metadata or {}
    assert meta.get("parser_backend") == "mathpix"
