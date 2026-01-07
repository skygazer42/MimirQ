"""
Optional Sentry initialization.

Enabled when SENTRY_DSN is set.
"""

from __future__ import annotations

import logging

from app.core.config import settings

logger = logging.getLogger("mimirq.sentry")


def init_sentry() -> bool:
    dsn = str(getattr(settings, "SENTRY_DSN", "") or "").strip()
    if not dsn:
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=dsn,
            integrations=[FastApiIntegration(), SqlalchemyIntegration()],
            traces_sample_rate=float(getattr(settings, "SENTRY_TRACES_SAMPLE_RATE", 0.0) or 0.0),
            send_default_pii=False,
        )
        logger.info("Sentry initialized")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to init Sentry: %s", str(exc)[:200])
        return False

