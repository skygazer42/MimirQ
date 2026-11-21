import os


def is_production_env() -> bool:
    return os.getenv("ENV", "").lower() in ("prod", "production")


def parse_csv(value: str | None) -> list[str]:
    """Split a comma-separated setting, ignoring blank items and preserving `*`."""
    if value is None:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]
