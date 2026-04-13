from __future__ import annotations

import asyncio

import pytest

from app.services.chat_response_cache import (
    acquire_inflight_chat_response,
    clear_inflight_chat_responses,
    reject_inflight_chat_response,
    resolve_inflight_chat_response,
)


@pytest.mark.asyncio
async def test_inflight_chat_response_singleflight_coalesces_followers() -> None:
    clear_inflight_chat_responses()
    key = "chat:test:coalesce"

    is_leader, leader_future = await acquire_inflight_chat_response(key)
    is_follower, follower_future = await acquire_inflight_chat_response(key)

    assert is_leader is True
    assert is_follower is False
    assert follower_future is leader_future

    payload = {"content": "cached", "citations": [], "metrics": {"elapsed_sec": 1.23}}
    resolve_inflight_chat_response(key, payload)

    assert await asyncio.shield(leader_future) == payload
    assert await asyncio.shield(follower_future) == payload


@pytest.mark.asyncio
async def test_inflight_chat_response_singleflight_releases_key_after_failure() -> None:
    clear_inflight_chat_responses()
    key = "chat:test:failure"

    is_leader, future = await acquire_inflight_chat_response(key)
    assert is_leader is True

    err = RuntimeError("boom")
    reject_inflight_chat_response(key, err)

    with pytest.raises(RuntimeError, match="boom"):
        await asyncio.shield(future)

    next_is_leader, next_future = await acquire_inflight_chat_response(key)
    assert next_is_leader is True
    assert next_future is not future
