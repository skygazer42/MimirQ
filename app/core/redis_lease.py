"""
Small owner-safe Redis lease helpers shared by sync and async callers.
"""

from typing import Any

_COMPARE_DELETE_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("DEL", KEYS[1])
end
return 0
"""

_COMPARE_EXPIRE_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("EXPIRE", KEYS[1], ARGV[2])
end
return 0
"""


def try_acquire_redis_lease(
    client: Any,
    key: str,
    *,
    value: str,
    ttl_sec: int,
) -> bool:
    if not key or not value or ttl_sec <= 0:
        return False
    return bool(
        client.set(
            key,
            value,
            ex=max(1, int(ttl_sec)),
            nx=True,
        )
    )

def release_redis_lease(
    client: Any,
    key: str,
    *,
    value: str,
) -> bool:
    if not key or not value:
        return False
    return bool(client.eval(_COMPARE_DELETE_LUA, 1, key, value))


def extend_redis_lease(
    client: Any,
    key: str,
    *,
    value: str,
    ttl_sec: int,
) -> bool:
    if not key or not value or ttl_sec <= 0:
        return False
    return bool(
        client.eval(
            _COMPARE_EXPIRE_LUA,
            1,
            key,
            value,
            max(1, int(ttl_sec)),
        )
    )
