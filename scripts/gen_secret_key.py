#!/usr/bin/env python3
"""
Generate a secure SECRET_KEY for MimirQ.

Default output is URL-safe and >= 32 chars (suitable for AUTH_MODE=jwt).
"""


import argparse
import secrets


def main() -> int:
    p = argparse.ArgumentParser(description="Generate a secure SECRET_KEY (URL-safe).")
    p.add_argument(
        "--nbytes",
        type=int,
        default=32,
        help="Number of random bytes before base64-url encoding (default: %(default)s)",
    )
    args = p.parse_args()

    nbytes = max(16, int(args.nbytes or 32))
    key = secrets.token_urlsafe(nbytes)
    print(key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

