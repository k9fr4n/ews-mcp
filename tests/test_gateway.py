"""Gateway probe/reset behavior — the false-warm fix (Phase B critical #4).

``inbox.total_count`` is a cached property after its first read, so probing
it reported warm forever (the /readyz lie). The probe must round-trip every
call, and reset() must evict exchangelib's protocol cache so a wedged
session actually renegotiates auth.
"""

from unittest.mock import MagicMock

from conftest import make_settings
from exchangelib.errors import UnauthorizedError

from ewsmcp.gateway import client as client_mod
from ewsmcp.gateway.client import EWSGateway


def _gateway_with_mock_account():
    gw = EWSGateway(make_settings())
    account = MagicMock(name="account")
    gw._account = account
    return gw, account


def test_probe_round_trips_on_every_call():
    gw, account = _gateway_with_mock_account()
    assert gw.test_connection() is True
    assert gw.test_connection() is True
    assert account.root.refresh.call_count == 2  # not a cached-property read


def test_probe_failure_is_reported_not_cached():
    gw, account = _gateway_with_mock_account()
    account.root.refresh.side_effect = ConnectionError("front door down")
    assert gw.test_connection() is False
    assert "front door down" in gw.last_connection_error
    account.root.refresh.side_effect = None
    assert gw.test_connection() is True  # recovery observed immediately
    assert gw.last_connection_error is None


def test_reset_evicts_protocol_cache_and_folder_cache(monkeypatch):
    cleared = []
    monkeypatch.setattr(client_mod.CachingProtocol, "clear_cache", lambda: cleared.append(True))
    gw, account = _gateway_with_mock_account()
    gw._folder_cache = {"path": object()}
    gw._folder_cache_ts = 123.0
    gw.reset()
    assert gw._account is None
    account.protocol.close.assert_called_once()
    assert cleared == [True]  # without this, the wedged Protocol comes back
    assert gw._folder_cache == {}
    assert gw._folder_cache_ts == 0.0


def test_probe_marks_auth_failed_on_unauthorized():
    gw, account = _gateway_with_mock_account()
    account.root.refresh.side_effect = UnauthorizedError("Invalid credentials")
    assert gw.test_connection() is False
    assert gw.auth_failed is True
    assert "UnauthorizedError" in gw.last_connection_error


def test_reset_clears_auth_failed():
    gw, account = _gateway_with_mock_account()
    account.root.refresh.side_effect = UnauthorizedError("Invalid credentials")
    gw.test_connection()
    assert gw.auth_failed is True
    gw.reset()
    assert gw.auth_failed is False


def test_disable_ntlm_cbt_forces_send_cbt_false(monkeypatch):
    import exchangelib.protocol as protocol

    calls = []

    def fake_original(auth_type, **kwargs):
        calls.append((auth_type, dict(kwargs)))
        return object()

    monkeypatch.setattr(client_mod, "_NTLM_CBT_PATCHED", False)
    monkeypatch.setattr(protocol, "get_auth_instance", fake_original)

    client_mod._disable_ntlm_cbt()
    protocol.get_auth_instance(protocol.NTLM, username="u", password="p")
    protocol.get_auth_instance("basic", username="u", password="p")

    assert calls[0] == (protocol.NTLM, {"username": "u", "password": "p", "send_cbt": False})
    assert calls[1] == ("basic", {"username": "u", "password": "p"})
    assert client_mod._NTLM_CBT_PATCHED is True


def test_reset_survives_close_and_clear_failures(monkeypatch):
    monkeypatch.setattr(
        client_mod.CachingProtocol,
        "clear_cache",
        lambda: (_ for _ in ()).throw(RuntimeError("cache locked")),
    )
    gw, account = _gateway_with_mock_account()
    account.protocol.close.side_effect = OSError("socket gone")
    gw.reset()  # must not raise
    assert gw._account is None
