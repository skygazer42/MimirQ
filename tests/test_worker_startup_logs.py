
import importlib
import logging
import socket


def test_worker_warns_when_redis_unreachable(caplog, monkeypatch):  # noqa: ANN001
    """
    Worker startup should be resilient to cold-start Redis.

    We don't spin up Redis here; instead we simulate a connect failure and assert
    the worker settings emit a clear WARNING and use non-trivial retry defaults.
    """

    def _raise(*args, **kwargs):  # noqa: ANN001, ANN202
        raise OSError("simulated redis connect failure")

    monkeypatch.setattr(socket, "create_connection", _raise, raising=True)

    caplog.set_level(logging.WARNING)

    import app.tasks.worker as worker_module

    importlib.reload(worker_module)

    assert worker_module.WorkerSettings.redis_settings.conn_retries >= 30
    assert any("Redis not reachable yet" in rec.message for rec in caplog.records)

