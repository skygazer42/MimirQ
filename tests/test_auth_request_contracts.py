"""Request-level identity checks with signed tokens and an in-memory ASGI transport."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import jwt
from fastapi import Depends, FastAPI, Request

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.infrastructure.config import settings


def test_signed_request_identity_and_workspace(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "test")
    for key, value in {
        "AUTH_MODE": "jwt",
        "ALGORITHM": "HS256",
        "SECRET_KEY": "request-contract-test-signing-key-000000",
        "SECRET_KEY_FALLBACKS": "",
        "JWT_ISSUER": "",
        "JWT_AUDIENCE": "",
        "JWT_TENANT_CLAIM": "tenant_id",
        "JWT_ENFORCE_TENANT_HEADER_MATCH": False,
        "TENANT_HEADER_TRUSTED": False,
    }.items():
        monkeypatch.setattr(settings, key, value)
    user_id, tenant_id = str(uuid4()), str(uuid4())
    app = FastAPI()

    @app.get("/identity")
    async def identity(
        request: Request,
        workspace: UUID = Depends(get_tenant_id),
        account: str = Depends(get_current_account_id),
    ) -> dict:
        return {"account": account, "workspace": str(workspace), "state_user": request.state.user_id}

    def token(**claims) -> str:
        payload = {"sub": user_id, "exp": datetime.now(UTC) + timedelta(minutes=5), "tenant_id": tenant_id}
        payload.update(claims)
        return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

    async def verify() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/identity")).status_code == 401
            assert (await client.get("/identity", headers={"Authorization": "Basic bad"})).status_code == 401
            assert (await client.get("/identity", headers={"Authorization": "Bearer invalid"})).status_code == 401
            expired = token(exp=datetime.now(UTC) - timedelta(seconds=1))
            assert (await client.get("/identity", headers={"Authorization": f"Bearer {expired}"})).status_code == 401
            forged = jwt.encode({"sub": user_id, "exp": 4_000_000_000}, "other-signing-key-0000000000000000000")
            assert (await client.get("/identity", headers={"Authorization": f"Bearer {forged}"})).status_code == 401
            missing_subject = jwt.encode({"exp": 4_000_000_000}, settings.SECRET_KEY)
            assert (
                await client.get("/identity", headers={"Authorization": f"Bearer {missing_subject}"})
            ).status_code == 401
            missing_expiry = jwt.encode({"sub": user_id}, settings.SECRET_KEY)
            assert (
                await client.get("/identity", headers={"Authorization": f"Bearer {missing_expiry}"})
            ).status_code == 401
            headers = {"Authorization": f"Bearer {token()}", "X-Tenant-ID": str(uuid4())}
            response = await client.get("/identity", headers=headers)
            assert response.status_code == 200
            assert response.json() == {"account": user_id, "workspace": tenant_id, "state_user": user_id}
            monkeypatch.setattr(settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", True)
            assert (await client.get("/identity", headers=headers)).status_code == 401
            assert (
                await client.get("/identity", headers={"Authorization": headers["Authorization"]})
            ).status_code == 400
            headers["X-Tenant-ID"] = tenant_id
            assert (await client.get("/identity", headers=headers)).status_code == 200
            headers["X-Tenant-ID"] = "not-a-uuid"
            assert (await client.get("/identity", headers=headers)).status_code == 400
            monkeypatch.setattr(settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", False)
            assert (
                await client.get("/identity", headers={"Authorization": f"Bearer {token(tenant_id='bad')}"})
            ).status_code == 401
            monkeypatch.setattr(settings, "JWT_TENANT_CLAIM", "")
            monkeypatch.setenv("ENV", "production")
            headers = {"Authorization": f"Bearer {token()}", "X-Tenant-ID": settings.DEFAULT_TENANT_ID}
            assert (await client.get("/identity", headers=headers)).status_code == 200
            headers["X-Tenant-ID"] = str(uuid4())
            assert (await client.get("/identity", headers=headers)).status_code == 400

    asyncio.run(verify())


def test_explicit_development_headers_do_not_invent_an_account(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setattr(settings, "AUTH_MODE", "header")
    app = FastAPI()

    @app.get("/identity")
    async def identity(request: Request) -> dict:
        account = await get_current_account_id(request)
        workspace = await get_tenant_id(request)
        return {"account": account, "workspace": str(workspace), "source": request.state.tenant_id_source}

    async def verify() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/identity")).status_code == 401
            response = await client.get("/identity", headers={"X-User-ID": "dev-user"})
            assert response.json() == {
                "account": "dev-user",
                "workspace": settings.DEFAULT_TENANT_ID,
                "source": "default",
            }

    asyncio.run(verify())
