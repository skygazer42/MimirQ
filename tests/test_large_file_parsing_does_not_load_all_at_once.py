from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any, Callable, List, Tuple

from app.parsing.parsers.base_parser import BaseAdvancedParser


class _GuardedFile:
    """
    Wrapper around a real binary file handle that forbids full-buffer reads.

    We use this to ensure parsing code paths don't call `read()` with no size
    (which loads the entire file into memory at once).
    """

    def __init__(self, f: Any) -> None:
        self._f = f

    def __enter__(self) -> "_GuardedFile":
        self._f.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> Any:  # noqa: ANN001
        return self._f.__exit__(exc_type, exc, tb)

    def read(self, size: int = -1) -> bytes:
        assert size != -1, "parsing must not read the entire file into memory in one call"
        return self._f.read(size)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._f, name)


class _DummyAdvancedParser(BaseAdvancedParser):
    SUPPORTED_EXTENSIONS = {".pdf"}

    def _create_parser(self) -> Any:
        return object()

    def _get_parser_name(self) -> str:
        return "dummy"

    def _check_parser_installation(self, parser: Any) -> Tuple[bool, str]:
        return (True, "")

    def _call_parse_method(
        self,
        parser: Any,
        file_path: Path,
        binary: bytes | None,
        callback: Callable[[float, str], None],
        **kwargs: Any,
    ) -> Tuple[List, List]:
        # The "streaming" contract for O23: BaseAdvancedParser should not
        # eagerly load full file bytes into memory.
        assert binary is None
        return (["hello"], [])


def test_large_file_parsing_does_not_load_all_at_once(monkeypatch, tmp_path: Path) -> None:
    # Synthetic "large" input; size is intentionally non-trivial but still fast
    # for unit tests.
    path = tmp_path / "large.pdf"
    path.write_bytes(b"0" * (8 * 1024 * 1024))

    real_open = builtins.open

    def _guarded_open(*args: Any, **kwargs: Any) -> Any:
        return _GuardedFile(real_open(*args, **kwargs))

    monkeypatch.setattr(builtins, "open", _guarded_open, raising=True)

    parser = _DummyAdvancedParser()
    docs = parser.parse(path)
    assert len(docs) == 1
    assert (docs[0].page_content or "").strip() == "hello"
