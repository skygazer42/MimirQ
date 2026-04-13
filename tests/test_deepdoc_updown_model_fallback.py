from __future__ import annotations

from pathlib import Path


class _DummyOCR:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        pass


class _DummyLayout:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        pass


class _DummyTable:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        pass


class _DummyRecognizer:
    pass


def test_integrated_pdf_parser_disables_updown_model_when_load_fails(monkeypatch, tmp_path: Path) -> None:
    import app.deepdoc.parser.pdf_parser as pdf_mod

    monkeypatch.setattr(pdf_mod, "_ensure_vision_runtime", lambda: (_DummyOCR, _DummyLayout, _DummyTable, _DummyRecognizer), raising=True)
    monkeypatch.setattr(pdf_mod, "_load_updown_concat_model", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("model load failed")), raising=True)
    monkeypatch.setattr(pdf_mod, "snapshot_download", lambda **_kwargs: str(tmp_path), raising=True)

    parser = pdf_mod.IntegratedPipelinePdfParser()

    assert getattr(parser, "updown_cnt_mdl", None) is None
    assert getattr(parser, "_updown_cnt_model_error", "")
