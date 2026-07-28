#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import json
import subprocess
import sys
from collections.abc import Iterable, Mapping

Network = ipaddress.IPv4Network | ipaddress.IPv6Network
DEFAULT_POOL = ipaddress.ip_network("10.254.0.0/16")
DEFAULT_PREFIX_LENGTH = 24


def select_free_subnet(
    used_subnets: Iterable[Network],
    *,
    seed: int,
    pool: Network = DEFAULT_POOL,
    prefixlen: int = DEFAULT_PREFIX_LENGTH,
) -> Network:
    if prefixlen < pool.prefixlen:
        raise ValueError("Subnet prefix cannot be broader than the candidate pool")

    candidates = tuple(pool.subnets(new_prefix=prefixlen)) if prefixlen > pool.prefixlen else (pool,)
    occupied = tuple(used_subnets)
    start = seed % len(candidates)
    for offset in range(len(candidates)):
        candidate = candidates[(start + offset) % len(candidates)]
        if all(
            candidate.version != existing.version or not candidate.overlaps(existing)
            for existing in occupied
        ):
            return candidate

    raise RuntimeError(f"No free Docker subnet remains in {pool}")


def compose_network_env(subnet: Network) -> dict[str, str]:
    proxy_ip = subnet.network_address + 10
    if proxy_ip >= subnet.broadcast_address:
        raise ValueError(f"Subnet {subnet} is too small for the web proxy address")
    return {
        "MIMIRQ_PROXY_SUBNET": str(subnet),
        "WEB_PROXY_IP_DOCKER": str(proxy_ip),
        "FORWARDED_ALLOW_IPS_DOCKER": f"127.0.0.1,{proxy_ip}",
    }


def docker_network_subnets() -> tuple[Network, ...]:
    network_ids = subprocess.run(
        ["docker", "network", "ls", "-q"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    if not network_ids:
        return ()

    payload = subprocess.run(
        ["docker", "network", "inspect", *network_ids],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    networks = json.loads(payload)
    discovered: list[Network] = []
    for network in networks:
        ipam = network.get("IPAM") if isinstance(network, Mapping) else None
        configs = ipam.get("Config", ()) if isinstance(ipam, Mapping) else ()
        for config in configs or ():
            raw_subnet = config.get("Subnet") if isinstance(config, Mapping) else None
            if not raw_subnet:
                continue
            try:
                discovered.append(ipaddress.ip_network(str(raw_subnet), strict=False))
            except ValueError:
                print(f"Ignoring unparseable Docker subnet: {raw_subnet}", file=sys.stderr)
    return tuple(discovered)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Select an unused subnet and emit synchronized Compose environment values."
    )
    parser.add_argument("--seed", type=int, default=0, help="Deterministic candidate rotation seed")
    parser.add_argument("--pool", default=str(DEFAULT_POOL), help="Candidate address pool")
    parser.add_argument("--prefixlen", type=int, default=DEFAULT_PREFIX_LENGTH)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    pool = ipaddress.ip_network(args.pool, strict=False)
    subnet = select_free_subnet(
        docker_network_subnets(),
        seed=args.seed,
        pool=pool,
        prefixlen=args.prefixlen,
    )
    for name, value in compose_network_env(subnet).items():
        print(f"{name}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
