"""Per-request Exchange identity parsing and isolated tenant context pooling."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterable, Optional, Tuple

from .server import build_context, start_connection_manager

logger = logging.getLogger(__name__)


class MissingTenantCredentials(ValueError):
    """Raised when an HTTP request omits required mailbox credentials."""


class TenantPoolFull(RuntimeError):
    """Raised when every retained mailbox context is currently in use."""


def _header_values(headers: Optional[Iterable[Tuple[Any, Any]]]) -> Dict[bytes, list[str]]:
    found: Dict[bytes, list[str]] = {}
    for name, value in headers or []:
        key = name.lower() if isinstance(name, bytes) else str(name).encode().lower()
        if isinstance(value, bytes):
            try:
                decoded = value.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise MissingTenantCredentials("credential headers must be UTF-8") from exc
        else:
            decoded = str(value)
        found.setdefault(key, []).append(decoded.strip())
    return found


def credentials_from_headers(headers, base_settings) -> tuple[str, str, str, str]:
    values = _header_values(headers)

    def one(name: bytes, *, required: bool) -> Optional[str]:
        entries = values.get(name, [])
        if len(entries) > 1:
            raise MissingTenantCredentials("duplicate mailbox credential header")
        value = entries[0] if entries else None
        if required and not value:
            raise MissingTenantCredentials("missing required mailbox credential header")
        return value or None

    email = one(b"x-ews-email", required=True)
    password = one(b"x-ews-password", required=True)
    username = one(b"x-ews-username", required=False) or email
    endpoint = (one(b"x-ews-server-url", required=False)
                or base_settings.ews_server_url).rstrip("/")
    allowed = {base_settings.ews_server_url.rstrip("/")}
    allowed.update(
        item.strip().rstrip("/")
        for item in (base_settings.ews_http_allowed_server_urls or "").split(",")
        if item.strip()
    )
    if endpoint.rstrip("/") not in allowed:
        raise MissingTenantCredentials("Exchange endpoint is not in the server allowlist")
    return email, username, password, endpoint


class TenantContextPool:
    """Bounded LRU of isolated mailbox contexts; active requests pin entries."""

    def __init__(self, settings, max_tenants: int = 32):
        self.settings = settings
        self.max_tenants = max(1, int(max_tenants))
        self._entries: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._closed = False

    async def acquire(self, headers) -> tuple[str, Any]:
        email, username, password, endpoint = credentials_from_headers(headers, self.settings)
        identity = json.dumps(
            [endpoint, email.casefold(), username, password],
            ensure_ascii=False, separators=(",", ":"),
        )
        tenant_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        async with self._lock:
            if self._closed:
                raise RuntimeError("tenant context pool is shutting down")
            entry = self._entries.get(tenant_id)
            if entry is None:
                await self._make_room_locked()
                tenant_settings = self.settings.model_copy(update={
                    "ews_server_url": endpoint,
                    "ews_email": email,
                    "ews_username": username,
                    "ews_password": password,
                    "data_dir": str(Path(self.settings.data_dir) / "tenants" / tenant_id),
                })
                context = build_context(tenant_settings, tenant_id=tenant_id)
                await start_connection_manager(context)
                entry = {"context": context, "active": 0}
                self._entries[tenant_id] = entry
            self._entries.move_to_end(tenant_id)
            entry["active"] += 1
            return tenant_id, entry["context"]

    async def release(self, tenant_id: str) -> None:
        async with self._lock:
            entry = self._entries.get(tenant_id)
            if entry is not None:
                entry["active"] = max(0, entry["active"] - 1)

    @asynccontextmanager
    async def lease(self, headers) -> AsyncIterator[Any]:
        tenant_id, context = await self.acquire(headers)
        try:
            yield context
        finally:
            await self.release(tenant_id)

    async def _make_room_locked(self) -> None:
        while len(self._entries) >= self.max_tenants:
            victim = next(
                (key for key, entry in self._entries.items() if entry["active"] == 0),
                None,
            )
            if victim is None:
                raise TenantPoolFull("all tenant contexts are currently in use")
            entry = self._entries.pop(victim)
            await self._dispose(entry["context"])

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            entries = list(self._entries.values())
            self._entries.clear()
        for entry in entries:
            await self._dispose(entry["context"])

    @staticmethod
    async def _dispose(context) -> None:
        try:
            if context.sync is not None:
                await context.sync.stop()
            if context.manager is not None:
                await context.manager.stop()
            if context.cache is not None:
                context.cache.close()
            if context.tenant_id:
                from .ids import evict_aliaser
                evict_aliaser(str(Path(context.settings.data_dir) / "memory"))
            pool = getattr(context.gateway, "_pool", None)
            if pool is not None:
                pool.shutdown(wait=False, cancel_futures=True)
        except Exception as exc:
            logger.warning("tenant context cleanup failed: %s", exc)
