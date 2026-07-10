
import os
from collections.abc import Iterable

LOCAL_NO_PROXY_HOSTS = ("localhost", "127.0.0.1", "::1")


def _merge_no_proxy_entries(current: str, hosts: Iterable[str]) -> str:
    entries = [
        entry.strip()
        for entry in str(current or "").split(",")
        if entry.strip()
    ]
    seen = set(entries)
    for host in hosts:
        clean = str(host or "").strip()
        if clean and clean not in seen:
            entries.append(clean)
            seen.add(clean)
    return ",".join(entries)


def ensure_local_no_proxy(hosts: Iterable[str] = LOCAL_NO_PROXY_HOSTS) -> None:
    """Keep local infrastructure calls out of global HTTP/SOCKS proxies."""
    host_list = tuple(hosts)
    for env_name in ("NO_PROXY", "no_proxy"):
        os.environ[env_name] = _merge_no_proxy_entries(os.getenv(env_name, ""), host_list)
