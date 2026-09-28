"""EWS gateway — one Account per process, EWS off the event loop.

Auth rule (verified live 2026-06-12): NEVER pin auth_type against this
Exchange; only exchangelib auto-negotiation works, and during front-door
lockdown windows nothing fresh authenticates at all — which is why the
ConnectionManager treats connecting as a state, not a failure.
"""

import asyncio
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

from exchangelib import Account, Configuration, Credentials, DELEGATE, EWSTimeZone
from exchangelib.errors import (
    ErrorInternalServerTransientError,
    ErrorServerBusy,
    UnauthorizedError,
)
from exchangelib.protocol import (
    BaseProtocol,
    CachingProtocol,
    FaultTolerance,
    NoVerifyHTTPAdapter,
)
import exchangelib.protocol as protocol_module

from ..config import Settings
from ..errors import ToolError

logger = logging.getLogger(__name__)

WELL_KNOWN = {
    "f:inbox": "inbox",
    "f:sent": "sent",
    "f:drafts": "drafts",
    "f:trash": "trash",
    "f:junk": "junk",
    "f:outbox": "outbox",
    "f:calendar": "calendar",
    "f:contacts": "contacts",
    "f:tasks": "tasks",
}


def _ews_response_diagnostics(response: Any) -> Dict[str, Any]:
    """Extract a small, allowlisted diagnostic record; never retain payloads."""
    headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
    diagnostics: Dict[str, Any] = {"http_status": response.status_code}
    retry_after = headers.get("retry-after", "").strip()
    if retry_after.isdigit() and int(retry_after) <= 86_400:
        diagnostics["retry_after_s"] = int(retry_after)
    for key, output in (
        ("x-feserver", "frontend"),
        ("x-beserver", "backend"),
        ("request-id", "request_id"),
        ("x-caserrorcode", "cas_error"),
    ):
        value = headers.get(key)
        if value:
            diagnostics[output] = re.sub(r"[^A-Za-z0-9_.:/-]+", "_", value)[:120]

    challenge = headers.get("www-authenticate", "")
    schemes = sorted(
        set(
            re.findall(
                r"(?i)(?<![\w-])(Negotiate|NTLM|Basic|Digest|Bearer)(?![\w-])",
                challenge,
            )
        )
    )
    if schemes:
        diagnostics["auth_schemes"] = ",".join(schemes)

    content = getattr(response, "content", b"")
    if isinstance(content, str):
        content = content.encode("utf-8", errors="replace")
    elif not isinstance(content, bytes):
        content = b""
    if len(content) <= 1_000_000 and b"ResponseCode" in content and b"Error" in content:
        match = re.search(
            rb"<(?:[A-Za-z_][\w.-]*:)?ResponseCode\b[^>]*>\s*"
            rb"(Error[A-Za-z0-9]{1,80})\s*</(?:[A-Za-z_][\w.-]*:)?ResponseCode\s*>",
            content,
        )
        if match:
            diagnostics["ews_code"] = match.group(1).decode("ascii")
    if len(content) <= 1_000_000 and b"BackOffMilliseconds" in content:
        match = re.search(
            rb"<(?:[A-Za-z_][\w.-]*:)?Value\b[^>]*\bName\s*=\s*[\"']"
            rb"BackOffMilliseconds[\"'][^>]*>\s*(\d+)\s*</"
            rb"(?:[A-Za-z_][\w.-]*:)?Value\s*>",
            content,
        )
        if match:
            backoff_ms = int(match.group(1))
            if backoff_ms <= 86_400_000:
                diagnostics["soap_backoff_ms"] = backoff_ms
    return diagnostics


def _diagnostic_fields(diagnostics: Dict[str, Any]) -> str:
    return " ".join(f"{key}={value}" for key, value in diagnostics.items())


_NTLM_CBT_PATCHED = False


def _disable_ntlm_cbt() -> None:
    """Stop requests_ntlm from sending a Channel Binding Token (CBT).

    exchangelib never exposes ``send_cbt``, and ``requests_ntlm`` defaults it
    to True. This Exchange rejects the TLS-server-end-point binding with a 401
    even when the credentials are correct, so we patch the single call site
    (``exchangelib.protocol.get_auth_instance``) to force it off for NTLM.
    Idempotent and process-wide.
    """
    global _NTLM_CBT_PATCHED
    if _NTLM_CBT_PATCHED:
        return
    original = protocol_module.get_auth_instance

    def patched(auth_type, **kwargs):
        if auth_type == protocol_module.NTLM:
            kwargs["send_cbt"] = False
        return original(auth_type, **kwargs)

    protocol_module.get_auth_instance = patched
    _NTLM_CBT_PATCHED = True


