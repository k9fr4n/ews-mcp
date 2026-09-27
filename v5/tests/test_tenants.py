"""Per-request mailbox credential parsing and tenant isolation."""

from types import SimpleNamespace

import pytest

from conftest import make_settings
from ewsmcp.tenants import (
    MissingTenantCredentials,
    TenantContextPool,
    TenantPoolFull,
    credentials_from_headers,
)


def test_credentials_are_read_from_request_headers():
    values = credentials_from_headers(
        [
            (b"x-ews-email", b"alice@example.com"),
            (b"x-ews-password", b"secret"),
        ],
        make_settings(),
    )
    assert values == (
        "alice@example.com",
        "alice@example.com",
        "secret",
        "https://mail.corp.example/EWS/Exchange.asmx",
    )


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"x-ews-email", b"alice@example.com")],
        [
            (b"x-ews-email", b"alice@example.com"),
            (b"x-ews-password", b"one"),
            (b"x-ews-password", b"two"),
        ],
    ],
)
def test_missing_or_duplicate_credentials_are_rejected(headers):
    with pytest.raises(MissingTenantCredentials):
        credentials_from_headers(headers, make_settings())


def test_endpoint_override_requires_server_allowlist():
    headers = [
        (b"x-ews-email", b"alice@example.com"),
        (b"x-ews-password", b"secret"),
        (b"x-ews-server-url", b"https://other.example/EWS/Exchange.asmx"),
    ]
    with pytest.raises(MissingTenantCredentials, match="allowlist"):
        credentials_from_headers(headers, make_settings())
    settings = make_settings(
        ews_http_allowed_server_urls=("https://other.example/EWS/Exchange.asmx")
    )
    assert credentials_from_headers(headers, settings)[3] == (
        "https://other.example/EWS/Exchange.asmx"
    )


@pytest.mark.asyncio
async def test_pool_reuses_and_isolates_mailbox_contexts(monkeypatch):
    import ewsmcp.tenants as tenants

    built = []

    def fake_build(settings, tenant_id=""):
        context = SimpleNamespace(
            settings=settings,
            tenant_id=tenant_id,
            manager=None,
            sync=None,
            cache=None,
            gateway=SimpleNamespace(_pool=None),
        )
        built.append(context)
        return context

    async def fake_start(context):
        return None

    monkeypatch.setattr(tenants, "build_context", fake_build)
    monkeypatch.setattr(tenants, "start_connection_manager", fake_start)
    settings = make_settings(ews_http_header_auth=True, mcp_transport="http")
    pool = TenantContextPool(settings, max_tenants=2)
    alice_headers = [(b"x-ews-email", b"alice@example.com"), (b"x-ews-password", b"alice-secret")]
    bob_headers = [(b"x-ews-email", b"bob@example.com"), (b"x-ews-password", b"bob-secret")]

    alice_id, alice = await pool.acquire(alice_headers)
    same_id, same = await pool.acquire(alice_headers)
    bob_id, bob = await pool.acquire(bob_headers)
    assert same_id == alice_id
    assert same is alice
    assert bob_id != alice_id
    assert alice.settings.ews_email == "alice@example.com"
    assert bob.settings.ews_email == "bob@example.com"
    assert alice.settings.data_dir != bob.settings.data_dir
    assert "alice-secret" not in alice.settings.data_dir
    assert len(built) == 2

    await pool.release(alice_id)
    await pool.release(alice_id)
    await pool.release(bob_id)
    await pool.close()


@pytest.mark.asyncio
async def test_pool_hard_caps_active_tenant_contexts(monkeypatch):
    import ewsmcp.tenants as tenants

    def fake_build(settings, tenant_id=""):
        return SimpleNamespace(
            settings=settings,
            tenant_id=tenant_id,
            manager=None,
            sync=None,
            cache=None,
            gateway=SimpleNamespace(_pool=None),
        )

    async def fake_start(context):
        return None

    monkeypatch.setattr(tenants, "build_context", fake_build)
    monkeypatch.setattr(tenants, "start_connection_manager", fake_start)
    pool = TenantContextPool(
        make_settings(ews_http_header_auth=True, mcp_transport="http"),
        max_tenants=1,
    )
    alice = [(b"x-ews-email", b"alice@example.com"), (b"x-ews-password", b"alice-secret")]
    bob = [(b"x-ews-email", b"bob@example.com"), (b"x-ews-password", b"bob-secret")]

    alice_id, _ = await pool.acquire(alice)
    with pytest.raises(TenantPoolFull):
        await pool.acquire(bob)
    await pool.release(alice_id)
    bob_id, _ = await pool.acquire(bob)
    assert len(pool._entries) == 1
    await pool.release(bob_id)
    await pool.close()
