from __future__ import annotations

import asyncio
from datetime import UTC
from datetime import datetime as real_datetime
from zoneinfo import ZoneInfo


class _FakeDateTime:
    last_tz = None

    @classmethod
    def now(cls, tz=None):  # noqa: ANN001
        cls.last_tz = tz
        return real_datetime(2026, 5, 11, 12, 34, 56, tzinfo=tz or UTC)


def test_get_current_time_defaults_to_utc(monkeypatch):  # noqa: ANN001
    from app.rag.tools import mcp_tools

    _FakeDateTime.last_tz = None
    monkeypatch.setattr(mcp_tools, "datetime", _FakeDateTime, raising=True)

    payload = mcp_tools.get_current_time()

    assert _FakeDateTime.last_tz is UTC
    assert payload["datetime"].startswith("2026-05-11 12:34:56")


def test_get_current_time_respects_named_timezone(monkeypatch):  # noqa: ANN001
    from app.rag.tools import mcp_tools

    _FakeDateTime.last_tz = None
    monkeypatch.setattr(mcp_tools, "datetime", _FakeDateTime, raising=True)

    mcp_tools.get_current_time(timezone="Asia/Shanghai")

    assert _FakeDateTime.last_tz == ZoneInfo("Asia/Shanghai")


def test_time_injector_uses_utc_timezone(monkeypatch):  # noqa: ANN001
    from app.rag.middleware import dynamic_prompt

    _FakeDateTime.last_tz = None
    monkeypatch.setattr(dynamic_prompt, "datetime", _FakeDateTime, raising=True)

    text = dynamic_prompt.TimeInjector().get_time_context()

    assert _FakeDateTime.last_tz is UTC
    assert "UTC" in text


def test_time_context_provider_uses_utc_timezone(monkeypatch):  # noqa: ANN001
    from app.rag.middleware import context_injection

    _FakeDateTime.last_tz = None
    monkeypatch.setattr(context_injection, "datetime", _FakeDateTime, raising=True)

    items = asyncio.run(context_injection.TimeContextProvider().get_context({}))

    assert _FakeDateTime.last_tz is UTC
    assert items[0].content.startswith("Current time: 2026-05-11 12:34:56")
