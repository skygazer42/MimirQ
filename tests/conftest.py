import os
import socket

import pytest
from sqlalchemy import text


def _patch_asyncio_threadsafe_wakeup_for_sandbox() -> None:
    """
    In this sandbox environment, Linux socket send syscalls are blocked (EPERM) even for
    AF_UNIX socketpairs. asyncio uses `socket.socketpair()` + `csock.send(b"\\0")` as its
    self-pipe wakeup mechanism for `loop.call_soon_threadsafe(...)`.

    When `send()` is blocked, cross-thread scheduling never wakes the event loop, which
    causes hangs in:
    - anyio.from_thread.start_blocking_portal()
    - Starlette/FastAPI TestClient (uses AnyIO blocking portal internally)

    Workaround: detect this condition and monkeypatch asyncio to wake the selector loop
    using `os.write(fd, b"\\0")` instead of `socket.send(...)`. `os.write()` is permitted
    in this environment.
    """

    # Import lazily so we don't change runtime behavior outside of pytest.
    import asyncio.selector_events as se  # noqa: WPS433

    # Detect whether socket send is blocked by the sandbox.
    try:
        ssock, csock = socket.socketpair()
        try:
            csock.send(b"\0")
            return  # Normal environment: no patch needed.
        except PermissionError:
            pass
        finally:
            ssock.close()
            csock.close()
    except Exception:
        # If detection fails for any reason, do not risk patching asyncio globally.
        return

    def _write_to_self_via_os_write(self) -> None:  # type: ignore[no-untyped-def]
        csock = getattr(self, "_csock", None)
        if csock is None:
            return
        try:
            os.write(csock.fileno(), b"\0")
        except OSError:
            # Mirror asyncio's behavior: swallow wakeup errors, log only in debug mode.
            if getattr(self, "_debug", False):
                try:
                    se.logger.debug("Fail to write a null byte into the self-pipe socket", exc_info=True)
                except Exception:
                    pass

    se.BaseSelectorEventLoop._write_to_self = _write_to_self_via_os_write  # type: ignore[assignment]


def _disable_proxy_env_for_tests() -> None:
    """
    Starlette's TestClient uses httpx.Client without explicitly setting trust_env=False.
    In sandboxed/offline environments we commonly have SOCKS-style proxy env vars set,
    which can cause TestClient requests to hang (waiting on an unreachable proxy).

    Tests should be hermetic and must not depend on outbound network/proxy settings, so we
    clear proxy env vars and ensure localhost/testserver bypass is present.
    """
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        os.environ.pop(key, None)

    # Preserve any existing NO_PROXY entries but ensure local targets are always bypassed.
    existing = str(os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or "")
    parts = {p.strip() for p in existing.split(",") if p.strip()}
    parts.update({"testserver", "localhost", "127.0.0.1"})
    merged = ",".join(sorted(parts))
    os.environ["NO_PROXY"] = merged
    os.environ["no_proxy"] = merged


def _block_outbound_network_for_tests() -> None:
    """
    Keep pytest hermetic by rejecting outbound non-local network access.

    This converts accidental public-network calls into immediate test failures instead of
    long hangs caused by blocked TLS/proxy egress in sandboxed environments.
    """

    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex
    orig_create_connection = socket.create_connection
    orig_getaddrinfo = socket.getaddrinfo

    def _host_allowed(host: object) -> bool:
        if isinstance(host, bytes):
            host = host.decode(errors="ignore")
        raw = str(host or "").strip().lower()
        if not raw:
            return False
        if raw in {"localhost", "::1"}:
            return True
        if raw.startswith("127."):
            return True
        return False

    def _guard(kind: str, address: object) -> None:
        if not isinstance(address, tuple) or not address:
            return
        host = address[0]
        if _host_allowed(host):
            return
        raise RuntimeError(f"Outbound network is disabled during pytest ({kind}): {address!r}")

    def guarded_connect(self, address):  # type: ignore[no-untyped-def]
        _guard("connect", address)
        return orig_connect(self, address)

    def guarded_connect_ex(self, address):  # type: ignore[no-untyped-def]
        _guard("connect_ex", address)
        return orig_connect_ex(self, address)

    def guarded_create_connection(address, *args, **kwargs):  # type: ignore[no-untyped-def]
        _guard("create_connection", address)
        return orig_create_connection(address, *args, **kwargs)

    def guarded_getaddrinfo(host, *args, **kwargs):  # type: ignore[no-untyped-def]
        if not _host_allowed(host):
            raise RuntimeError(f"Outbound network is disabled during pytest (getaddrinfo): {host!r}")
        return orig_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    socket.create_connection = guarded_create_connection
    socket.getaddrinfo = guarded_getaddrinfo


_disable_proxy_env_for_tests()
_block_outbound_network_for_tests()
_patch_asyncio_threadsafe_wakeup_for_sandbox()

# Ensure `app.__init__` runs early in the pytest process so it can backfill
# `datetime.UTC` on Python 3.10 before any test modules import it.
import app  # noqa: F401,E402


def _integration_enabled() -> bool:
    return str(os.getenv("MIMIRQ_INTEGRATION_TESTS", "") or "").strip().lower() in {"1", "true", "yes", "y", "on"}


@pytest.fixture()
def pg_session():
    """
    Postgres-backed DB session for integration tests.

    Disabled by default. Enable with:
      - set MIMIRQ_INTEGRATION_TESTS=1
      - set DATABASE_URL to a dedicated test database
    """
    if not _integration_enabled():
        pytest.skip("Integration tests disabled (set MIMIRQ_INTEGRATION_TESTS=1)")

    # Import models lazily so pure unit tests don't pull DB config eagerly.
    # Ensure required models are registered for create_all.
    import app.models.dataset  # noqa: F401
    import app.models.dataset_profile_scan  # noqa: F401
    import app.models.document  # noqa: F401
    import app.models.ingest_dead_letter  # noqa: F401
    import app.models.tenant  # noqa: F401
    from app.core.database import Base, SessionLocal, engine  # noqa: WPS433

    # Create tables (idempotent).
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        yield db
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()

    # Best-effort cleanup for the next test run.
    try:
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE dataset_profile_scan_runs RESTART IDENTITY CASCADE;"))
            conn.execute(text("TRUNCATE TABLE ingest_dead_letters RESTART IDENTITY CASCADE;"))
            conn.execute(text("TRUNCATE TABLE document_parsed_contents RESTART IDENTITY CASCADE;"))
            conn.execute(text("TRUNCATE TABLE document_chunks RESTART IDENTITY CASCADE;"))
            conn.execute(text("TRUNCATE TABLE document_permissions RESTART IDENTITY CASCADE;"))
            conn.execute(text("TRUNCATE TABLE documents RESTART IDENTITY CASCADE;"))
            conn.execute(text("TRUNCATE TABLE dataset_permissions RESTART IDENTITY CASCADE;"))
            conn.execute(text("TRUNCATE TABLE datasets RESTART IDENTITY CASCADE;"))
            conn.execute(text("TRUNCATE TABLE tenant_members RESTART IDENTITY CASCADE;"))
            conn.execute(text("TRUNCATE TABLE tenants RESTART IDENTITY CASCADE;"))
    except Exception:
        # Do not fail tests due to cleanup issues.
        pass
