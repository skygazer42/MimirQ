"""Shared parsing for comma-separated configuration values."""


def parse_csv(value: str | None) -> list[str]:
    """
    Parse a comma-separated env/config value into a list of non-empty strings.

    - Strips whitespace around items
    - Ignores empty items
    - Preserves literal "*" when provided
    """
    if value is None:
        return []
    raw = str(value).strip()
    if not raw:
        return []
    if raw == "*":
        return ["*"]
    return [part.strip() for part in raw.split(",") if part.strip()]


__all__ = ["parse_csv"]
