from types import SimpleNamespace

import pytest
from exchangelib.errors import ErrorServerBusy, RateLimitError

from ewsmcp.gateway.client import DiagnosticFaultTolerance, _ews_response_diagnostics


def test_response_diagnostics_allowlist_auth_challenge_and_omit_secrets():
    response = SimpleNamespace(
        status_code=401,
        headers={
            "WWW-Authenticate": "Negotiate private-token, NTLM",
            "Retry-After": "30",
            "X-FEServer": "EX-FE-01",
            "request-id": "request-123",
            "Authorization": "Bearer secret-value",
        },
        content=b"private response body",
    )

    diagnostics = _ews_response_diagnostics(response)

    assert diagnostics == {
        "http_status": 401,
        "retry_after_s": 30,
        "frontend": "EX-FE-01",
        "request_id": "request-123",
        "auth_schemes": "NTLM,Negotiate",
    }
    assert "secret-value" not in str(diagnostics)
    assert "private response body" not in str(diagnostics)


def test_response_diagnostics_extract_soap_busy_code_and_backoff():
    response = SimpleNamespace(
        status_code=200,
        headers={},
        content=(
            b'<s:Envelope xmlns:s="soap" xmlns:m="messages" xmlns:t="types">'
            b"<s:Body><m:ResponseCode>ErrorServerBusy</m:ResponseCode>"
            b'<t:Value Name="BackOffMilliseconds">320000</t:Value>'
            b"</s:Body></s:Envelope>"
        ),
    )

    diagnostics = _ews_response_diagnostics(response)

    assert diagnostics == {
        "http_status": 200,
        "ews_code": "ErrorServerBusy",
        "soap_backoff_ms": 320000,
    }


def test_retry_limit_log_correlates_http_auth_challenge_without_logging_token(caplog):
    policy = DiagnosticFaultTolerance(max_wait=300)
    response = SimpleNamespace(
        status_code=401,
        headers={
            "WWW-Authenticate": "Negotiate private-token",
            "request-id": "request-456",
        },
        content=b"private response body",
    )

    with pytest.raises(ErrorServerBusy):
        policy.raise_response_errors(response)
    with pytest.raises(RateLimitError):
        policy.back_off(320)

    assert "http_status=401" in caplog.text
    assert "auth_schemes=Negotiate" in caplog.text
    assert "requested_backoff_s=320" in caplog.text
    assert "max_wait_s=300" in caplog.text
    assert "request_id=request-456" in caplog.text
    assert "private-token" not in caplog.text
    assert "private response body" not in caplog.text


def test_retry_limit_log_identifies_soap_backoff(caplog):
    policy = DiagnosticFaultTolerance(max_wait=300)
    response = SimpleNamespace(
        status_code=200,
        headers={},
        content=(
            b'<Envelope xmlns:m="messages" xmlns:t="types">'
            b"<m:ResponseCode>ErrorServerBusy</m:ResponseCode>"
            b'<t:Value Name="BackOffMilliseconds">320000</t:Value>'
            b"</Envelope>"
        ),
    )

    policy.raise_response_errors(response)
    with pytest.raises(RateLimitError):
        policy.back_off(320)

    assert "ews_code=ErrorServerBusy" in caplog.text
    assert "soap_backoff_ms=320000" in caplog.text
    assert "backoff_origin=ews_soap" in caplog.text
