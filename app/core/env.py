import os


def is_production_env() -> bool:
    return os.getenv("ENV", "").lower() in ("prod", "production")

