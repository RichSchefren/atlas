"""Security boundary tests for the localhost FastAPI surface."""

from dataclasses import dataclass

import pytest


@dataclass
class _DispatchResult:
    ok: bool = True
    result: dict | None = None
    error: str | None = None


class _FakeMCPServer:
    def __init__(self):
        self.dispatched: list[tuple[str, dict]] = []

    def list_tools(self):
        return [{"name": "memory.forget"}]

    async def dispatch(self, name, params):
        self.dispatched.append((name, params))
        return _DispatchResult(result={"name": name})


@pytest.fixture
def fake_server():
    return _FakeMCPServer()


@pytest.fixture
def http_app(fake_server):
    from atlas_core.api import create_http_app

    return create_http_app(
        mcp_server=fake_server,
        bearer_token="test-token-that-is-long-enough-for-local-auth",
        allowed_origins=["app://obsidian.md"],
    )


@pytest.fixture
async def client(http_app):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=http_app), base_url="http://test"
    ) as value:
        yield value


def _auth_headers():
    return {"Authorization": "Bearer test-token-that-is-long-enough-for-local-auth"}


async def test_health_is_the_only_anonymous_route(client):
    assert (await client.get("/health")).status_code == 200
    assert (await client.get("/tools")).status_code == 401
    assert (await client.get("/verify-chain")).status_code == 401
    assert (await client.get("/events/stats")).status_code == 401


async def test_authorized_dispatch_reaches_mcp_server(client, fake_server):
    response = await client.post(
        "/tools/memory.forget",
        headers=_auth_headers(),
        json={"params": {"memory_id": "m-1"}},
    )

    assert response.status_code == 200
    assert fake_server.dispatched == [
        ("memory.forget", {"memory_id": "m-1"})
    ]


async def test_unauthorized_dispatch_never_reaches_mcp_server(client, fake_server):
    response = await client.post(
        "/tools/memory.forget",
        json={"params": {"memory_id": "m-1"}},
    )

    assert response.status_code == 401
    assert fake_server.dispatched == []


async def test_cors_rejects_untrusted_web_origins(client):
    response = await client.options(
        "/tools/memory.forget",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


async def test_cors_allows_configured_obsidian_origin(client):
    response = await client.options(
        "/tools/memory.forget",
        headers={
            "Origin": "app://obsidian.md",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "app://obsidian.md"