class DiagnosticFaultTolerance(FaultTolerance):
    """Keep exchangelib retries, while logging safe response and backoff facts."""

    def __init__(self, max_wait: int = 3600):
        super().__init__(max_wait=max_wait)
        self._diagnostic_local = threading.local()

    def raise_response_errors(self, response: Any) -> None:
        diagnostics = _ews_response_diagnostics(response)
        self._diagnostic_local.response = diagnostics
        ews_code = diagnostics.get("ews_code")
        if response.status_code != 200 or (ews_code and ews_code != "NoError"):
            logger.warning("EWS response diagnostic: %s", _diagnostic_fields(diagnostics))
        # A 401 that still carries an authentication challenge is the server
        # re-challenging after a failed NTLM handshake — a credential (or
        # channel-binding) rejection. exchangelib otherwise treats every 401
        # as retryable ErrorServerBusy, which hammers the account with backoff
        # and masks the real cause as a 503. Surface it as UnauthorizedError.
        if response.status_code == 401 and diagnostics.get("auth_schemes"):
            raise UnauthorizedError(
                f"Invalid credentials for {getattr(response, 'url', 'Exchange')}"
            )
        try:
            result = super().raise_response_errors(response)
        except (ErrorInternalServerTransientError, ErrorServerBusy):
            raise
        except Exception:
            self._diagnostic_local.response = {}
            raise
        if ews_code != "ErrorServerBusy":
            self._diagnostic_local.response = {}
        return result

    def back_off(self, seconds: Optional[float]) -> None:
        diagnostics = getattr(self._diagnostic_local, "response", {})
        if diagnostics.get("soap_backoff_ms") is not None:
            origin = "ews_soap"
        elif diagnostics.get("retry_after_s") is not None:
            origin = "http_retry_after"
        else:
            origin = "exchangelib_fallback"
        summary = " ".join(
            f"{key}={diagnostics[key]}"
            for key in (
                "http_status",
                "ews_code",
                "soap_backoff_ms",
                "retry_after_s",
                "auth_schemes",
                "frontend",
                "request_id",
            )
            if key in diagnostics
        )
        effective_seconds = self.DEFAULT_BACKOFF if seconds is None else seconds
        if effective_seconds > self.max_wait:
            logger.error(
                "EWS retry limit reached: requested_backoff_s=%s max_wait_s=%s "
                "backoff_origin=%s %s",
                effective_seconds,
                self.max_wait,
                origin,
                summary,
            )
        else:
            logger.warning(
                "EWS retry backoff: requested_backoff_s=%s max_wait_s=%s backoff_origin=%s %s",
                effective_seconds,
                self.max_wait,
                origin,
                summary,
            )
        try:
            return super().back_off(seconds)
        finally:
            self._diagnostic_local.response = {}


