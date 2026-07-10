"""Alembic CLI wrapper.

Why this exists:
- `alembic` is typically installed as a console script, but in some Windows/CI
  environments the entrypoint may not be available on PATH.
- This wrapper makes `make db-upgrade` work reliably via `python scripts/alembic_cli.py ...`.
"""


import sys


def main(argv: list[str]) -> int:
    from alembic.config import main as alembic_main

    return int(alembic_main(argv=argv) or 0)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

