"""ConnectionManager auth-failure behavior: no hammering, observable state.

A rejected login (bad/expired password, wrong mailbox, or a channel-binding
mismatch) must stop the warmup loop and surface as ``auth_failed`` instead of
being retried forever (which risks locking the account) and masked as a 503.
"""

import asyncio
from unittest.mock import MagicMock

from ewsmcp.gateway.connection import STATE_AUTH_FAILED, ConnectionManager


def _manager(client):
    return ConnectionManager(client, initial_backoff=0.001, max_backoff=0.01)


def test_try_connect_marks_auth_failed():
    client = MagicMock()
    client.test_connection.return_value = False
    client.last_connection_error = "UnauthorizedError: Invalid credentials"
    client.auth_failed = True

    mgr = _manager(client)

    assert mgr._try_connect() is False
    assert mgr.state == STATE_AUTH_FAILED
    assert mgr.status()["last_error"].startswith("UnauthorizedError")
    assert mgr.status()["next_retry_in_s"] is None


def test_try_connect_non_auth_failure_stays_connecting():
    client = MagicMock()
    client.test_connection.return_value = False
    client.last_connection_error = "ConnectionError: reset"
    client.auth_failed = False

    mgr = _manager(client)

    assert mgr._try_connect() is False
    assert mgr.state == "connecting"


def test_warmup_loop_stops_on_auth_failed():
    client = MagicMock()
    client.test_connection.return_value = False
    client.last_connection_error = "UnauthorizedError: Invalid credentials"
    client.auth_failed = True

    mgr = _manager(client)

    asyncio.run(mgr._warmup_loop())

    assert mgr.state == STATE_AUTH_FAILED
    client.reset.assert_not_called()  # no reset ladder, no retry
    assert client.test_connection.call_count == 1
