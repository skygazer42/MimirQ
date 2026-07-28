from ipaddress import ip_network

import pytest

from scripts.select_free_docker_subnet import compose_network_env, select_free_subnet


def test_select_free_subnet_skips_every_overlapping_network() -> None:
    pool = ip_network("10.254.0.0/21")
    used = [
        ip_network("10.254.0.0/24"),
        ip_network("10.254.1.0/25"),
        ip_network("10.254.2.0/23"),
    ]

    selected = select_free_subnet(used, seed=0, pool=pool, prefixlen=24)

    assert selected == ip_network("10.254.4.0/24")
    assert all(not selected.overlaps(network) for network in used)


def test_compose_network_env_keeps_proxy_trust_values_in_sync() -> None:
    values = compose_network_env(ip_network("10.254.42.0/24"))

    assert values == {
        "MIMIRQ_PROXY_SUBNET": "10.254.42.0/24",
        "WEB_PROXY_IP_DOCKER": "10.254.42.10",
        "FORWARDED_ALLOW_IPS_DOCKER": "127.0.0.1,10.254.42.10",
    }


def test_select_free_subnet_fails_when_the_pool_is_exhausted() -> None:
    pool = ip_network("10.254.0.0/30")

    with pytest.raises(RuntimeError, match="No free Docker subnet"):
        select_free_subnet([pool], seed=0, pool=pool, prefixlen=30)
