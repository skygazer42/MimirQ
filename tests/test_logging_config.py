from __future__ import annotations

import logging


def _restore_root(*, level: int, handlers: list[logging.Handler]) -> None:
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in handlers:
        root.addHandler(h)
    root.setLevel(level)


def test_configure_logging_plain_sets_level_without_overriding_handlers(monkeypatch) -> None:
    import app.core.logging_config as lc

    root = logging.getLogger()
    old_level = root.level
    old_handlers = list(root.handlers)
    old_factory = logging.getLogRecordFactory()

    dummy = logging.NullHandler()
    root.addHandler(dummy)
    root.setLevel(logging.WARNING)

    try:
        lc.configure_logging(log_level="DEBUG", log_format="plain")
        assert root.level == logging.DEBUG
        assert dummy in root.handlers
    finally:
        _restore_root(level=old_level, handlers=old_handlers)
        logging.setLogRecordFactory(old_factory)
        monkeypatch.setattr(lc, "_record_factory_installed", False, raising=False)


def test_configure_logging_json_forces_json_formatter(monkeypatch) -> None:
    import app.core.logging_config as lc

    root = logging.getLogger()
    old_level = root.level
    old_handlers = list(root.handlers)
    old_factory = logging.getLogRecordFactory()

    root.addHandler(logging.NullHandler())
    root.setLevel(logging.INFO)

    try:
        lc.configure_logging(log_level="INFO", log_format="json")
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, lc.JSONFormatter)
    finally:
        _restore_root(level=old_level, handlers=old_handlers)
        logging.setLogRecordFactory(old_factory)
        monkeypatch.setattr(lc, "_record_factory_installed", False, raising=False)