class EWSGateway:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._account: Optional[Account] = None
        self._account_lock = threading.Lock()
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, settings.ews_max_concurrency),
            thread_name_prefix="ews",
        )
        self.last_connection_error: Optional[str] = None
        self.auth_failed: bool = False
        self._folder_cache: Dict[str, Any] = {}
        self._folder_cache_ts = 0.0
        if settings.ews_insecure_skip_verify:
            BaseProtocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter
            logger.warning("TLS verification DISABLED for Exchange traffic")
        if not settings.ews_ntlm_send_cbt:
            _disable_ntlm_cbt()
            logger.info("NTLM Channel Binding Token (CBT) disabled for this Exchange")

    # ------------------------------------------------------------- account

    @property
    def account(self) -> Account:
        with self._account_lock:
            if self._account is None:
                self._account = self._build_account()
            return self._account

    def _build_account(self) -> Account:
        s = self.settings
        BaseProtocol.TIMEOUT = s.request_timeout
        kwargs: Dict[str, Any] = dict(
            service_endpoint=s.ews_server_url,
            credentials=Credentials(s.ews_username or s.ews_email, s.ews_password or ""),
            retry_policy=DiagnosticFaultTolerance(max_wait=s.ews_retry_max_wait_seconds),
        )
        if s.ews_auth_type_force:  # escape hatch for a DIFFERENT Exchange only
            logger.warning(
                "auth_type FORCED to %s — the primary Exchange requires auto-negotiation",
                s.ews_auth_type_force,
            )
            kwargs["auth_type"] = s.ews_auth_type_force
        config = Configuration(**kwargs)
        return Account(
            primary_smtp_address=s.ews_email,
            config=config,
            autodiscover=False,
            access_type=DELEGATE,
            default_timezone=EWSTimeZone(s.ews_tz),
        )

    def reset(self) -> None:
        """Drop the cached account AND exchangelib's protocol-cache entry.

        Dropping only our Account is not enough: ``CachingProtocol`` hands
        the same wedged Protocol (with its already-negotiated auth type)
        right back on the next build, so a session that died mid-outage
        would never renegotiate. Clearing the cache forces a genuinely
        fresh session + auth negotiation on the next access.
        """
        with self._account_lock:
            if self._account is not None:
                try:
                    self._account.protocol.close()
                except Exception:
                    pass
                self._account = None
        try:
            CachingProtocol.clear_cache()
        except Exception as e:
            logger.debug("protocol cache clear failed: %s", e)
        self._folder_cache.clear()
        self._folder_cache_ts = 0.0
        self.auth_failed = False

    def test_connection(self) -> bool:
        """Real network probe — must round-trip on EVERY call.

        ``inbox.total_count`` is a cached property after its first read, so
        probing it reported warm forever once it had succeeded once (the
        false-warm bug: /readyz lied through outages and the reset ladder
        never ran). ``root.refresh()`` issues a GetFolder request each time.
        """
        try:
            self.account.root.refresh()
            self.last_connection_error = None
            self.auth_failed = False
            return True
        except UnauthorizedError as e:
            self.auth_failed = True
            self.last_connection_error = f"{type(e).__name__}: {e}"
            logger.error("connection test failed (authentication): %s", self.last_connection_error)
            return False
        except Exception as e:
            self.auth_failed = False
            self.last_connection_error = f"{type(e).__name__}: {e}"
            logger.error("connection test failed: %s", self.last_connection_error)
            return False

    # ------------------------------------------------------------- calling

    async def call(self, fn: Callable[[Account], Any]) -> Any:
        """Run blocking EWS work on the bounded pool; the pool size IS the
        EWS concurrency cap (polite guest on the per-user throttle budget)."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, lambda: fn(self.account))

    # ------------------------------------------------------------- folders

    def _folder_map(self, account: Account) -> Dict[str, Any]:
        """{raw_id|lower_path: Folder} cache, rebuilt every 300s (sync)."""
        now = time.time()
        if self._folder_cache and now - self._folder_cache_ts < 300:
            return self._folder_cache
        cache: Dict[str, Any] = {}
        try:
            for folder in account.msg_folder_root.walk():
                if getattr(folder, "id", None):
                    cache[folder.id] = folder
                try:
                    path = (
                        "/".join(
                            p.name
                            for p in folder.parts[2:]  # drop root/Top of Info Store
                        )
                        or folder.name
                    )
                except Exception:
                    path = folder.name
                cache[path.lower()] = folder
        except Exception as e:
            logger.warning("folder walk failed: %s", e)
        if cache:
            self._folder_cache = cache
            self._folder_cache_ts = now
        return cache

    def resolve_folder(self, account: Account, ref: Optional[str], aliaser) -> Any:
        """well-known alias | folder alias (f12) | path | raw id → Folder (sync)."""
        if not ref:
            return account.inbox
        key = ref.strip()
        attr = WELL_KNOWN.get(key.lower()) or WELL_KNOWN.get(f"f:{key.lower()}")
        if attr:
            return getattr(account, attr)
        try:
            key = aliaser.resolve(key)  # f12 → raw id; raw/path pass through
        except KeyError as e:
            raise ToolError("validation", str(e.args[0] if e.args else e))
        cache = self._folder_map(account)
        folder = cache.get(key) or cache.get(key.lower())
        if folder is None:
            raise ToolError(
                "not_found",
                f"No folder matches {ref!r}.",
                hint="Use list_folders and pass one of its ids or paths.",
            )
        return folder


def paginate(
    query: Any, *, offset: int, limit: int, chunk: int = 50
) -> Tuple[List[Any], Optional[int]]:
    """Materialize query[offset:offset+limit] in chunks (sync, raises on
    mid-iteration failure — the caller's error mapper classifies it).

    Returns ``(items, next_offset)``. NEVER calls ``QuerySet.count()`` —
    in exchangelib that iterates every matching id server-side, so a 20k
    inbox paid ~20k ids of round trips on every "read 10 emails". Whether
    another page exists comes from a one-item lookahead instead; callers
    that want an exact total use a refreshed ``folder.total_count`` (only
    valid for unfiltered listings) or a local mirror count.
    """
    offset = max(0, offset)
    limit = max(0, limit)
    lookahead = limit + 1
    items: List[Any] = []
    cursor = offset
    chunk = max(1, min(chunk, 250))
    while len(items) < lookahead:
        want = min(chunk, lookahead - len(items))
        batch = list(query[cursor : cursor + want])
        if not batch:
            break
        items.extend(batch)
        cursor += len(batch)
        if len(batch) < want:
            break
    next_offset = offset + limit if len(items) > limit else None
    return items[:limit], next_offset
