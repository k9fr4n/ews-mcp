"""Settings guards: absolute data_dir + the synced-folder refusal.

The data dir holds mail-at-rest (aliases, audit chain, cache mirror) —
booting with it inside OneDrive/Dropbox/… replicates a mailbox to every
synced device, so the default posture is refusal with an explicit escape
hatch.
"""

import pytest

from conftest import make_settings


def test_data_dir_is_always_absolute(tmp_path):
    s = make_settings(data_dir=str(tmp_path / "d"))
    import os
    assert os.path.isabs(s.data_dir)


def test_default_data_dir_is_home_scoped_absolute(monkeypatch, tmp_path):
    monkeypatch.delenv("DATA_DIR", raising=False)
    s = make_settings()
    assert s.data_dir.endswith(".ewsmcp")


@pytest.mark.parametrize("marker", ["OneDrive", "Dropbox", "Google Drive"])
def test_synced_paths_are_refused(tmp_path, marker):
    with pytest.raises(Exception, match="synced"):
        make_settings(data_dir=str(tmp_path / marker / "data"))


def test_synced_path_escape_hatch(tmp_path):
    s = make_settings(data_dir=str(tmp_path / "OneDrive" / "data"),
                      data_dir_allow_synced=True)
    assert "OneDrive" in s.data_dir


def test_confirm_ttl_default_matches_confirm_module():
    from ewsmcp import confirm
    assert make_settings().confirm_ttl_seconds == confirm.DEFAULT_TTL_SECONDS == 600


def test_header_auth_allows_credentials_to_be_supplied_per_request():
    settings = make_settings(
        ews_http_header_auth=True, mcp_transport="http",
        ews_email=None, ews_username=None, ews_password=None,
    )
    assert settings.ews_email is None


def test_header_auth_requires_http_transport():
    with pytest.raises(Exception, match="MCP_TRANSPORT=http"):
        make_settings(ews_http_header_auth=True)


def test_non_loopback_http_requires_transport_authentication():
    with pytest.raises(Exception, match="MCP_API_KEY"):
        make_settings(mcp_transport="http", mcp_host="0.0.0.0")
